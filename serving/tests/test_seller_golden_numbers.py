"""Seller KPIs from the API must equal KPIs computed by independent SQL on the real data.

The SQL below is written separately from serving/core/sellers.py, in a different shape (distinct
orders instead of a seller-order CTE, MIN instead of MAX for the shipping deadline), so a shared
mistake is unlikely. It runs on the DuckDB export, which reconciles to SQL Server (see
test_golden_numbers.py). When LocalDB is available, the API on the azuresql backend must return
the same numbers too, which proves the translated T-SQL. Skipped when the real export is missing.
"""
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from serving.api.main import create_app
from serving.core.backends import DuckDBBackend
from serving.core.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPORT = PROJECT_ROOT / "data" / "serving.duckdb"
WINDOW = "i.purchase_date_key BETWEEN 20170101 AND 20180831"
SALES = "i.order_status NOT IN ('canceled', 'unavailable')"

pytestmark = pytest.mark.skipif(not EXPORT.is_file(), reason="real export not found; run scripts/export_serving_db.py")

# For one seller (bound as $seller): its distinct sales orders in the window, with the order facts.
SELLER_ORDERS = f"""
    SELECT DISTINCT i.order_id FROM dw.fact_order_items AS i
      JOIN dw.dim_seller AS s ON s.seller_key = i.seller_key
     WHERE s.seller_id = $seller AND {SALES} AND {WINDOW}"""
INDEPENDENT_KPIS = {
    "orders": f"SELECT COUNT(*) FROM ({SELLER_ORDERS}) AS x",
    "items_sold": f"""SELECT COUNT(*) FROM dw.fact_order_items AS i JOIN dw.dim_seller AS s USING (seller_key)
                      WHERE s.seller_id = $seller AND {SALES} AND {WINDOW}""",
    "product_sales": f"""SELECT SUM(i.price) FROM dw.fact_order_items AS i JOIN dw.dim_seller AS s USING (seller_key)
                         WHERE s.seller_id = $seller AND {SALES} AND {WINDOW}""",
    "average_order_value": f"""
        SELECT SUM(i.price + i.freight_value) / COUNT(DISTINCT i.order_id)
          FROM dw.fact_order_items AS i JOIN dw.dim_seller AS s USING (seller_key)
         WHERE s.seller_id = $seller AND {SALES} AND {WINDOW}""",
    "late_rate": f"""
        SELECT AVG(CASE WHEN o.delivered_carrier_date_key > d.deadline THEN 1.0 ELSE 0.0 END)
          FROM (SELECT i.order_id, MIN(i.shipping_limit_date_key) AS deadline
                  FROM dw.fact_order_items AS i JOIN dw.dim_seller AS s USING (seller_key)
                 WHERE s.seller_id = $seller AND {SALES} AND {WINDOW} GROUP BY i.order_id) AS d
          JOIN dw.fact_orders AS o ON o.order_id = d.order_id
         WHERE o.delivered_carrier_date_key IS NOT NULL""",
    "review_score": f"""SELECT AVG(o.review_score_avg) FROM dw.fact_orders AS o
                        WHERE o.order_id IN ({SELLER_ORDERS})""",
}
LATE_RATE_LAST_SIX_MONTHS = INDEPENDENT_KPIS["late_rate"].replace(
    WINDOW, "i.purchase_date_key BETWEEN 20180301 AND 20180831")


@pytest.fixture(scope="module")
def export():
    # DuckDB refuses a second connection to one file with different settings, so this uses the
    # backend's read-only settings. Only the SQL has to be independent.
    connection = DuckDBBackend(EXPORT).connect()
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    settings = Settings(duckdb_path=EXPORT, audit_path=tmp_path_factory.mktemp("golden") / "audit.jsonl")
    return TestClient(create_app(settings))


@pytest.fixture(scope="module")
def sample_sellers(export) -> list[str]:
    """Largest by sales, most orders, and three from the middle and the tail, chosen by plain SQL.
    No seller here has an unavailable order: all of them are from 2016, before the window, so the
    synthetic tests cover that status instead."""
    ranked = f"""SELECT s.seller_id, SUM(i.price) AS sales, COUNT(DISTINCT i.order_id) AS n
                   FROM dw.fact_order_items AS i JOIN dw.dim_seller AS s USING (seller_key)
                  WHERE {SALES} AND {WINDOW} GROUP BY s.seller_id"""
    top = export.execute(f"SELECT seller_id FROM ({ranked}) ORDER BY sales DESC LIMIT 1").fetchone()[0]
    busiest = export.execute(f"SELECT seller_id FROM ({ranked}) ORDER BY n DESC LIMIT 1").fetchone()[0]
    spread = [row[0] for row in export.execute(
        f"SELECT seller_id FROM ({ranked}) ORDER BY seller_id LIMIT 3 OFFSET 1000").fetchall()]
    tail = export.execute(f"SELECT seller_id FROM ({ranked}) ORDER BY n, seller_id LIMIT 1").fetchone()[0]
    return list(dict.fromkeys([top, busiest, *spread, tail]))


def independent(export, seller_id: str) -> dict:
    return {kpi: export.execute(sql, {"seller": seller_id}).fetchone()[0] for kpi, sql in INDEPENDENT_KPIS.items()}


def assert_equal(api: dict, expected: dict) -> None:
    for kpi, value in expected.items():
        if value is None:
            assert api[kpi] is None, kpi
        elif kpi in ("orders", "items_sold", "product_sales"):
            assert api[kpi] == float(value), kpi  # counts and money sums: exactly equal
        else:
            assert api[kpi] == pytest.approx(float(value), rel=1e-12), kpi


def test_the_seller_count_equals_independent_sql(client, export):
    expected = export.execute(f"""SELECT COUNT(DISTINCT i.seller_key) FROM dw.fact_order_items AS i
                                  WHERE {SALES} AND {WINDOW}""").fetchone()[0]
    assert client.get("/sellers", params={"page_size": 1}).json()["total"] == expected


def test_detail_kpis_equal_independent_sql(client, export, sample_sellers):
    for seller_id in sample_sellers:
        assert_equal(client.get(f"/sellers/{seller_id}").json()["summary"], independent(export, seller_id))


def test_list_kpis_equal_independent_sql(client, export, sample_sellers):
    for seller_id in sample_sellers:
        items = client.get("/sellers", params={"q": seller_id}).json()["items"]
        assert [item["seller_id"] for item in items] == [seller_id]
        assert_equal(items[0], independent(export, seller_id))


def test_the_late_dispatch_signal_equals_independent_sql(client, export, sample_sellers):
    for seller_id in sample_sellers:
        signal = next(s for s in client.get(f"/sellers/{seller_id}").json()["signals"] if s["key"] == "late_dispatch")
        if signal["status"] != "insufficient_data":
            expected = export.execute(LATE_RATE_LAST_SIX_MONTHS, {"seller": seller_id}).fetchone()[0]
            assert signal["value"] == pytest.approx(float(expected), rel=1e-12)


def test_monthly_rows_add_up_to_the_summary(client, sample_sellers):
    for seller_id in sample_sellers:
        body = client.get(f"/sellers/{seller_id}").json()
        assert sum(m["orders"] for m in body["monthly"]) == body["summary"]["orders"]
        assert sum(m["product_sales"] for m in body["monthly"]) == pytest.approx(body["summary"]["product_sales"])


@pytest.fixture(scope="module")
def localdb_client(tmp_path_factory) -> TestClient:
    if importlib.util.find_spec("pyodbc") is None:
        pytest.skip("pyodbc not installed")
    import pyodbc

    from ingestion import db
    if not db.is_local():
        pytest.skip("only runs against LocalDB")
    try:
        db.connect(attempts=1).close()
    except pyodbc.Error:
        pytest.skip("LocalDB or the project database is not available")
    settings = Settings(backend="azuresql", audit_path=tmp_path_factory.mktemp("golden_sql") / "audit.jsonl",
                        query_timeout_seconds=60)
    return TestClient(create_app(settings))


def test_sql_server_returns_the_same_seller_pages(client, localdb_client):
    for params in ({"page_size": 10}, {"state": "RJ", "sort": "late_rate", "order": "asc", "page": 2},
                   {"sort": "review_score", "order": "asc", "page_size": 5}):
        duck, sql_server = client.get("/sellers", params=params).json(), localdb_client.get("/sellers", params=params)
        assert sql_server.status_code == 200, sql_server.text
        assert sql_server.json()["total"] == duck["total"]
        for ours, theirs in zip(duck["items"], sql_server.json()["items"], strict=True):
            assert theirs["seller_id"] == ours["seller_id"]
            assert theirs == pytest.approx(ours)


def test_sql_server_returns_the_same_seller_detail(client, localdb_client, sample_sellers):
    for seller_id in sample_sellers[:2]:
        duck, sql_server = client.get(f"/sellers/{seller_id}").json(), localdb_client.get(f"/sellers/{seller_id}").json()
        assert sql_server["summary"] == pytest.approx(duck["summary"])
        assert [s["status"] for s in sql_server["signals"]] == [s["status"] for s in duck["signals"]]
