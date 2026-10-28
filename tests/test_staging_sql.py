"""Behaviour tests for the staging stored procedures, on tiny hand-made raw data.

They cover the paths the real dataset never triggers: rejected rows, changed
records, multiple versions of a key, and failure handling.
"""
import itertools

import pyodbc
import pytest

ORDER_A = "a" * 32
ORDER_B = "b" * 32
CUSTOMER = "c" * 32
_run_counter = itertools.count(1)


def new_run(conn) -> str:
    run_id = f"test_run_{next(_run_counter)}"
    conn.execute("EXEC ops.usp_run_start ?, N'pytest', NULL, N'local'", run_id)
    return run_id


def insert_raw_order(conn, batch_id, order_id=ORDER_A, status="delivered",
                     purchased="2018-01-01 10:00:00", approved=None,
                     estimated="2018-01-10 00:00:00", loaded_at="2026-01-01 00:00:00"):
    conn.execute(
        "INSERT raw.orders (order_id, customer_id, order_status, order_purchase_timestamp, order_approved_at, "
        "order_delivered_carrier_date, order_delivered_customer_date, order_estimated_delivery_date, "
        "batch_id, source_file, run_id, loaded_at_utc) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, N'test.csv', N'seed', ?)",
        order_id, CUSTOMER, status, purchased, approved, estimated, batch_id, loaded_at)


def last_step(conn, run_id):
    return conn.execute("SELECT TOP 1 status, rows_read, rows_written, rows_rejected, error_message "
                        "FROM ops.step_log WHERE run_id = ? ORDER BY step_id DESC", run_id).fetchone()


@pytest.fixture
def db(sql_test_db):
    """Empty raw/stg/ops tables before each test."""
    for table in ["raw.orders", "stg.orders", "raw.geolocation", "stg.geolocation", "ops.rejected_row"]:
        sql_test_db.execute(f"DELETE FROM {table}")
    return sql_test_db


def test_invalid_rows_are_rejected_and_logged(db):
    insert_raw_order(db, "b1")                                         # valid
    insert_raw_order(db, "b1", order_id="not-a-valid-id")              # bad key
    insert_raw_order(db, "b1", order_id=ORDER_B, purchased="31/01/2018 10:00")  # bad timestamp
    run_id = new_run(db)

    db.execute("EXEC stg.usp_load_orders @run_id = ?, @batch_id = N'b1'", run_id)

    assert db.execute("SELECT COUNT(*) FROM stg.orders").fetchval() == 1
    reasons = {r.record_key: r.reason for r in db.execute(
        "SELECT record_key, reason FROM ops.rejected_row WHERE run_id = ?", run_id)}
    assert reasons == {
        "not-a-valid-id": "order_id is not a 32-character hex id",
        ORDER_B: "order_purchase_timestamp is empty or not a timestamp",
    }
    assert tuple(last_step(db, run_id))[:4] == ("SUCCEEDED", 3, 1, 2)


def test_rerun_writes_nothing_and_nulls_do_not_count_as_changes(db):
    insert_raw_order(db, "b1", approved=None)  # NULL must compare equal to NULL on rerun
    run_id = new_run(db)
    db.execute("EXEC stg.usp_load_orders @run_id = ?, @batch_id = N'b1'", run_id)
    db.execute("EXEC stg.usp_load_orders @run_id = ?, @batch_id = N'b1'", run_id)

    assert tuple(last_step(db, run_id))[:4] == ("SUCCEEDED", 1, 0, 0)
    assert db.execute("SELECT COUNT(*) FROM stg.orders").fetchval() == 1


def test_changed_record_in_new_batch_updates_existing_row(db):
    insert_raw_order(db, "b1", status="shipped")
    db.execute("EXEC stg.usp_load_orders @run_id = ?, @batch_id = N'b1'", new_run(db))

    insert_raw_order(db, "b2", status="delivered", loaded_at="2026-01-02 00:00:00")
    run_id = new_run(db)
    db.execute("EXEC stg.usp_load_orders @run_id = ?, @batch_id = N'b2'", run_id)

    row = db.execute("SELECT order_status, batch_id, run_id, updated_at_utc FROM stg.orders").fetchone()
    assert (row.order_status, row.batch_id, row.run_id) == ("delivered", "b2", run_id)
    assert row.updated_at_utc is not None
    assert tuple(last_step(db, run_id))[:3] == ("SUCCEEDED", 1, 1)


def test_reprocessing_all_batches_keeps_latest_version(db):
    insert_raw_order(db, "b1", status="shipped", loaded_at="2026-01-01 00:00:00")
    insert_raw_order(db, "b2", status="delivered", loaded_at="2026-01-02 00:00:00")
    run_id = new_run(db)
    db.execute("EXEC stg.usp_load_orders @run_id = ?, @batch_id = NULL", run_id)

    assert db.execute("SELECT order_status FROM stg.orders").fetchval() == "delivered"
    assert tuple(last_step(db, run_id))[:3] == ("SUCCEEDED", 1, 1)  # 2 raw versions -> 1 key


def test_estimated_delivery_with_time_part_is_rejected(db):
    # Converting to DATE would silently drop the time, so the row is rejected instead.
    insert_raw_order(db, "b1", estimated="2018-01-10 15:30:00")
    run_id = new_run(db)
    db.execute("EXEC stg.usp_load_orders @run_id = ?, @batch_id = N'b1'", run_id)

    assert db.execute("SELECT reason FROM ops.rejected_row WHERE run_id = ?", run_id).fetchval() \
        == "order_estimated_delivery_date has a time part; DATE would lose it"


def test_failure_rolls_back_logs_error_and_rethrows(db):
    insert_raw_order(db, "b1", status="boom")
    insert_raw_order(db, "b1", order_id="bad-id")  # a reject that must ALSO be rolled back
    db.execute("ALTER TABLE stg.orders ADD CONSTRAINT ck_test_fail CHECK (order_status <> N'boom')")
    run_id = new_run(db)
    try:
        with pytest.raises(pyodbc.Error, match="ck_test_fail"):
            db.execute("EXEC stg.usp_load_orders @run_id = ?, @batch_id = N'b1'", run_id)
    finally:
        db.execute("ALTER TABLE stg.orders DROP CONSTRAINT ck_test_fail")

    status, *_, error = last_step(db, run_id)
    assert status == "FAILED" and "ck_test_fail" in error
    assert db.execute("SELECT COUNT(*) FROM stg.orders").fetchval() == 0
    assert db.execute("SELECT COUNT(*) FROM ops.rejected_row WHERE run_id = ?", run_id).fetchval() == 0


def test_geolocation_is_summarised_to_one_row_per_zip(db):
    rows = [
        ("01037", "-23.50", "-46.60", "SP"),
        ("01037", "-23.50", "-46.60", "SP"),   # exact duplicate
        ("01037", "-23.60", "-46.70", "SP"),
        ("01037", "-23.55", "-46.65", "RJ"),   # minority state
        ("01037", "40.00", "-3.70", "SP"),     # outside Brazil (Madrid): excluded from averages
        ("99999", "abc", "-46.60", "SP"),      # not a number: rejected
    ]
    for zip_code, lat, lng, state in rows:
        db.execute("INSERT raw.geolocation (geolocation_zip_code_prefix, geolocation_lat, geolocation_lng, "
                   "geolocation_city, geolocation_state, batch_id, source_file, run_id) "
                   "VALUES (?, ?, ?, N'x', ?, N'b1', N'test.csv', N'seed')", zip_code, lat, lng, state)
    run_id = new_run(db)
    db.execute("EXEC stg.usp_load_geolocation @run_id = ?, @batch_id = NULL", run_id)

    geo = db.execute("SELECT * FROM stg.geolocation").fetchall()
    assert len(geo) == 1
    g = geo[0]
    assert (g.zip_code_prefix, g.state, g.source_rows, g.excluded_points) == ("01037", "SP", 5, 1)
    assert float(g.latitude) == pytest.approx(-23.5375, abs=1e-6)   # mean of the 4 points inside Brazil
    assert tuple(last_step(db, run_id))[:4] == ("SUCCEEDED", 6, 1, 1)
