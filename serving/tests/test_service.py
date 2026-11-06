"""The four shared functions, row limits, timeouts and the audit log."""
import json
from dataclasses import replace

import pytest

from serving.core.errors import DatasetNotFound, QueryFailed, QueryRejected, QueryTimedOut
from serving.core.service import DataService

SLOW_QUERY = ("SELECT SUM(a.date_key * b.date_key * c.date_key * d.date_key) "
              "FROM dw.dim_date a, dw.dim_date b, dw.dim_date c, dw.dim_date d")


def audit_lines(service) -> list[dict]:
    return [json.loads(line) for line in service.audit.path.read_text(encoding="utf-8").splitlines()]


def test_list_datasets_returns_all_catalog_entries(service):
    datasets = service.list_datasets()
    assert {d["name"] for d in datasets} == set(service.catalog.datasets)
    assert all(d["description"] and d["grain"] and d["owner"] for d in datasets)


def test_ops_is_not_a_dataset(service):
    assert not [d for d in service.list_datasets() if d["layer"] == "ops"]


def test_describe_dataset_gives_definitions_grain_source_and_row_count(service):
    dataset = service.describe_dataset("mart.vw_sales_monthly")
    assert dataset["row_count"] == 2
    assert dataset["grain"] == "one row per month"
    assert dataset["source"] == "sql/mart/01_views.sql"
    assert all(column["definition"] for column in dataset["columns"])


def test_describe_dataset_ignores_case(service):
    assert service.describe_dataset("MART.VW_SALES_MONTHLY")["name"] == "mart.vw_sales_monthly"


@pytest.mark.parametrize("name", ["mart.nope", "ops.dq_result", "mart.vw_payment_mix; DROP TABLE x"])
def test_describe_rejects_names_outside_the_catalog(service, name):
    with pytest.raises(DatasetNotFound):
        service.describe_dataset(name)


def test_run_query_returns_rows_as_json_safe_values(service):
    result = service.run_query("SELECT year_month, month_start, product_sales FROM mart.vw_sales_monthly "
                               "ORDER BY year_month", client="api")
    assert result["columns"] == ["year_month", "month_start", "product_sales"]
    assert result["rows"][0] == {"year_month": "2018-01", "month_start": "2018-01-01", "product_sales": 30.5}
    assert (result["row_count"], result["truncated"]) == (2, False)
    json.dumps(result)


def test_default_row_limit_truncates_and_says_so(settings):
    service = DataService(replace(settings, default_row_limit=10))
    result = service.run_query("SELECT * FROM dw.fact_payments", client="api")
    assert (result["row_count"], result["row_limit"], result["truncated"]) == (10, 10, True)


def test_a_result_of_exactly_the_limit_is_not_called_truncated(service):
    result = service.run_query("SELECT * FROM dw.fact_payments", client="api", limit=50)
    assert (result["row_count"], result["truncated"]) == (50, False)


def test_a_caller_cannot_exceed_the_maximum_row_limit(settings):
    service = DataService(replace(settings, max_row_limit=20))
    result = service.run_query("SELECT * FROM dw.fact_payments LIMIT 1000", client="api", limit=1000)
    assert (result["row_count"], result["row_limit"], result["truncated"]) == (20, 20, True)


def test_the_default_limits_are_500_and_5000(service):
    assert (service.settings.default_row_limit, service.settings.max_row_limit) == (500, 5_000)


def test_a_slow_query_is_cancelled_by_the_timeout(fast_timeout_service):
    with pytest.raises(QueryTimedOut):
        fast_timeout_service.run_query(SLOW_QUERY, client="api")


def test_pipeline_status_uses_the_latest_run_only(service):
    status = service.get_pipeline_status()
    assert status["latest_run"]["run_id"] == "run_new"
    assert status["latest_run"]["status"] == "SUCCEEDED"
    assert status["data_quality"]["summary"] == {"PASS": 1, "WARN": 1}
    assert {check["check_name"] for check in status["data_quality"]["checks"]} == {"row_count", "no_items"}


def test_pipeline_status_never_returns_error_text(service):
    assert "error_message" not in service.get_pipeline_status()["latest_run"]


def test_audit_records_a_successful_query(service):
    sql = "SELECT * FROM mart.vw_payment_mix"
    service.run_query(sql, client="mcp")
    entry = audit_lines(service)[-1]
    assert (entry["client"], entry["sql"], entry["status"], entry["row_count"]) == ("mcp", sql, "ok", 2)
    assert entry["duration_ms"] >= 0 and entry["timestamp"] and entry["reason"] is None


def test_audit_records_a_rejected_query_with_the_reason(service):
    with pytest.raises(QueryRejected):
        service.run_query("DROP TABLE dw.fact_orders", client="api")
    entry = audit_lines(service)[-1]
    assert (entry["client"], entry["status"], entry["row_count"]) == ("api", "rejected", None)
    assert "Only SELECT" in entry["reason"]


def test_audit_records_a_database_error(service):
    with pytest.raises(QueryFailed):
        service.run_query("SELECT no_such_column FROM mart.vw_payment_mix", client="api")
    entry = audit_lines(service)[-1]
    assert entry["status"] == "error" and "no_such_column" in entry["reason"]


def test_audit_records_a_timeout(fast_timeout_service):
    with pytest.raises(QueryTimedOut):
        fast_timeout_service.run_query(SLOW_QUERY, client="api")
    entry = audit_lines(fast_timeout_service)[-1]
    assert entry["status"] == "error" and "cancelled" in entry["reason"]


def test_audit_appends_one_json_line_per_query(service):
    for _ in range(3):
        service.run_query("SELECT 1", client="api")
    assert len(audit_lines(service)) == 3
