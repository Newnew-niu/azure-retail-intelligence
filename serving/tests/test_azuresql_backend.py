"""The azuresql backend: translation always, and a real SQL Server engine when LocalDB exists.

The integration tests use LocalDB through the same ingestion/db.py code path, against the
development database. They prove the T-SQL is valid. They do not prove Azure sign-in works.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

from serving.core.backends import AzureSqlBackend, create_backend, to_tsql
from serving.core.errors import QueryFailed, QueryRejected, QueryTimedOut
from serving.core.service import DataService
from serving.core.sql_guard import validate_query

ALLOWED = frozenset({"mart.vw_sales_monthly"})


def test_limit_becomes_top_in_tsql():
    safe_sql = validate_query("SELECT year_month FROM mart.vw_sales_monthly", ALLOWED, 500)
    assert to_tsql(safe_sql) == "SELECT TOP 501 year_month FROM mart.vw_sales_monthly"


def test_lowered_limit_applies_to_tsql_too():
    safe_sql = validate_query("SELECT * FROM mart.vw_sales_monthly LIMIT 999999", ALLOWED, 500)
    assert "TOP 501" in to_tsql(safe_sql)


def test_the_backend_is_chosen_by_config(tmp_path):
    assert create_backend("azuresql", tmp_path).name == "azuresql"
    assert create_backend("duckdb", tmp_path).name == "duckdb"
    with pytest.raises(ValueError, match="SERVING_BACKEND"):
        create_backend("oracle", tmp_path)


class FakeCursor:
    description = [("a",)]

    def fetchmany(self, count):
        return [(1,)]


class FakeConnection:
    """Records what the backend does, so no real database is touched."""

    def __init__(self, error=None):
        self.error, self.timeout, self.sql, self.events = error, None, None, []

    def execute(self, sql):
        self.sql = sql
        if self.error:
            raise self.error
        return FakeCursor()

    def rollback(self):
        self.events.append("rollback")

    def close(self):
        self.events.append("close")


@pytest.fixture
def fake_sql_server(monkeypatch):
    """Replaces pyodbc and ingestion.db, so these tests also run on CI without ODBC drivers."""
    fake_pyodbc = types.ModuleType("pyodbc")
    fake_pyodbc.Error = type("Error", (Exception,), {})
    fake_db = types.ModuleType("ingestion.db")
    fake_ingestion = types.ModuleType("ingestion")
    fake_ingestion.db = fake_db
    monkeypatch.setitem(sys.modules, "pyodbc", fake_pyodbc)
    monkeypatch.setitem(sys.modules, "ingestion", fake_ingestion)
    monkeypatch.setitem(sys.modules, "ingestion.db", fake_db)

    def install(error_args=None):
        error = fake_pyodbc.Error(*error_args) if error_args else None
        connection = FakeConnection(error)
        fake_db.connect = lambda autocommit: connection if autocommit is False else pytest.fail("needs a transaction")
        return connection
    return install


def test_every_query_runs_in_a_transaction_that_is_rolled_back(fake_sql_server):
    connection = fake_sql_server()
    columns, rows = AzureSqlBackend().execute("SELECT 1 AS a LIMIT 2", 2, 5)
    assert (columns, rows) == (["a"], [(1,)])
    assert connection.sql == "SELECT TOP 2 1 AS a"
    assert connection.events == ["rollback", "close"]


def test_a_failed_query_is_rolled_back_too(fake_sql_server):
    connection = fake_sql_server(("42S02", "Invalid object name"))
    with pytest.raises(QueryFailed):
        AzureSqlBackend().execute("SELECT 1", 1, 5)
    assert connection.events == ["rollback", "close"]


def test_the_query_timeout_is_set_in_whole_seconds(fake_sql_server):
    connection = fake_sql_server()
    AzureSqlBackend().execute("SELECT 1", 1, 2.5)
    assert connection.timeout == 3


def test_a_driver_timeout_becomes_query_timed_out(fake_sql_server):
    fake_sql_server(("HYT00", "Query timeout expired"))
    with pytest.raises(QueryTimedOut):
        AzureSqlBackend().execute("SELECT 1", 1, 5)


@pytest.fixture(scope="module")
def localdb_service(tmp_path_factory):
    if importlib.util.find_spec("pyodbc") is None:
        pytest.skip("pyodbc not installed")
    import pyodbc

    from ingestion import db
    from serving.core.config import Settings
    if not db.is_local():
        pytest.skip("only runs against LocalDB")
    try:
        connection = db.connect(attempts=1)
        populated = connection.execute("SELECT COUNT(*) FROM dw.fact_orders").fetchval() > 0
        connection.close()
    except pyodbc.Error:
        pytest.skip("LocalDB or the project database is not available")
    if not populated:
        pytest.skip("development database is empty")
    audit = Path(tmp_path_factory.mktemp("azuresql")) / "audit.jsonl"
    return DataService(Settings(backend="azuresql", audit_path=audit), backend=AzureSqlBackend())


def test_run_query_on_sql_server(localdb_service):
    result = localdb_service.run_query(
        "SELECT year_month, sales_orders FROM mart.vw_sales_monthly ORDER BY year_month DESC LIMIT 3",
        client="api")
    assert result["row_count"] == 3 and result["truncated"] is False


def test_row_limit_on_sql_server(localdb_service):
    result = localdb_service.run_query("SELECT order_id FROM dw.fact_orders", client="api", limit=5)
    assert (result["row_count"], result["truncated"]) == (5, True)


def test_guard_still_applies_on_sql_server(localdb_service):
    with pytest.raises(QueryRejected):
        localdb_service.run_query("SELECT * FROM ops.pipeline_run", client="api")


def test_engine_errors_are_reported_on_sql_server(localdb_service):
    with pytest.raises(QueryFailed):
        localdb_service.run_query("SELECT no_such_column FROM mart.vw_sales_monthly", client="api")


def test_describe_dataset_on_sql_server(localdb_service):
    assert localdb_service.describe_dataset("dw.dim_date")["row_count"] > 0


def test_pipeline_status_on_sql_server(localdb_service):
    status = localdb_service.get_pipeline_status()
    assert status["latest_run"]["status"] in {"SUCCEEDED", "FAILED", "RUNNING"}
    assert status["data_quality"]["checks"]
