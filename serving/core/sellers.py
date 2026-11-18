"""Seller list and seller detail, built on fixed, parameterised queries.

Callers choose values (a state, an id prefix, a sort key, a page), never SQL. Values travel as
bound parameters; the sort column comes from a fixed mapping and LIMIT and OFFSET are integers
checked here (see backends.py for why they are not placeholders). The SQL is DuckDB dialect, so
the azuresql backend translates it like every other query.

Definitions, all inside the reporting window of the catalog and on sales orders only (status
not canceled or unavailable). One seller-order is one order counted for one seller: an order
with items from two sellers counts once for each.
- orders: seller-orders. items_sold: order items.
- product_sales: SUM(item price), excluding freight.
- average_order_value: the seller's (price + freight) per seller-order.
- late_rate: dispatched seller-orders handed to the carrier after the seller's shipping
  deadline (dates, not times), divided by dispatched seller-orders.
- review_score: mean of the order review score over seller-orders that have a review.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from serving.core.audit import AuditLog
from serving.core.backends import Backend
from serving.core.errors import QueryFailed, QueryTimedOut, SellerNotFound
from serving.core.health_signals import DISCLAIMER, health_signals
from serving.core.service import json_safe

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25
SORT_COLUMNS = {  # public sort key -> column of the list query; the only way a sort reaches SQL
    "product_sales": "product_sales",
    "orders": "orders",
    "late_rate": "late_rate",
    "review_score": "review_score",
}
DIRECTIONS = {"asc": "ASC", "desc": "DESC"}

# One row per seller and order. {seller_filter} is one of the fixed strings in SELLER_FILTERS.
SELLER_ORDERS_CTE = """
seller_orders AS (
    SELECT s.seller_id,
           s.state AS seller_state,
           i.order_id,
           d.year_month,
           COUNT(*) AS items,
           SUM(i.price) AS product_sales,
           SUM(i.freight_value) AS freight,
           MAX(i.shipping_limit_date_key) AS shipping_limit_date_key
      FROM dw.fact_order_items AS i
      JOIN dw.dim_seller AS s ON s.seller_key = i.seller_key
      JOIN dw.dim_date AS d ON d.date_key = i.purchase_date_key
     WHERE i.order_status NOT IN ('canceled', 'unavailable')
       AND i.purchase_date_key BETWEEN ? AND ?{seller_filter}
     GROUP BY s.seller_id, s.state, i.order_id, d.year_month
)"""
SELLER_FILTERS = {
    "state": "\n       AND s.state = ?",
    "prefix": "\n       AND s.seller_id LIKE ?",
    "seller": "\n       AND s.seller_id = ?",
}

# Additive measures, so monthly rows can be summed into the seller summary.
COUNTS = """
           COUNT(*) AS orders,
           SUM(so.items) AS items_sold,
           SUM(so.product_sales) AS product_sales,
           SUM(so.freight) AS freight,
           SUM(CASE WHEN o.delivered_carrier_date_key IS NOT NULL THEN 1 ELSE 0 END) AS dispatched_orders,
           SUM(CASE WHEN o.delivered_carrier_date_key > so.shipping_limit_date_key THEN 1 ELSE 0 END) AS late_orders,
           COUNT(o.review_score_avg) AS reviewed_orders,
           SUM(o.review_score_avg) AS review_total"""

LIST_SQL = """
WITH {cte},
sellers AS (
    SELECT so.seller_id,
           so.seller_state,{counts}
      FROM seller_orders AS so
      JOIN dw.fact_orders AS o ON o.order_id = so.order_id
     GROUP BY so.seller_id, so.seller_state
)
SELECT *
  FROM (
    SELECT seller_id, seller_state, orders, items_sold, product_sales,
           (product_sales + freight) / orders AS average_order_value,
           CAST(late_orders AS DOUBLE) / NULLIF(dispatched_orders, 0) AS late_rate,
           CAST(review_total AS DOUBLE) / NULLIF(reviewed_orders, 0) AS review_score
      FROM sellers
  ) AS ranked
 ORDER BY {sort} {direction}, seller_id
 LIMIT {limit} OFFSET {offset}"""
# The outer SELECT makes the KPIs real columns: T-SQL cannot use a column alias inside the
# NULLS LAST expression that sqlglot adds to ORDER BY.

COUNT_SQL = """
WITH {cte}
SELECT COUNT(DISTINCT seller_id) AS sellers FROM seller_orders"""

MONTHLY_SQL = """
WITH {cte}
SELECT so.seller_state,
       so.year_month,{counts}
  FROM seller_orders AS so
  JOIN dw.fact_orders AS o ON o.order_id = so.order_id
 GROUP BY so.seller_state, so.year_month
 ORDER BY so.year_month"""

ADDITIVE = ("orders", "items_sold", "product_sales", "freight", "dispatched_orders", "late_orders",
            "reviewed_orders", "review_total")


def window_months(first_date_key: int, last_date_key: int) -> list[str]:
    """Every month of the window as yyyy-mm, so months without orders still appear."""
    year, month = divmod(first_date_key // 100, 100)
    last = last_date_key // 100
    months = []
    while year * 100 + month <= last:
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def ratios(row: dict) -> dict:
    """The derived KPIs of one summed row. None where the denominator is zero."""
    def divide(numerator, denominator):
        return float(Decimal(str(numerator)) / Decimal(str(denominator))) if denominator else None
    return {
        "orders": int(row["orders"]),
        "items_sold": int(row["items_sold"]),
        "product_sales": float(row["product_sales"]),
        "average_order_value": divide(row["product_sales"] + row["freight"], row["orders"]),
        "late_rate": divide(row["late_orders"], row["dispatched_orders"]),
        "review_score": divide(row["review_total"], row["reviewed_orders"]),
        "dispatched_orders": int(row["dispatched_orders"]),
        "reviewed_orders": int(row["reviewed_orders"]),
    }


@dataclass(frozen=True)
class Query:
    name: str
    sql: str
    params: tuple


class SellerService:
    def __init__(self, backend: Backend, audit: AuditLog, reporting_window: dict,
                 timeout_seconds: float) -> None:
        self.backend = backend
        self.audit = audit
        self.timeout_seconds = timeout_seconds
        self.first_date_key = int(reporting_window["first_purchase_date_key"])
        self.last_date_key = int(reporting_window["last_purchase_date_key"])
        self.months = window_months(self.first_date_key, self.last_date_key)

    def _cte(self, filters: Sequence[str]) -> str:
        return SELLER_ORDERS_CTE.format(seller_filter="".join(SELLER_FILTERS[f] for f in filters))

    def _run(self, query: Query, max_rows: int) -> list[dict]:
        """Run one fixed query and audit it like run_query: the query name and its parameters."""
        started = time.perf_counter()
        label = f"{query.name} {json.dumps(list(query.params))}"
        try:
            columns, rows = self.backend.execute(query.sql, max_rows, self.timeout_seconds, params=query.params)
        except (QueryFailed, QueryTimedOut) as exc:
            self.audit.record("api", label, "error", (time.perf_counter() - started) * 1000, reason=str(exc))
            raise
        self.audit.record("api", label, "ok", (time.perf_counter() - started) * 1000, row_count=len(rows))
        return [dict(zip(columns, row)) for row in rows]

    def list_sellers(self, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE, state: str | None = None,
                     prefix: str | None = None, sort: str = "product_sales", order: str = "desc") -> dict:
        if sort not in SORT_COLUMNS or order not in DIRECTIONS:
            raise ValueError(f"Unknown sort '{sort}' or order '{order}'")
        page, page_size = int(page), int(page_size)  # integers only: they are written into the SQL
        if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError("page must be >= 1 and page_size between 1 and 100")

        filters, params = [], [self.first_date_key, self.last_date_key]
        if state:
            filters.append("state")
            params.append(state)
        if prefix:
            filters.append("prefix")
            params.append(prefix + "%")  # the API allows only hex characters, so no LIKE wildcards
        cte = self._cte(filters)

        total = self._run(Query("sellers.count", COUNT_SQL.format(cte=cte), tuple(params)), 1)[0]["sellers"]
        sql = LIST_SQL.format(cte=cte, counts=COUNTS, sort=SORT_COLUMNS[sort], direction=DIRECTIONS[order],
                              limit=page_size, offset=(page - 1) * page_size)
        rows = self._run(Query("sellers.list", sql, tuple(params)), page_size)
        items = [{key: json_safe(value) for key, value in row.items()} for row in rows]
        return {"items": items, "page": page, "page_size": page_size, "total": int(total),
                "total_pages": -(-int(total) // page_size), "sort": sort, "order": order}

    def get_seller(self, seller_id: str) -> dict:
        cte = self._cte(["seller"])
        params = (self.first_date_key, self.last_date_key, seller_id)
        rows = self._run(Query("sellers.detail", MONTHLY_SQL.format(cte=cte, counts=COUNTS), params),
                         len(self.months) * 2)
        if not rows:
            raise SellerNotFound(f"Seller '{seller_id}' has no sales orders in the reporting window")

        by_month = {row["year_month"]: row for row in rows}
        zero = {field: 0 for field in ADDITIVE}
        monthly = [{"year_month": month, **{f: by_month.get(month, zero)[f] or 0 for f in ADDITIVE}}
                   for month in self.months]
        summary = {f: sum((Decimal(str(m[f])) for m in monthly), Decimal(0)) for f in ADDITIVE}
        return {
            "seller_id": seller_id,
            "seller_state": rows[0]["seller_state"],
            "window": {"first_month": self.months[0], "last_month": self.months[-1]},
            "summary": ratios(summary),
            "monthly": [{"year_month": m["year_month"], **ratios({f: Decimal(str(m[f])) for f in ADDITIVE})}
                        for m in monthly],
            "signals": health_signals(monthly),
            "disclaimer": DISCLAIMER,
        }
