"""The four operations of the serving layer, shared by the REST API and the MCP server.

All rules live here, so both front ends behave identically. They only translate
requests and errors.
"""
from __future__ import annotations

import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from serving.core.audit import AuditLog
from serving.core.backends import Backend, create_backend
from serving.core.catalog import Catalog
from serving.core.config import Settings
from serving.core.errors import QueryFailed, QueryRejected, QueryTimedOut
from serving.core.sql_guard import validate_query


# Fixed queries, so they are not checked by the guard. They are not parameterised because
# the azuresql backend must be able to translate them; error_message is deliberately absent.
LATEST_RUN_SQL = """
SELECT run_id, pipeline_name, batch_id, trigger_source, status, started_at_utc, ended_at_utc
  FROM ops.pipeline_run ORDER BY started_at_utc DESC LIMIT 1"""
LATEST_DQ_SQL = """
SELECT check_name, check_category, target_object, severity, failed_rows, status, description
  FROM ops.dq_result
 WHERE run_id = (SELECT run_id FROM ops.pipeline_run ORDER BY started_at_utc DESC LIMIT 1)
 ORDER BY severity, failed_rows DESC, check_name"""
MAX_DQ_CHECKS = 200


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def as_dicts(columns: list[str], rows: list[tuple]) -> list[dict]:
    return [dict(zip(columns, map(json_safe, row))) for row in rows]


class DataService:
    def __init__(self, settings: Settings, backend: Backend | None = None) -> None:
        self.settings = settings
        self.catalog = Catalog.load(settings.catalog_path)
        self.backend = backend or create_backend(settings.backend, settings.duckdb_path)
        self.audit = AuditLog(settings.audit_path)

    def list_datasets(self) -> list[dict]:
        return [{"name": name, "description": d["description"], "grain": d["grain"],
                 "layer": d["layer"], "owner": d["owner"]}
                for name, d in self.catalog.datasets.items()]

    def describe_dataset(self, name: str) -> dict:
        dataset = self.catalog.dataset(name)  # raises DatasetNotFound, so `name` below is from the catalog
        _, rows = self.backend.execute(f"SELECT COUNT(*) FROM {dataset['name']}", 1,
                                       self.settings.query_timeout_seconds)
        return {**dataset, "row_count": rows[0][0]}

    def run_query(self, sql: str, client: str, limit: int | None = None) -> dict:
        """Validate, run and audit one query. Every outcome is written to the audit log."""
        row_limit = min(limit or self.settings.default_row_limit, self.settings.max_row_limit)
        started = time.perf_counter()

        def elapsed_ms() -> float:
            return (time.perf_counter() - started) * 1000

        try:
            safe_sql = validate_query(sql, self.catalog.allowed_tables, row_limit)
            columns, rows = self.backend.execute(safe_sql, row_limit + 1,
                                                 self.settings.query_timeout_seconds)
        except QueryRejected as exc:
            self.audit.record(client, sql, "rejected", elapsed_ms(), reason=str(exc))
            raise
        except (QueryFailed, QueryTimedOut) as exc:
            self.audit.record(client, sql, "error", elapsed_ms(), reason=str(exc))
            raise

        result_rows = rows[:row_limit]
        duration_ms = elapsed_ms()
        self.audit.record(client, sql, "ok", duration_ms, row_count=len(result_rows))
        return {"columns": columns,
                "rows": as_dicts(columns, result_rows),
                "row_count": len(result_rows),
                "row_limit": row_limit,
                "truncated": len(rows) > row_limit,
                "duration_ms": round(duration_ms, 1)}

    def get_pipeline_status(self) -> dict:
        timeout = self.settings.query_timeout_seconds
        columns, rows = self.backend.execute(LATEST_RUN_SQL, 1, timeout)
        runs = as_dicts(columns, rows)
        if not runs:
            return {"latest_run": None, "data_quality": {"summary": {}, "checks": []}}

        columns, rows = self.backend.execute(LATEST_DQ_SQL, MAX_DQ_CHECKS, timeout)
        checks = as_dicts(columns, rows)
        summary: dict[str, int] = {}
        for check in checks:
            summary[check["status"]] = summary.get(check["status"], 0) + 1
        return {"latest_run": runs[0], "data_quality": {"summary": summary, "checks": checks}}
