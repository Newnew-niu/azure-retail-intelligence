"""Every endpoint through a real HTTP stack (in process), on the synthetic database."""
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from serving.api.main import create_app
from serving.core.sql_guard import MAX_SQL_LENGTH

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture
def client(settings) -> TestClient:
    return TestClient(create_app(settings))


def audit_lines(settings) -> list[dict]:
    return [json.loads(line) for line in settings.audit_path.read_text(encoding="utf-8").splitlines()]


def test_health_needs_no_key_and_names_the_backend(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "backend": "duckdb"}


def test_openapi_docs_are_generated(client):
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/health", "/datasets", "/datasets/{name}", "/query", "/runs/latest"} <= set(paths)


@pytest.mark.parametrize("method, path, body", [
    ("get", "/datasets", None),
    ("get", "/datasets/mart.vw_sales_monthly", None),
    ("post", "/query", {"sql": "SELECT 1"}),
    ("get", "/runs/latest", None),
])
class TestAuthentication:
    def test_a_missing_key_gets_401(self, client, method, path, body):
        assert client.request(method, path, json=body).status_code == 401

    def test_a_wrong_key_gets_401(self, client, method, path, body):
        response = client.request(method, path, json=body, headers={"X-API-Key": "wrong"})
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "ApiKey"

    def test_the_right_key_is_accepted(self, client, method, path, body):
        assert client.request(method, path, json=body, headers=HEADERS).status_code == 200

    def test_an_unset_server_key_refuses_everyone(self, settings, method, path, body):
        client = TestClient(create_app(replace(settings, api_key="")))
        assert client.request(method, path, json=body, headers={"X-API-Key": ""}).status_code == 401


def test_a_bad_key_is_refused_before_the_query_runs_or_is_audited(client, settings):
    client.post("/query", json={"sql": "SELECT 1"})
    assert not settings.audit_path.exists()


def test_a_non_ascii_key_gets_401_not_a_crash(client):
    assert client.get("/datasets", headers={"X-API-Key": "clé".encode("latin-1")}).status_code == 401


def test_list_datasets(client):
    names = {d["name"] for d in client.get("/datasets", headers=HEADERS).json()}
    assert "mart.vw_sales_monthly" in names and "dw.fact_orders" in names


def test_describe_dataset(client):
    body = client.get("/datasets/mart.vw_sales_monthly", headers=HEADERS).json()
    assert body["row_count"] == 2 and body["grain"] == "one row per month"
    assert body["columns"][0]["definition"]


def test_unknown_dataset_gets_404(client):
    assert client.get("/datasets/mart.nope", headers=HEADERS).status_code == 404


def test_ops_is_not_a_dataset_over_http(client):
    assert client.get("/datasets/ops.dq_result", headers=HEADERS).status_code == 404


def test_query_returns_rows(client):
    response = client.post("/query", headers=HEADERS, json={"sql": "SELECT year_month, freight FROM "
                           "mart.vw_sales_monthly ORDER BY year_month"})
    assert response.status_code == 200
    body = response.json()
    assert body["rows"][1] == {"year_month": "2018-02", "freight": 1.0}
    assert (body["row_count"], body["row_limit"], body["truncated"]) == (2, 500, False)


def test_query_honours_the_requested_limit(client):
    body = client.post("/query", headers=HEADERS, json={"sql": "SELECT * FROM dw.fact_payments", "limit": 5}).json()
    assert (body["row_count"], body["truncated"]) == (5, True)


@pytest.mark.parametrize("sql", ["DROP TABLE dw.fact_orders", "SELECT 1; SELECT 2",
                                 "SELECT * FROM read_csv('.env')", "SELECT * FROM ops.dq_result",
                                 "SELECT 1 -- hidden"])
def test_rejected_sql_gets_400_with_a_reason(client, sql):
    response = client.post("/query", headers=HEADERS, json={"sql": sql})
    assert response.status_code == 400
    assert response.json()["detail"]


def test_a_sql_error_gets_400(client):
    response = client.post("/query", headers=HEADERS, json={"sql": "SELECT nope FROM mart.vw_payment_mix"})
    assert response.status_code == 400 and "nope" in response.json()["detail"]


@pytest.mark.parametrize("body", [
    {},
    {"sql": ""},
    {"sql": 123},
    {"sql": "SELECT 1", "limit": 0},
    {"sql": "SELECT 1", "limit": 5001},
    {"sql": "SELECT 1", "limit": "many"},
    {"sql": "SELECT 1", "unexpected": True},
])
def test_an_invalid_body_gets_422(client, body):
    assert client.post("/query", headers=HEADERS, json=body).status_code == 422


def test_oversized_sql_gets_400_and_is_audited(client, settings):
    sql = "SELECT " + "1," * MAX_SQL_LENGTH + "1"
    assert client.post("/query", headers=HEADERS, json={"sql": sql}).status_code == 400
    assert audit_lines(settings)[-1]["status"] == "rejected"


def test_a_slow_query_gets_504(settings):
    client = TestClient(create_app(replace(settings, query_timeout_seconds=0.2)))
    sql = ("SELECT SUM(a.date_key * b.date_key * c.date_key * d.date_key) "
           "FROM dw.dim_date a, dw.dim_date b, dw.dim_date c, dw.dim_date d")
    assert client.post("/query", headers=HEADERS, json={"sql": sql}).status_code == 504


def test_a_missing_database_gets_503_and_is_audited(settings, tmp_path):
    client = TestClient(create_app(replace(settings, duckdb_path=tmp_path / "missing.duckdb")))
    response = client.post("/query", headers=HEADERS, json={"sql": "SELECT 1"})
    assert response.status_code == 503 and "export_serving_db" in response.json()["detail"]
    assert audit_lines(settings)[-1]["status"] == "error"


def test_latest_run(client):
    body = client.get("/runs/latest", headers=HEADERS).json()
    assert body["latest_run"]["run_id"] == "run_new"
    assert body["data_quality"]["summary"] == {"PASS": 1, "WARN": 1}


def test_api_queries_are_audited_as_api(client, settings):
    client.post("/query", headers=HEADERS, json={"sql": "SELECT 1"})
    client.post("/query", headers=HEADERS, json={"sql": "DROP TABLE x"})
    entries = audit_lines(settings)
    assert [(e["client"], e["status"]) for e in entries] == [("api", "ok"), ("api", "rejected")]
