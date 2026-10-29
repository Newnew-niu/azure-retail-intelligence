"""The web dashboard must show the same numbers as SQL (and therefore as Power BI).

Runs dashboard/metrics.js under Node on dashboard/data.json and compares its results with
independent SQL queries on the dw star schema, for the whole reporting window and for a
filtered slice (one state, three months). Skipped without Node or the development database.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ingestion import db

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA = PROJECT_ROOT / "dashboard" / "data.json"
DEV_DATABASE = db.database_name()  # captured before the SQL test fixture switches databases
SALES = "f.order_status NOT IN (N'canceled', N'unavailable')"
FILTERS = [("2017-01", "2018-08", "ALL"), ("2018-01", "2018-03", "SP")]


@pytest.fixture(scope="module")
def conn():
    if not shutil.which("node") or not DATA.is_file():
        pytest.skip("Node.js or dashboard/data.json not available")
    try:
        connection = db.connect(database=DEV_DATABASE)
    except Exception:
        pytest.skip("development database not available")
    yield connection
    connection.close()


def page(first, last, state):
    out = subprocess.run(["node", "tests/dashboard_metrics.mjs", str(DATA), first, last, state],
                         cwd=PROJECT_ROOT, capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def where(first, last, state, alias="f"):
    keys = f"{alias}.purchase_date_key BETWEEN {first.replace('-', '')}01 AND {last.replace('-', '')}31"
    return keys + ("" if state == "ALL" else f" AND c.state = '{state}'")


def sql_kpis(conn, first, last, state):
    w = where(first, last, state)
    one = lambda q: conn.execute(q).fetchone()  # noqa: E731
    orders = f"dw.fact_orders AS f JOIN dw.dim_customer AS c ON c.customer_key = f.customer_key WHERE {w}"
    items = (f"dw.fact_order_items AS f JOIN dw.dim_customer AS c ON c.customer_key = f.customer_key "
             f"WHERE {w} AND {SALES}")
    sales_orders, with_items = one(f"SELECT COUNT(*), SUM(CASE WHEN f.item_count > 0 THEN 1 ELSE 0 END) FROM {orders} AND {SALES}")
    n_items, price, freight = one(f"SELECT COUNT(*), SUM(f.price), SUM(f.freight_value) FROM {items}")
    delivered, days, late = one(f"SELECT COUNT(*), SUM(f.delivery_days), SUM(CAST(f.is_late AS INT)) FROM {orders} AND f.is_delivered = 1")
    review = one(f"SELECT AVG(f.review_score_avg) FROM {orders} AND f.review_count > 0")[0]
    people, repeat = one(f"SELECT COUNT(*), SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END) FROM ("
                         f"SELECT c.customer_unique_id, COUNT(*) AS n FROM {orders} AND {SALES} GROUP BY c.customer_unique_id) AS p")
    payment = one(f"SELECT SUM(f.payment_value) FROM dw.fact_payments AS f JOIN dw.dim_customer AS c "
                  f"ON c.customer_key = f.customer_key WHERE {w} AND {SALES}")[0]
    return {
        "salesOrders": sales_orders, "productSales": float(price), "itemsSold": n_items,
        "averageOrderValue": float(price + freight) / with_items, "customers": people,
        "repeatCustomerRate": repeat / people, "deliveredOrders": delivered,
        "avgDeliveryDays": float(days) / delivered, "lateDeliveryRate": late / delivered,
        "avgReviewScore": float(review), "avgItemPrice": float(price) / n_items, "paymentValue": float(payment),
    }


@pytest.mark.parametrize("first, last, state", FILTERS)
def test_kpis_match_sql(conn, first, last, state):
    shown = page(first, last, state)["kpi"]
    for name, expected in sql_kpis(conn, first, last, state).items():
        assert shown[name] == pytest.approx(expected, abs=0.005), name


def test_full_window_matches_the_power_bi_cards(conn):
    k = page("2017-01", "2018-08", "ALL")["kpi"]
    assert (k["salesOrders"], k["customers"], k["itemsSold"], k["deliveredOrders"]) == (97910, 94707, 111752, 96203)
    assert round(k["productSales"], 2) == 13449529.68
    assert (round(k["averageOrderValue"], 2), round(k["avgDeliveryDays"], 1), round(k["avgReviewScore"], 2)) == (160.19, 12.5, 4.09)
    assert (round(k["lateDeliveryRate"] * 100, 1), round(k["repeatCustomerRate"] * 100, 1)) == (6.8, 3.0)
    assert (round(k["avgItemPrice"], 2), round(k["orderReviewScoreAllCategories"], 2)) == (120.35, 4.11)


def test_category_review_scores_match_the_power_bi_table(conn):
    categories = {c["name"]: c for c in page("2017-01", "2018-08", "ALL")["categories"]}
    assert {n: round(categories[n]["orderReviewScore"], 2) for n in ["health_beauty", "watches_gifts", "bed_bath_table"]} \
        == {"health_beauty": 4.18, "watches_gifts": 4.07, "bed_bath_table": 3.97}
    assert sum(c["productSales"] for c in categories.values()) == pytest.approx(13449529.68, abs=0.005)


@pytest.mark.parametrize("first, last, state", FILTERS)
def test_monthly_and_state_breakdowns_add_up(conn, first, last, state):
    p = page(first, last, state)
    assert sum(p["salesByMonth"]["values"]) == pytest.approx(p["kpi"]["productSales"], abs=0.005)
    assert sum(p["deliveryByMonth"]["delivered"]) == p["kpi"]["deliveredOrders"]
    assert sum(s["salesOrders"] for s in p["states"]) == p["kpi"]["salesOrders"]
