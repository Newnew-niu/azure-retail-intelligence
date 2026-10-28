"""Source-to-target reconciliation on the real dataset in the development database.

Run after `python scripts/run_local_pipeline.py`. Checks that nothing was lost or
duplicated between the CSV files, the raw layer and the staging layer.
Skipped when the data files or a successful local run are not available.
"""
import pandas as pd
import pytest

from ingestion import db, validate_files

BATCH_ID = "full_load"
CONTRACT = validate_files.load_contract(validate_files.DEFAULT_CONTRACT)
# Natural key of each staging table, as raw column names.
STAGING_KEYS = {
    "customers": ["customer_id"],
    "sellers": ["seller_id"],
    "product_category_translation": ["product_category_name"],
    "products": ["product_id"],
    "orders": ["order_id"],
    "order_items": ["order_id", "order_item_id"],
    "order_payments": ["order_id", "payment_sequential"],
    "order_reviews": ["review_id", "order_id"],
}


@pytest.fixture(scope="module")
def conn():
    if not (validate_files.DEFAULT_DATA_DIR / CONTRACT["entities"]["orders"]["file"]).is_file():
        pytest.skip("source data not downloaded")
    try:
        connection = db.connect()
    except Exception:
        pytest.skip("development database not available")
    succeeded = connection.execute("SELECT COUNT(*) FROM ops.pipeline_run WHERE batch_id = ? AND status = N'SUCCEEDED'",
                                   BATCH_ID).fetchval()
    if not succeeded:
        pytest.skip("no successful local pipeline run yet")
    yield connection
    connection.close()


def csv_rows(entity: str) -> int:
    path = validate_files.DEFAULT_DATA_DIR / CONTRACT["entities"][entity]["file"]
    first_column = CONTRACT["entities"][entity]["columns"][0]["name"]
    return len(pd.read_csv(path, usecols=[first_column], dtype=str, encoding="utf-8-sig"))


@pytest.mark.parametrize("entity", list(CONTRACT["entities"]))
def test_raw_row_count_matches_source_file(conn, entity):
    raw = conn.execute(f"SELECT COUNT(*) FROM raw.{entity} WHERE batch_id = ?", BATCH_ID).fetchval()
    assert raw == csv_rows(entity)


@pytest.mark.parametrize("entity", list(STAGING_KEYS))
def test_staging_holds_every_distinct_key_minus_rejects(conn, entity):
    keys = ", ".join(STAGING_KEYS[entity])
    distinct_keys = conn.execute(f"SELECT COUNT(*) FROM (SELECT DISTINCT {keys} FROM raw.{entity}) AS k").fetchval()
    staged = conn.execute(f"SELECT COUNT(*) FROM stg.{entity}").fetchval()
    # Rejects of the latest successful run for this table
    rejected = conn.execute(
        "SELECT COUNT(*) FROM ops.rejected_row WHERE source_table = ? AND run_id = "
        "(SELECT TOP 1 run_id FROM ops.pipeline_run WHERE status = N'SUCCEEDED' ORDER BY started_at_utc DESC)",
        f"raw.{entity}").fetchval()
    assert staged == distinct_keys - rejected


def test_geolocation_has_exactly_one_row_per_raw_zip_prefix(conn):
    # Geolocation is summarised, not merged by key; the real data has no rejects for it.
    missing = conn.execute("SELECT COUNT(*) FROM (SELECT geolocation_zip_code_prefix FROM raw.geolocation "
                           "EXCEPT SELECT zip_code_prefix FROM stg.geolocation) AS m").fetchval()
    extra = conn.execute("SELECT COUNT(*) FROM (SELECT zip_code_prefix FROM stg.geolocation "
                         "EXCEPT SELECT geolocation_zip_code_prefix FROM raw.geolocation) AS e").fetchval()
    assert (missing, extra) == (0, 0)


@pytest.mark.parametrize("table, column, stg_table", [
    ("order_items", "price", "order_items"),
    ("order_items", "freight_value", "order_items"),
    ("order_payments", "payment_value", "order_payments"),
])
def test_monetary_totals_reconcile_to_the_cent(conn, table, column, stg_table):
    source_total = pd.read_csv(validate_files.DEFAULT_DATA_DIR / CONTRACT["entities"][table]["file"],
                               usecols=[column], dtype=str)[column].map(lambda v: round(float(v) * 100)).sum()
    staged_total = conn.execute(f"SELECT CAST(SUM({column}) * 100 AS BIGINT) FROM stg.{stg_table}").fetchval()
    assert staged_total == source_total
