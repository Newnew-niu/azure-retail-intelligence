"""Database backends. Both take DuckDB-dialect SQL and return (column names, rows).

DuckDB is the demo backend: it reads the exported file. Azure SQL is the production
configuration: it reuses ingestion/db.py, including Entra ID sign-in.
"""
from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Protocol

import duckdb
import sqlglot

from serving.core.errors import QueryFailed, QueryTimedOut


def first_line(exc: Exception) -> str:
    return str(exc).splitlines()[0][:300]


class Backend(Protocol):
    name: str

    def execute(self, sql: str, max_rows: int, timeout_seconds: float) -> tuple[list[str], list[tuple]]: ...


class DuckDBBackend:
    """Read-only, with external access off, so even SQL that passed the guard cannot touch files."""
    name = "duckdb"

    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> duckdb.DuckDBPyConnection:
        if not self.path.is_file():
            raise QueryFailed(f"{self.path.name} not found. Run scripts/export_serving_db.py first.")
        return duckdb.connect(str(self.path), read_only=True, config={
            "enable_external_access": "false",
            "lock_configuration": "true",  # a query cannot switch the setting back on
        })

    def execute(self, sql: str, max_rows: int, timeout_seconds: float) -> tuple[list[str], list[tuple]]:
        connection = self.connect()
        timed_out = threading.Event()

        def cancel() -> None:
            timed_out.set()
            connection.interrupt()

        timer = threading.Timer(timeout_seconds, cancel)
        timer.start()
        try:
            cursor = connection.execute(sql)
            columns = [column[0] for column in cursor.description]
            return columns, cursor.fetchmany(max_rows)
        except duckdb.Error as exc:
            if timed_out.is_set():
                raise QueryTimedOut(f"Query cancelled after {timeout_seconds} seconds") from exc
            raise QueryFailed(first_line(exc)) from exc
        finally:
            timer.cancel()
            connection.close()


def to_tsql(sql: str) -> str:
    return sqlglot.transpile(sql, read="duckdb", write="tsql")[0]


class AzureSqlBackend:
    """Azure SQL through ingestion/db.py. Imported lazily: pyodbc is not needed for the demo.

    SQL Server has no read-only connection flag, so three things keep this read-only: the
    guard, a reader identity with SELECT on the catalog objects only (serving/sql/), and a
    transaction that is always rolled back.
    """
    name = "azuresql"
    TIMEOUT_SQLSTATE = "HYT00"

    def execute(self, sql: str, max_rows: int, timeout_seconds: float) -> tuple[list[str], list[tuple]]:
        import pyodbc
        from ingestion import db

        connection = db.connect(autocommit=False)
        connection.timeout = max(1, math.ceil(timeout_seconds))  # pyodbc query timeout, whole seconds
        try:
            cursor = connection.execute(to_tsql(sql))
            columns = [column[0] for column in cursor.description]
            return columns, [tuple(row) for row in cursor.fetchmany(max_rows)]
        except pyodbc.Error as exc:
            if exc.args and exc.args[0] == self.TIMEOUT_SQLSTATE:
                raise QueryTimedOut(f"Query cancelled after {timeout_seconds} seconds") from exc
            raise QueryFailed(first_line(exc)) from exc
        finally:
            connection.rollback()
            connection.close()


def create_backend(name: str, duckdb_path: Path) -> Backend:
    if name == "duckdb":
        return DuckDBBackend(duckdb_path)
    if name == "azuresql":
        return AzureSqlBackend()
    raise ValueError(f"Unknown SERVING_BACKEND '{name}' (expected 'duckdb' or 'azuresql')")
