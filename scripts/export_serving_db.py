"""Export the serving datasets from LocalDB into a DuckDB file for the demo backend.

    python scripts/export_serving_db.py

Writes data/serving.duckdb and data/serving_baseline.json, both git-ignored because the
data is licensed CC BY-NC-SA. Rows travel through temporary CSV files so that DECIMAL values
stay exact text. The script stops if row counts or money totals differ after the copy.
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

import duckdb
import sqlglot
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ingestion import db  # noqa: E402
from serving.golden_kpis import GOLDEN_KPIS  # noqa: E402

NOTES = PROJECT_ROOT / "serving" / "catalog_notes.yml"
OUT_DB = PROJECT_ROOT / "data" / "serving.duckdb"
OUT_BASELINE = PROJECT_ROOT / "data" / "serving_baseline.json"
NULL = r"\N"
LINEAGE_COLUMNS = {"run_id", "loaded_at_utc", "updated_at_utc", "inserted_at_utc"}

# Read only through get_pipeline_status(), never through run_query. error_message is left
# out on purpose: it is free text that could contain internal details.
OPS_COLUMNS = {
    "ops.pipeline_run": ["run_id", "pipeline_name", "batch_id", "trigger_source", "status",
                         "started_at_utc", "ended_at_utc"],
    "ops.dq_result": ["run_id", "check_name", "check_category", "target_object", "severity",
                      "failed_rows", "status", "description", "checked_at_utc"],
}
SIMPLE_TYPES = {"int": "INTEGER", "bigint": "BIGINT", "smallint": "SMALLINT", "date": "DATE",
                "tinyint": "TINYINT", "bit": "TINYINT",  # 0/1, so `is_late = 1` works in both engines
                "char": "VARCHAR", "nvarchar": "VARCHAR", "datetime2": "TIMESTAMP"}


def source_columns(source, table: str, keep: list[str] | None) -> list[tuple[str, str]]:
    """(column, DuckDB type) of one object, read from INFORMATION_SCHEMA."""
    schema, name = table.split(".")
    rows = source.execute(
        "SELECT column_name, data_type, numeric_precision, numeric_scale FROM information_schema.columns "
        "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position", schema, name).fetchall()
    if not rows:
        raise SystemExit(f"{table} not found in the source database")
    columns = []
    for column, data_type, precision, scale in rows:
        wanted = column in keep if keep else column not in LINEAGE_COLUMNS
        if wanted:
            duck_type = f"DECIMAL({precision},{scale})" if data_type == "decimal" else SIMPLE_TYPES[data_type]
            columns.append((column, duck_type))
    return columns


def csv_value(value) -> object:
    if value is None:
        return NULL
    return int(value) if isinstance(value, bool) else value


def copy_table(source, target, table: str, columns: list[tuple[str, str]], folder: Path) -> None:
    definitions = ", ".join(f'"{column}" {duck_type}' for column, duck_type in columns)
    target.execute(f"CREATE TABLE {table} ({definitions})")
    names = ", ".join(f'"{column}"' for column, _ in columns)
    path = folder / f"{table}.csv"
    cursor = source.execute(f"SELECT {names} FROM {table}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        while rows := cursor.fetchmany(50_000):
            writer.writerows([csv_value(value) for value in row] for row in rows)
    target.execute(f"COPY {table} FROM '{path.as_posix()}' (FORMAT csv, HEADER false, NULLSTR '{NULL}')")


def verify_copy(source, target, table: str, columns: list[tuple[str, str]]) -> int:
    """Row count and every DECIMAL column total must match exactly; returns the row count."""
    decimals = [column for column, duck_type in columns if duck_type.startswith("DECIMAL")]
    query = "SELECT " + ", ".join(["COUNT(*)"] + [f'SUM("{column}")' for column in decimals]) + f" FROM {table}"
    expected = tuple(source.execute(query).fetchone())
    actual = target.execute(query).fetchone()
    if expected != actual:
        raise SystemExit(f"{table}: source {expected} != export {actual}")
    return actual[0]


def compute_baseline(source) -> dict[str, str]:
    """The golden KPIs as computed by SQL Server, the reconciled warehouse."""
    baseline = {}
    for name, kpi in GOLDEN_KPIS.items():
        tsql = sqlglot.transpile(kpi["sql"], read="duckdb", write="tsql")[0]
        baseline[name] = str(source.execute(tsql).fetchval())
    return baseline


def main() -> int:
    datasets = yaml.safe_load(NOTES.read_text(encoding="utf-8"))["datasets"]
    tables = {name: None for name in datasets} | OPS_COLUMNS

    temporary = OUT_DB.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    source = db.connect(autocommit=True)
    target = duckdb.connect(str(temporary))
    try:
        for schema in sorted({name.split(".")[0] for name in tables}):
            target.execute(f"CREATE SCHEMA {schema}")
        with tempfile.TemporaryDirectory() as folder:
            for table, keep in tables.items():
                columns = source_columns(source, table, keep)
                copy_table(source, target, table, columns, Path(folder))
                print(f"  {table:36}{verify_copy(source, target, table, columns):>9,} rows, totals match")
        baseline = compute_baseline(source)
    finally:
        source.close()
        target.close()
    temporary.replace(OUT_DB)
    OUT_BASELINE.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_DB.relative_to(PROJECT_ROOT)} and {OUT_BASELINE.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
