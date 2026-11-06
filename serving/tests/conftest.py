"""Fixtures for the serving tests: a tiny synthetic DuckDB file, built from the real catalog.

No real data, no network and no LocalDB, so these tests run on Linux CI. Every catalog table
is created from its catalog definition, which also proves the catalog describes real columns.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import duckdb
import pytest

from serving.core.catalog import Catalog
from serving.core.config import Settings
from serving.core.service import DataService

CATALOG_PATH = Path(__file__).resolve().parents[1] / "catalog.yml"
CALENDAR_DAYS = 2_000  # large enough for a four-way cross join to outlast the timeout test


def create_table(connection, name: str, columns: list[dict]) -> None:
    definitions = ", ".join(f'"{c["name"]}" {c["type"]}' for c in columns)
    connection.execute(f"CREATE TABLE {name} ({definitions})")


def build_fixture_database(path: Path) -> None:
    catalog = Catalog.load(CATALOG_PATH)
    connection = duckdb.connect(str(path))
    for schema in ("mart", "dw", "ops"):
        connection.execute(f"CREATE SCHEMA {schema}")
    for name, dataset in catalog.datasets.items():
        create_table(connection, name, dataset["columns"])

    connection.execute("""
        INSERT INTO mart.vw_sales_monthly (year_month, month_start, sales_orders, customers, items_sold,
                                           product_sales, freight, average_order_value)
        VALUES ('2018-01', '2018-01-01', 2, 2, 3, 30.50, 5.00, 17.75),
               ('2018-02', '2018-02-01', 1, 1, 1, 10.25, 1.00, 11.25)""")
    connection.execute("""
        INSERT INTO mart.vw_payment_mix (payment_type, payment_records, orders, payment_value, avg_installments)
        VALUES ('credit_card', 2, 2, 40.00, 1.50), ('boleto', 1, 1, 7.75, 1.00)""")
    connection.execute("INSERT INTO dw.dim_date (date_key) SELECT i FROM range(?) AS t(i)", [CALENDAR_DAYS])
    connection.execute("""
        INSERT INTO dw.fact_payments (order_id, payment_sequential, payment_type, payment_value)
        SELECT 'order_' || i, 1, 'credit_card', 1.00 FROM range(50) AS t(i)""")

    connection.execute("""
        CREATE TABLE ops.pipeline_run (run_id VARCHAR, pipeline_name VARCHAR, batch_id VARCHAR,
            trigger_source VARCHAR, status VARCHAR, started_at_utc TIMESTAMP, ended_at_utc TIMESTAMP)""")
    connection.execute("""
        INSERT INTO ops.pipeline_run VALUES
            ('run_old', 'pl_olist_master', 'full_load', 'local', 'FAILED', '2026-01-01 10:00:00', NULL),
            ('run_new', 'pl_olist_master', 'full_load', 'local', 'SUCCEEDED', '2026-01-02 10:00:00', '2026-01-02 10:01:00')""")
    connection.execute("""
        CREATE TABLE ops.dq_result (run_id VARCHAR, check_name VARCHAR, check_category VARCHAR,
            target_object VARCHAR, severity VARCHAR, failed_rows BIGINT, status VARCHAR,
            description VARCHAR, checked_at_utc TIMESTAMP)""")
    connection.execute("""
        INSERT INTO ops.dq_result VALUES
            ('run_new', 'row_count', 'reconciliation', 'dw.fact_orders', 'ERROR', 0, 'PASS', 'rows match', '2026-01-02 10:01:00'),
            ('run_new', 'no_items', 'completeness', 'dw.fact_orders', 'WARN', 3, 'WARN', 'orders without items', '2026-01-02 10:01:00'),
            ('run_old', 'stale_check', 'validity', 'dw.fact_orders', 'ERROR', 9, 'FAIL', 'from the older run', '2026-01-01 10:01:00')""")
    connection.close()


@pytest.fixture(scope="session")
def fixture_database(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("serving") / "fixture.duckdb"
    build_fixture_database(path)
    return path


@pytest.fixture
def settings(fixture_database, tmp_path) -> Settings:
    return Settings(backend="duckdb", duckdb_path=fixture_database, catalog_path=CATALOG_PATH,
                    audit_path=tmp_path / "audit.jsonl", api_key="test-key", query_timeout_seconds=5.0)


@pytest.fixture
def service(settings) -> DataService:
    return DataService(settings)


@pytest.fixture
def fast_timeout_service(settings) -> DataService:
    return DataService(replace(settings, query_timeout_seconds=0.2))
