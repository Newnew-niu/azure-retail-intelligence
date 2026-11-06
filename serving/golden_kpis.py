"""The README's headline KPIs as DuckDB-dialect SQL, each returning a single value.

scripts/export_serving_db.py runs these on LocalDB (translated to T-SQL) and saves the
results as data/serving_baseline.json. serving/tests/test_golden_numbers.py runs the same
text through the API on the DuckDB export. Two engines must agree, and no expected number
is typed by hand. `readme` is how the value appears in README.md.
"""
from __future__ import annotations

WINDOW = "purchase_date_key BETWEEN 20170101 AND 20180831"  # reporting window of the README
SALES = "order_status NOT IN ('canceled', 'unavailable')"

GOLDEN_KPIS = {
    "sales_orders": {
        "sql": f"SELECT COUNT(*) FROM dw.fact_orders WHERE {SALES} AND {WINDOW}",
        "readme": lambda v: f"{v:,.0f} orders",
    },
    "product_sales": {
        "sql": f"SELECT SUM(price) FROM dw.fact_order_items WHERE {SALES} AND {WINDOW}",
        "readme": lambda v: f"{v / 1_000_000:.1f} M BRL",
    },
    "average_order_value": {
        "sql": f"SELECT SUM(items_price + items_freight) * 1.0 / COUNT(*) FROM dw.fact_orders "
               f"WHERE {SALES} AND {WINDOW} AND item_count > 0",
        "readme": lambda v: f"{v:.0f} BRL",
    },
    "average_delivery_days": {
        "sql": f"SELECT AVG(delivery_days) FROM dw.fact_orders WHERE is_delivered = 1 AND {WINDOW}",
        "readme": lambda v: f"{v:.1f} days",
    },
    "late_rate": {
        "sql": f"SELECT SUM(CAST(is_late AS INT)) * 1.0 / COUNT(*) FROM dw.fact_orders "
               f"WHERE is_delivered = 1 AND {WINDOW}",
        "readme": lambda v: f"{v * 100:.1f} %",
    },
    "repeat_customer_rate": {
        "sql": "SELECT SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) FROM ("
               "SELECT c.customer_unique_id, COUNT(*) AS n FROM dw.fact_orders AS f "
               "JOIN dw.dim_customer AS c ON c.customer_key = f.customer_key "
               f"WHERE f.{SALES} AND f.{WINDOW} GROUP BY c.customer_unique_id) AS p",
        "readme": lambda v: f"{v * 100:.0f} %",
    },
}
