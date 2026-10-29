"""Export the data behind the web dashboard (dashboard/data.json) from the dw star schema.

    python scripts/export_dashboard_data.py            # LocalDB by default; Azure SQL via SQL_SERVER/SQL_AUTH

The web dashboard is a static twin of the Power BI report for people without Power BI.
It uses the same KPI definitions as the DAX measures (scripts/build_powerbi_model.py) and
the same reporting window (Jan 2017 - Aug 2018). Everything is pre-aggregated per
(month, customer state) so the page can filter by month range and state in the browser:

  cells       per month x state: order-level sums (sales orders, product sales, delivery, reviews, payments)
  review      per month x state x delivery status: review score sum and count
  categories  per month x state x category: items, product sales, and review of the orders containing them
  payments    per month x state x payment type: payment value
  people      one entry per sales order: (month, state, person) - distinct customers and the
              repeat rate cannot be summed across cells, so they are counted in the browser

Money is stored in cents and averages as sums + counts (scores and days in hundredths), so
all totals are exact integers and the page reproduces the SQL values to the cent.
tests/test_dashboard.py checks the page's calculations against SQL.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ingestion import db  # noqa: E402

OUT = PROJECT_ROOT / "dashboard" / "data.json"
FIRST_KEY, LAST_KEY = 20170101, 20180831  # reporting window, as dim_date[In Reporting Window]
SALES = "order_status NOT IN (N'canceled', N'unavailable')"
DELIVERY_STATUSES = ["On time", "Late", "Not delivered"]

# Every query returns (year_month, state, ...); facts are joined to the customer of the order.
ORDER_CELLS = f"""
SELECT d.year_month, c.state,
       SUM(CASE WHEN f.{SALES} THEN 1 ELSE 0 END)                                     AS sales_orders,
       SUM(CASE WHEN f.{SALES} AND f.item_count > 0 THEN 1 ELSE 0 END)                AS sales_orders_with_items,
       SUM(CASE WHEN f.is_delivered = 1 THEN 1 ELSE 0 END)                            AS delivered,
       SUM(CASE WHEN f.is_delivered = 1 THEN CAST(f.delivery_days * 100 AS BIGINT) ELSE 0 END) AS delivery_days_x100,
       SUM(CASE WHEN f.is_late = 1 THEN 1 ELSE 0 END)                                 AS late,
       SUM(CASE WHEN f.review_count > 0 THEN CAST(f.review_score_avg * 100 AS BIGINT) ELSE 0 END) AS review_x100,
       SUM(CASE WHEN f.review_count > 0 THEN 1 ELSE 0 END)                            AS reviewed,
       SUM(CASE WHEN f.item_count > 0 AND f.review_count > 0 THEN CAST(f.review_score_avg * 100 AS BIGINT) ELSE 0 END)
                                                                                      AS item_orders_review_x100,
       SUM(CASE WHEN f.item_count > 0 AND f.review_count > 0 THEN 1 ELSE 0 END)       AS item_orders_reviewed
  FROM dw.fact_orders AS f
  JOIN dw.dim_date AS d ON d.date_key = f.purchase_date_key
  JOIN dw.dim_customer AS c ON c.customer_key = f.customer_key
 WHERE f.purchase_date_key BETWEEN {FIRST_KEY} AND {LAST_KEY}
 GROUP BY d.year_month, c.state"""

ITEM_CELLS = f"""
SELECT d.year_month, c.state, COUNT(*) AS items, SUM(CAST(i.price * 100 AS BIGINT)) AS sales_cents,
       SUM(CAST(i.freight_value * 100 AS BIGINT)) AS freight_cents
  FROM dw.fact_order_items AS i
  JOIN dw.dim_date AS d ON d.date_key = i.purchase_date_key
  JOIN dw.dim_customer AS c ON c.customer_key = i.customer_key
 WHERE i.purchase_date_key BETWEEN {FIRST_KEY} AND {LAST_KEY} AND i.{SALES}
 GROUP BY d.year_month, c.state"""

PAYMENT_CELLS = f"""
SELECT d.year_month, c.state, p.payment_type, SUM(CAST(p.payment_value * 100 AS BIGINT)) AS value_cents
  FROM dw.fact_payments AS p
  JOIN dw.dim_date AS d ON d.date_key = p.purchase_date_key
  JOIN dw.dim_customer AS c ON c.customer_key = p.customer_key
 WHERE p.purchase_date_key BETWEEN {FIRST_KEY} AND {LAST_KEY} AND p.{SALES}
 GROUP BY d.year_month, c.state, p.payment_type"""

# Same as the Power BI visual "Avg Review Score by delivery_status": all orders, any status
REVIEW_CELLS = f"""
SELECT d.year_month, c.state, f.delivery_status,
       SUM(CAST(f.review_score_avg * 100 AS BIGINT)) AS review_x100, COUNT(*) AS reviewed
  FROM dw.fact_orders AS f
  JOIN dw.dim_date AS d ON d.date_key = f.purchase_date_key
  JOIN dw.dim_customer AS c ON c.customer_key = f.customer_key
 WHERE f.purchase_date_key BETWEEN {FIRST_KEY} AND {LAST_KEY} AND f.review_count > 0
 GROUP BY d.year_month, c.state, f.delivery_status"""

# Items and sales: sales orders only (as [Items Sold] / [Product Sales]).
# Review: every order containing an item of the category, any status (as [Order Review Score],
# which uses VALUES(fact_order_items[order_id]) without a status filter); each order once per category.
CATEGORY_CELLS = f"""
WITH item AS (
    SELECT d.year_month, c.state, p.category_name_en, i.order_id, i.price,
           CASE WHEN i.{SALES} THEN 1 ELSE 0 END AS is_sales
      FROM dw.fact_order_items AS i
      JOIN dw.dim_date AS d ON d.date_key = i.purchase_date_key
      JOIN dw.dim_customer AS c ON c.customer_key = i.customer_key
      JOIN dw.dim_product AS p ON p.product_key = i.product_key
     WHERE i.purchase_date_key BETWEEN {FIRST_KEY} AND {LAST_KEY}
),
sales AS (
    SELECT year_month, state, category_name_en, SUM(is_sales) AS items,
           SUM(CASE WHEN is_sales = 1 THEN CAST(price * 100 AS BIGINT) ELSE 0 END) AS sales_cents
      FROM item GROUP BY year_month, state, category_name_en
),
reviews AS (
    SELECT o.year_month, o.state, o.category_name_en,
           SUM(CAST(f.review_score_avg * 100 AS BIGINT)) AS review_x100, COUNT(*) AS reviewed
      FROM (SELECT DISTINCT year_month, state, category_name_en, order_id FROM item) AS o
      JOIN dw.fact_orders AS f ON f.order_id = o.order_id
     WHERE f.review_count > 0
     GROUP BY o.year_month, o.state, o.category_name_en
)
SELECT s.year_month, s.state, s.category_name_en, s.items, s.sales_cents,
       ISNULL(r.review_x100, 0), ISNULL(r.reviewed, 0)
  FROM sales AS s
  LEFT JOIN reviews AS r ON r.year_month = s.year_month AND r.state = s.state AND r.category_name_en = s.category_name_en"""

PEOPLE = f"""
SELECT d.year_month, c.state, c.customer_unique_id
  FROM dw.fact_orders AS f
  JOIN dw.dim_date AS d ON d.date_key = f.purchase_date_key
  JOIN dw.dim_customer AS c ON c.customer_key = f.customer_key
 WHERE f.purchase_date_key BETWEEN {FIRST_KEY} AND {LAST_KEY} AND f.{SALES}"""


def export() -> dict:
    with db.connect() as conn:
        def rows(sql):
            return [tuple(r) for r in conn.execute(sql).fetchall()]
        order_cells, item_cells = rows(ORDER_CELLS), rows(ITEM_CELLS)
        payment_cells, review_cells = rows(PAYMENT_CELLS), rows(REVIEW_CELLS)
        category_cells, people = rows(CATEGORY_CELLS), rows(PEOPLE)

    months = sorted({r[0] for r in order_cells})
    states = sorted({r[1] for r in order_cells})
    categories = sorted({r[2] for r in category_cells})
    payment_types = sorted({r[2] for r in payment_cells})
    m = {v: i for i, v in enumerate(months)}
    s = {v: i for i, v in enumerate(states)}

    items = {(r[0], r[1]): r[2:] for r in item_cells}
    cells = []
    for ym, st, *order_values in order_cells:
        n_items, sales_cents, freight_cents = items.get((ym, st), (0, 0, 0))
        cells.append([m[ym], s[st], *map(int, order_values), int(n_items), int(sales_cents), int(freight_cents)])

    person_ids: dict[str, int] = {}
    people_m, people_s, people_p = [], [], []
    for ym, st, person in people:
        people_m.append(m[ym]); people_s.append(s[st])
        people_p.append(person_ids.setdefault(person, len(person_ids)))

    return {
        "meta": {"generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                 "source": "dw star schema (Azure SQL / LocalDB, identical)", "currency": "BRL",
                 "window": [months[0], months[-1]]},
        "months": months, "states": states, "categories": categories, "paymentTypes": payment_types,
        "deliveryStatuses": DELIVERY_STATUSES,
        "cellFields": ["m", "s", "salesOrders", "salesOrdersWithItems", "delivered", "deliveryDaysX100", "late",
                       "reviewX100", "reviewed", "itemOrdersReviewX100", "itemOrdersReviewed",
                       "items", "salesCents", "freightCents"],
        "cells": cells,
        "review": [[m[ym], s[st], DELIVERY_STATUSES.index(status), int(x), int(n)] for ym, st, status, x, n in review_cells],
        "categories_cells": [[m[ym], s[st], categories.index(cat), int(n), int(c), int(x), int(r)]
                             for ym, st, cat, n, c, x, r in category_cells],
        "payments": [[m[ym], s[st], payment_types.index(t), int(v)] for ym, st, t, v in payment_cells],
        "people": {"m": people_m, "s": people_s, "p": people_p},
    }


def main() -> int:
    data = export()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(PROJECT_ROOT)} ({OUT.stat().st_size / 1e6:.2f} MB): "
          f"{len(data['cells'])} cells, {len(data['categories_cells'])} category cells, "
          f"{len(data['people']['p']):,} sales orders, {len(set(data['people']['p'])):,} people")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
