"""Acceptance test for incremental loading (LocalDB): batches in order == one full load.

    python scripts/verify_incremental.py

1. Recreates a separate local database (retail_intelligence_sim) from the SQL scripts.
2. Runs the local pipeline once per SIMULATED batch in data/batches/ (oldest first).
3. Compares every staging table, dimension, fact and mart view with the development
   database, which holds the one-off full load: EXCEPT in both directions on business
   columns (surrogate keys, run ids and load timestamps naturally differ and are excluded).
Exit code 0 only if every comparison finds 0 differing rows.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from ingestion import db  # noqa: E402

BATCH_DIR = PROJECT_ROOT / "data" / "batches"
SIM_DATABASE = "retail_intelligence_sim"

# {db} is replaced by the database name; each query returns the business content of one object.
COMPARISONS = {
    "stg.customers": "SELECT customer_id, customer_unique_id, zip_code_prefix, city, state FROM {db}.stg.customers",
    "stg.sellers": "SELECT seller_id, zip_code_prefix, city, state FROM {db}.stg.sellers",
    "stg.product_category_translation": "SELECT category_name_pt, category_name_en FROM {db}.stg.product_category_translation",
    "stg.products": "SELECT product_id, category_name_pt, name_length, description_length, photos_qty, weight_g, "
                    "length_cm, height_cm, width_cm FROM {db}.stg.products",
    "stg.orders": "SELECT order_id, customer_id, order_status, purchased_at, approved_at, delivered_carrier_at, "
                  "delivered_customer_at, estimated_delivery_date FROM {db}.stg.orders",
    "stg.order_items": "SELECT order_id, order_item_id, product_id, seller_id, shipping_limit_at, price, freight_value "
                       "FROM {db}.stg.order_items",
    "stg.order_payments": "SELECT order_id, payment_sequential, payment_type, payment_installments, payment_value "
                          "FROM {db}.stg.order_payments",
    "stg.order_reviews": "SELECT review_id, order_id, review_score, comment_title, comment_message, created_at, answered_at "
                         "FROM {db}.stg.order_reviews",
    "stg.geolocation": "SELECT zip_code_prefix, latitude, longitude, state, source_rows, excluded_points FROM {db}.stg.geolocation",
    "dw.dim_date": "SELECT * FROM {db}.dw.dim_date",
    "dw.dim_customer": "SELECT customer_id, customer_unique_id, zip_code_prefix, city, state, latitude, longitude "
                       "FROM {db}.dw.dim_customer",
    "dw.dim_product": "SELECT product_id, category_name_pt, category_name_en, is_category_translated, weight_g "
                      "FROM {db}.dw.dim_product",
    "dw.dim_seller": "SELECT seller_id, zip_code_prefix, city, state, latitude, longitude FROM {db}.dw.dim_seller",
    "dw.fact_orders": "SELECT c.customer_id, f.order_id, f.purchase_date_key, f.approved_date_key, f.delivered_carrier_date_key, "
                      "f.delivered_customer_date_key, f.estimated_delivery_date_key, f.order_status, f.purchased_at, "
                      "f.delivered_customer_at, f.estimated_delivery_date, f.item_count, f.items_price, f.items_freight, "
                      "f.payment_count, f.payment_value, f.review_count, f.review_score_avg, f.delivery_days, "
                      "f.estimated_delivery_days, f.delivery_vs_estimate_days, f.is_delivered, f.is_late, f.delivery_status "
                      "FROM {db}.dw.fact_orders AS f JOIN {db}.dw.dim_customer AS c ON c.customer_key = f.customer_key",
    "dw.fact_order_items": "SELECT f.order_id, f.order_item_id, p.product_id, s.seller_id, c.customer_id, f.purchase_date_key, "
                           "f.shipping_limit_date_key, f.order_status, f.price, f.freight_value "
                           "FROM {db}.dw.fact_order_items AS f "
                           "JOIN {db}.dw.dim_product AS p ON p.product_key = f.product_key "
                           "JOIN {db}.dw.dim_seller AS s ON s.seller_key = f.seller_key "
                           "JOIN {db}.dw.dim_customer AS c ON c.customer_key = f.customer_key",
    "dw.fact_payments": "SELECT f.order_id, f.payment_sequential, c.customer_id, f.purchase_date_key, f.order_status, "
                        "f.payment_type, f.payment_installments, f.payment_value FROM {db}.dw.fact_payments AS f "
                        "JOIN {db}.dw.dim_customer AS c ON c.customer_key = f.customer_key",
    "mart.vw_sales_monthly": "SELECT * FROM {db}.mart.vw_sales_monthly",
    "mart.vw_delivery_by_state": "SELECT * FROM {db}.mart.vw_delivery_by_state",
    "mart.vw_review_by_delivery_status": "SELECT * FROM {db}.mart.vw_review_by_delivery_status",
    "mart.vw_category_sales": "SELECT * FROM {db}.mart.vw_category_sales",
    "mart.vw_seller_performance": "SELECT * FROM {db}.mart.vw_seller_performance",
    "mart.vw_payment_mix": "SELECT * FROM {db}.mart.vw_payment_mix",
}


def compare(conn, full_db: str, sim_db: str) -> dict[str, tuple[int, int, int]]:
    """{object: (rows in full load, rows only in full, rows only in incremental)}"""
    results = {}
    for name, query in COMPARISONS.items():
        full, sim = query.format(db=full_db), query.format(db=sim_db)
        rows = conn.execute(f"SELECT COUNT(*) FROM ({full}) AS q").fetchval()
        only_full = conn.execute(f"SELECT COUNT(*) FROM ({full} EXCEPT {sim}) AS q").fetchval()
        only_sim = conn.execute(f"SELECT COUNT(*) FROM ({sim} EXCEPT {full}) AS q").fetchval()
        results[name] = (rows, only_full, only_sim)
    return results


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    if not db.is_local():
        print("This check runs on LocalDB only (it compares two databases on one server).", file=sys.stderr)
        return 2
    batches = sorted(p for p in BATCH_DIR.glob("sim_*") if p.is_dir())
    if not batches:
        print("No batches - run scripts/make_incremental_batches.py first.", file=sys.stderr)
        return 2
    full_db = db.database_name()

    os.environ["SQL_DATABASE"] = SIM_DATABASE
    import deploy_sql
    import run_local_pipeline
    deploy_sql.ensure_local_database(reset=True)
    deploy_sql.deploy()

    for batch in batches:
        started = time.perf_counter()
        run_id = run_local_pipeline.run(batch.name, batch, "dw")
        with db.connect() as conn:
            written = conn.execute("SELECT SUM(rows_written) FROM ops.step_log WHERE run_id = ? AND step_name = "
                                   "N'dw.usp_load_fact_orders'", run_id).fetchval()
            dq = dict(tuple(r) for r in conn.execute(
                "SELECT status, COUNT(*) FROM ops.dq_result WHERE run_id = ? GROUP BY status", run_id))
        print(f"loaded {batch.name:<22} {time.perf_counter() - started:5.1f} s  "
              f"fact_orders rows rebuilt={written:,}  DQ={dq}")

    with db.connect() as conn:
        results = compare(conn, full_db, SIM_DATABASE)
    print(f"\n{'object':<36}{'rows':>10}{'only full':>11}{'only incr.':>11}")
    for name, (rows, only_full, only_sim) in results.items():
        print(f"{name:<36}{rows:>10,}{only_full:>11,}{only_sim:>11,}")
    differences = sum(a + b for _, a, b in results.values())
    print(f"\n{'PASS' if differences == 0 else 'FAIL'}: {differences} differing rows "
          f"(incremental batches in {SIM_DATABASE} vs full load in {full_db})")
    return 0 if differences == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
