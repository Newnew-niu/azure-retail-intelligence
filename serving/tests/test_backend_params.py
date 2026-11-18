"""Bound parameters for the fixed seller queries, on both backends."""
import sys
import types

import pytest

from serving.core.backends import AzureSqlBackend, DuckDBBackend, to_tsql


def test_duckdb_binds_parameters_in_order(fixture_database):
    columns, rows = DuckDBBackend(fixture_database).execute(
        "SELECT year_month FROM mart.vw_sales_monthly WHERE year_month = ? OR year_month = ? ORDER BY 1",
        10, 5, params=["2018-02", "2017-12"])
    assert (columns, rows) == (["year_month"], [("2018-02",)])


def test_a_bound_value_is_data_not_sql(fixture_database):
    _, rows = DuckDBBackend(fixture_database).execute(
        "SELECT COUNT(*) FROM mart.vw_sales_monthly WHERE year_month = ?", 1, 5,
        params=["2018-01' OR '1'='1"])
    assert rows == [(0,)]


def test_azuresql_passes_parameters_to_the_driver(monkeypatch):
    calls = []

    class Cursor:
        description = [("a",)]

        def fetchmany(self, count):
            return [(1,)]

    class Connection:
        timeout = None

        def execute(self, sql, *params):
            calls.append((sql, params))
            return Cursor()

        def rollback(self):
            pass

        def close(self):
            pass

    fake_pyodbc = types.ModuleType("pyodbc")
    fake_pyodbc.Error = type("Error", (Exception,), {})
    fake_db = types.ModuleType("ingestion.db")
    fake_db.connect = lambda autocommit: Connection()
    fake_ingestion = types.ModuleType("ingestion")
    fake_ingestion.db = fake_db
    monkeypatch.setitem(sys.modules, "pyodbc", fake_pyodbc)
    monkeypatch.setitem(sys.modules, "ingestion", fake_ingestion)
    monkeypatch.setitem(sys.modules, "ingestion.db", fake_db)

    AzureSqlBackend().execute("SELECT a FROM t WHERE s = ? AND k BETWEEN ? AND ?", 1, 5, params=["SP", 1, 2])
    assert calls == [("SELECT a FROM t WHERE s = ? AND k BETWEEN ? AND ?", ("SP", 1, 2))]


def test_paging_placeholders_would_be_reordered_in_tsql():
    """Why sellers.py writes LIMIT and OFFSET as validated integers instead of placeholders."""
    tsql = to_tsql("SELECT a FROM t ORDER BY a LIMIT ? OFFSET ?")
    assert tsql.endswith("OFFSET ? ROWS FETCH FIRST ? ROWS ONLY")
