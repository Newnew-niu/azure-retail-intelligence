"""Layer 2: the DuckDB connection itself, with the guard bypassed on purpose.

If the guard ever misses something, these restrictions must still hold.
"""
from pathlib import Path

import pytest

from serving.core.backends import DuckDBBackend
from serving.core.errors import QueryFailed


@pytest.fixture
def backend(fixture_database) -> DuckDBBackend:
    return DuckDBBackend(fixture_database)


@pytest.mark.parametrize("sql", [
    "DROP TABLE mart.vw_payment_mix",
    "DELETE FROM mart.vw_payment_mix",
    "UPDATE mart.vw_payment_mix SET orders = 0",
    "INSERT INTO mart.vw_payment_mix (payment_type) VALUES ('x')",
    "CREATE TABLE mart.stolen (a INT)",
])
def test_the_connection_cannot_write(backend, sql):
    with pytest.raises(QueryFailed):
        backend.execute(sql, 10, 5)


@pytest.mark.parametrize("function", ["read_csv", "read_text", "read_blob", "read_parquet", "read_json"])
def test_the_connection_cannot_read_files(backend, tmp_path, function):
    secret = tmp_path / "secret.txt"
    secret.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(QueryFailed):
        backend.execute(f"SELECT * FROM {function}('{secret.as_posix()}')", 10, 5)


def test_the_connection_cannot_scan_a_file_by_name(backend, tmp_path):
    secret = tmp_path / "secret.csv"
    secret.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(QueryFailed):
        backend.execute(f"SELECT * FROM '{secret.as_posix()}'", 10, 5)


def test_the_connection_cannot_write_files(backend, tmp_path):
    target = tmp_path / "stolen.csv"
    with pytest.raises(QueryFailed):
        backend.execute(f"COPY mart.vw_payment_mix TO '{target.as_posix()}'", 10, 5)
    assert not target.exists()


def test_the_connection_cannot_attach_another_database(backend, tmp_path):
    with pytest.raises(QueryFailed):
        backend.execute(f"ATTACH '{(tmp_path / 'other.duckdb').as_posix()}' AS other", 10, 5)


@pytest.mark.parametrize("sql", ["SET enable_external_access = true",
                                 "SET lock_configuration = false"])
def test_the_restrictions_cannot_be_switched_off_from_sql(backend, sql):
    with pytest.raises(QueryFailed):
        backend.execute(sql, 10, 5)


def test_rows_are_capped_at_the_driver_too(backend):
    _, rows = backend.execute("SELECT * FROM dw.fact_payments", 7, 5)
    assert len(rows) == 7


def test_a_missing_export_gives_a_helpful_error(tmp_path):
    with pytest.raises(QueryFailed, match="export_serving_db"):
        DuckDBBackend(Path(tmp_path / "missing.duckdb")).execute("SELECT 1", 1, 5)
