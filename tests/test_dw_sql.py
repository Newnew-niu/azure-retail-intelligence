"""Behaviour tests for the DW procedures and the data quality checks, on tiny staging data.

Covered: no fan-out when an order has several items AND several payments, incremental
loads that touch only changed orders, late-arriving dimension rows, the watermark staying
put when a load fails, and the DQ step blocking on an ERROR check.
"""
import itertools

import pyodbc
import pytest

ORDER_A, ORDER_B = "a" * 32, "b" * 32
CUSTOMER_A, CUSTOMER_B = "c" * 32, "d" * 32
PERSON = "e" * 32
PRODUCT, SELLER = "1" * 32, "2" * 32
DW_PROCEDURES = ["dw.usp_load_dim_date", "dw.usp_load_dim_customer", "dw.usp_load_dim_product",
                 "dw.usp_load_dim_seller", "dw.usp_load_fact_orders", "dw.usp_load_fact_order_items",
                 "dw.usp_load_fact_payments"]
_runs = itertools.count(1)


@pytest.fixture
def db(sql_test_db):
    """Empty stg/dw/ops tables before each test (dimension Unknown members are kept)."""
    for table in ["stg.orders", "stg.order_items", "stg.order_payments", "stg.order_reviews", "stg.customers",
                  "stg.products", "stg.sellers", "stg.product_category_translation", "stg.geolocation",
                  "dw.fact_orders", "dw.fact_order_items", "dw.fact_payments", "ops.watermark", "ops.dq_result"]:
        sql_test_db.execute(f"DELETE FROM {table}")
    for table in ["dw.dim_customer", "dw.dim_product", "dw.dim_seller"]:
        sql_test_db.execute(f"DELETE FROM {table} WHERE {table.split('_', 1)[1]}_key <> -1")
    return sql_test_db


def new_run(conn) -> str:
    run_id = f"dw_test_run_{next(_runs)}"
    conn.execute("EXEC ops.usp_run_start ?, N'pytest', NULL, N'local'", run_id)
    return run_id


def run_dw(conn) -> str:
    run_id = new_run(conn)
    for proc in DW_PROCEDURES:
        conn.execute(f"EXEC {proc} @run_id = ?", run_id)
    return run_id


def step(conn, run_id, name):
    return conn.execute("SELECT status, rows_read, rows_written, error_message FROM ops.step_log "
                        "WHERE run_id = ? AND step_name = ? ORDER BY step_id DESC", run_id, name).fetchone()


def add_customer(conn, customer_id=CUSTOMER_A):
    conn.execute("INSERT stg.customers (customer_id, customer_unique_id, zip_code_prefix, city, state, batch_id, run_id) "
                 "VALUES (?, ?, '01037', N'sao paulo', 'SP', 'b1', 'seed')", customer_id, PERSON)


def add_order(conn, order_id=ORDER_A, customer_id=CUSTOMER_A, status="delivered",
              delivered="2018-01-05 12:00:00", estimated="2018-01-10"):
    conn.execute("INSERT stg.orders (order_id, customer_id, order_status, purchased_at, approved_at, delivered_carrier_at, "
                 "delivered_customer_at, estimated_delivery_date, batch_id, run_id) "
                 "VALUES (?, ?, ?, '2018-01-01 12:00:00', '2018-01-01 13:00:00', '2018-01-02 10:00:00', ?, ?, 'b1', 'seed')",
                 order_id, customer_id, status, delivered, estimated)


def add_item(conn, order_id, item_no, price, freight="5.00", product_id=PRODUCT):
    conn.execute("INSERT stg.order_items (order_id, order_item_id, product_id, seller_id, shipping_limit_at, price, "
                 "freight_value, batch_id, run_id) VALUES (?, ?, ?, ?, '2018-01-03 00:00:00', ?, ?, 'b1', 'seed')",
                 order_id, item_no, product_id, SELLER, price, freight)


def add_payment(conn, order_id, seq, value, payment_type="credit_card"):
    conn.execute("INSERT stg.order_payments (order_id, payment_sequential, payment_type, payment_installments, "
                 "payment_value, batch_id, run_id) VALUES (?, ?, ?, 1, ?, 'b1', 'seed')", order_id, seq, payment_type, value)


def add_product(conn, product_id=PRODUCT):
    conn.execute("INSERT stg.products (product_id, category_name_pt, batch_id, run_id) "
                 "VALUES (?, N'pc_gamer', 'b1', 'seed')", product_id)


def add_seller(conn):
    conn.execute("INSERT stg.sellers (seller_id, zip_code_prefix, city, state, batch_id, run_id) "
                 "VALUES (?, '01037', N'sao paulo', 'SP', 'b1', 'seed')", SELLER)


def seed_order_with_two_items_and_two_payments(conn):
    add_customer(conn); add_product(conn); add_seller(conn); add_order(conn)
    add_item(conn, ORDER_A, 1, "100.00")
    add_item(conn, ORDER_A, 2, "50.00")
    add_payment(conn, ORDER_A, 1, "110.00")
    add_payment(conn, ORDER_A, 2, "50.00")


def test_order_aggregates_do_not_fan_out(db):
    seed_order_with_two_items_and_two_payments(db)
    run_dw(db)

    f = db.execute("SELECT item_count, items_price, items_freight, payment_count, payment_value, "
                   "delivery_status, is_late, delivery_days FROM dw.fact_orders").fetchone()
    # A naive items x payments join would give 4 rows: price 300.00, payments 320.00
    assert (f.item_count, float(f.items_price), float(f.items_freight)) == (2, 150.0, 10.0)
    assert (f.payment_count, float(f.payment_value)) == (2, 160.0)
    assert (f.delivery_status, f.is_late, float(f.delivery_days)) == ("On time", 0, 4.0)
    assert tuple(db.execute("SELECT COUNT(*), SUM(price) FROM dw.fact_order_items").fetchone()) == (2, 150)
    assert tuple(db.execute("SELECT COUNT(*), SUM(payment_value) FROM dw.fact_payments").fetchone()) == (2, 160)


def test_untranslated_category_falls_back_to_portuguese(db):
    seed_order_with_two_items_and_two_payments(db)
    run_dw(db)
    p = db.execute("SELECT category_name_en, is_category_translated FROM dw.dim_product WHERE product_key <> -1").fetchone()
    assert (p.category_name_en, p.is_category_translated) == ("pc_gamer", 0)


def test_incremental_load_rewrites_only_changed_orders(db):
    seed_order_with_two_items_and_two_payments(db)
    add_customer(db, CUSTOMER_B)
    add_order(db, ORDER_B, CUSTOMER_B, status="shipped", delivered=None)
    run_dw(db)

    db.execute("UPDATE stg.orders SET order_status = N'delivered', delivered_customer_at = '2018-01-15 09:00:00', "
               "updated_at_utc = SYSUTCDATETIME() WHERE order_id = ?", ORDER_B)
    run_id = run_dw(db)

    assert tuple(step(db, run_id, "dw.usp_load_fact_orders"))[:3] == ("SUCCEEDED", 1, 1)  # only ORDER_B
    late = db.execute("SELECT delivery_status, is_late, delivery_vs_estimate_days FROM dw.fact_orders "
                      "WHERE order_id = ?", ORDER_B).fetchone()
    assert tuple(late) == ("Late", 1, 5)
    untouched = db.execute("SELECT run_id FROM dw.fact_orders WHERE order_id = ?", ORDER_A).fetchval()
    assert untouched != run_id

    rerun = run_dw(db)
    assert tuple(step(db, rerun, "dw.usp_load_fact_orders"))[:3] == ("SUCCEEDED", 0, 0)


def test_late_arriving_product_is_resolved_on_the_next_run(db):
    add_customer(db); add_seller(db); add_order(db)
    add_item(db, ORDER_A, 1, "100.00")          # product not staged yet
    run_dw(db)
    assert db.execute("SELECT product_key FROM dw.fact_order_items").fetchval() == -1

    add_product(db)
    run_dw(db)
    key = db.execute("SELECT product_key FROM dw.fact_order_items").fetchval()
    assert key == db.execute("SELECT product_key FROM dw.dim_product WHERE product_id = ?", PRODUCT).fetchval()


def test_failed_fact_load_keeps_watermark_and_is_retried(db):
    seed_order_with_two_items_and_two_payments(db)
    run_dw(db)
    mark_before = db.execute("SELECT last_change_utc FROM ops.watermark WHERE target_object = N'dw.fact_orders'").fetchval()

    db.execute("UPDATE stg.orders SET order_status = N'boom', updated_at_utc = SYSUTCDATETIME()")
    db.execute("ALTER TABLE dw.fact_orders ADD CONSTRAINT ck_test_fail CHECK (order_status <> N'boom')")
    run_id = new_run(db)
    try:
        with pytest.raises(pyodbc.Error, match="ck_test_fail"):
            db.execute("EXEC dw.usp_load_fact_orders @run_id = ?", run_id)
    finally:
        db.execute("ALTER TABLE dw.fact_orders DROP CONSTRAINT ck_test_fail")

    assert step(db, run_id, "dw.usp_load_fact_orders").status == "FAILED"
    assert db.execute("SELECT last_change_utc FROM ops.watermark WHERE target_object = N'dw.fact_orders'").fetchval() \
        == mark_before
    assert db.execute("SELECT order_status FROM dw.fact_orders").fetchval() == "delivered"  # rolled back

    run_dw(db)  # retry picks up the same change
    assert db.execute("SELECT order_status FROM dw.fact_orders").fetchval() == "boom"


def test_dq_error_check_fails_the_step_and_records_results(db):
    seed_order_with_two_items_and_two_payments(db)
    run_dw(db)
    db.execute("UPDATE dw.fact_orders SET items_price = items_price * 2")  # simulate double counting
    run_id = new_run(db)

    with pytest.raises(pyodbc.Error, match="fact_orders_items_price_matches_stg"):
        db.execute("EXEC ops.usp_run_dq_checks @run_id = ?", run_id)

    assert step(db, run_id, "ops.usp_run_dq_checks").status == "FAILED"
    status = db.execute("SELECT status FROM ops.dq_result WHERE run_id = ? AND check_name = ?",
                        run_id, "fact_orders_items_price_matches_stg").fetchval()
    assert status == "FAIL"


def test_dq_passes_on_consistent_data_and_reports_warnings(db):
    seed_order_with_two_items_and_two_payments(db)   # payments 160 = price 150 + freight 10
    add_customer(db, CUSTOMER_B)
    add_order(db, ORDER_B, CUSTOMER_B, status="canceled", delivered=None)  # no items, no payment
    run_dw(db)
    run_id = new_run(db)
    db.execute("EXEC ops.usp_run_dq_checks @run_id = ?", run_id)

    results = {r.check_name: r.status for r in db.execute(
        "SELECT check_name, status FROM ops.dq_result WHERE run_id = ?", run_id)}
    assert all(s != "FAIL" for s in results.values())
    assert results["orders_without_items"] == "WARN"
    assert results["payment_differs_from_price_plus_freight"] == "PASS"
