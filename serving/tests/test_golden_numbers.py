"""The API must return the same KPIs as the reconciled warehouse, and as the README.

Runs only when the real export exists, so it is skipped on CI. Expected values come from
data/serving_baseline.json, which SQL Server computed during the export. None is typed here.
"""
import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from serving.api.main import create_app
from serving.core.config import Settings
from serving.golden_kpis import GOLDEN_KPIS, SALES, WINDOW

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPORT = PROJECT_ROOT / "data" / "serving.duckdb"
BASELINE = PROJECT_ROOT / "data" / "serving_baseline.json"
README = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
HEADERS = {"X-API-Key": "golden"}
EXACT_KPIS = {"sales_orders", "product_sales"}  # the rest are ratios, rounded differently by each engine

pytestmark = pytest.mark.skipif(not (EXPORT.is_file() and BASELINE.is_file()),
                                reason="real export not found; run scripts/export_serving_db.py")


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    settings = Settings(duckdb_path=EXPORT, api_key="golden",
                        audit_path=tmp_path_factory.mktemp("golden") / "audit.jsonl")
    return TestClient(create_app(settings))


@pytest.fixture(scope="module")
def baseline() -> dict[str, str]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def api_value(client, sql: str) -> float:
    response = client.post("/query", headers=HEADERS, json={"sql": sql})
    assert response.status_code == 200, response.text
    return next(iter(response.json()["rows"][0].values()))


@pytest.mark.parametrize("name", GOLDEN_KPIS)
def test_the_api_equals_sql_server(client, baseline, name):
    value = api_value(client, GOLDEN_KPIS[name]["sql"])
    if name in EXACT_KPIS:
        assert Decimal(str(value)) == Decimal(baseline[name])
    else:
        assert value == pytest.approx(float(baseline[name]), abs=1e-5)


@pytest.mark.parametrize("name", GOLDEN_KPIS)
def test_the_readme_shows_the_same_number(baseline, name):
    assert GOLDEN_KPIS[name]["readme"](float(baseline[name])) in README


def test_the_mart_view_agrees_inside_the_reporting_window(client, baseline):
    sql = ("SELECT SUM(sales_orders) FROM mart.vw_sales_monthly "
           "WHERE year_month BETWEEN '2017-01' AND '2018-08'")
    assert api_value(client, sql) == int(baseline["sales_orders"])


def test_the_full_mart_total_is_larger_which_is_why_the_catalog_warns(client, baseline):
    assert api_value(client, "SELECT SUM(sales_orders) FROM mart.vw_sales_monthly") > int(baseline["sales_orders"])


def test_fact_orders_row_count_matches_the_sales_kpi_source(client, baseline):
    sql = f"SELECT COUNT(*) FROM dw.fact_orders WHERE {SALES} AND {WINDOW}"
    assert api_value(client, sql) == int(baseline["sales_orders"])


def test_the_latest_run_has_no_failed_quality_check(client):
    body = client.get("/runs/latest", headers=HEADERS).json()
    assert body["latest_run"]["status"] == "SUCCEEDED"
    assert body["data_quality"]["summary"].get("FAIL", 0) == 0
    assert sum(body["data_quality"]["summary"].values()) > 0
