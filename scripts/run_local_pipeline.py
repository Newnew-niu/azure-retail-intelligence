"""Run the pipeline locally against LocalDB - the local equivalent of the ADF master pipeline.

Steps (each logged to ops.pipeline_run / ops.step_log):
  1. validate   - ingestion.validate_files (stops the run on any ERROR)
  2. raw        - ingestion.load_data, one step per source file
  3. stg        - staging stored procedures (they log their own steps)
  4. dw         - dimension and fact procedures, then the data quality checks
                  (an ERROR-severity check failure fails the run)

Usage:
    python scripts/run_local_pipeline.py [--batch-id full_load] [--data-dir data/raw] [--until raw|stg|dw]
"""
from __future__ import annotations

import argparse
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ingestion import db, load_data, validate_files  # noqa: E402

log = logging.getLogger("run_local_pipeline")

PIPELINE_NAME = "pl_olist_master"
# Staging procedures in dependency-free order; each takes @run_id and @batch_id.
STAGING_PROCEDURES = [
    "stg.usp_load_customers",
    "stg.usp_load_sellers",
    "stg.usp_load_product_category_translation",
    "stg.usp_load_products",
    "stg.usp_load_orders",
    "stg.usp_load_order_items",
    "stg.usp_load_order_payments",
    "stg.usp_load_order_reviews",
    "stg.usp_load_geolocation",
]
# Dimensions before facts (facts look up surrogate keys); quality checks last.
DW_PROCEDURES = [
    "dw.usp_load_dim_date",
    "dw.usp_load_dim_customer",
    "dw.usp_load_dim_product",
    "dw.usp_load_dim_seller",
    "dw.usp_load_fact_orders",
    "dw.usp_load_fact_order_items",
    "dw.usp_load_fact_payments",
    "ops.usp_run_dq_checks",
]
# The ADF child pipeline runs exactly this list (checked by tests/test_adf_definitions.py).
TRANSFORM_PROCEDURES = STAGING_PROCEDURES + DW_PROCEDURES


# Logging and stored procedures use an AUTOCOMMIT connection, exactly like ADF's Stored
# Procedure activity: log rows survive a failed load, and each procedure owns its transaction.
def step_start(ops_conn, run_id: str, name: str, target: str | None) -> int:
    return ops_conn.execute("SET NOCOUNT ON; DECLARE @id INT; "
                            "EXEC ops.usp_step_start @run_id = ?, @step_name = ?, @target_object = ?, @step_id = @id OUTPUT; "
                            "SELECT @id;", run_id, name, target).fetchval()


def step_end(ops_conn, step_id: int, status: str, rows_read=None, rows_written=None, error=None) -> None:
    ops_conn.execute("EXEC ops.usp_step_end @step_id = ?, @status = ?, @rows_read = ?, @rows_written = ?, "
                     "@rows_rejected = 0, @error_message = ?", step_id, status, rows_read, rows_written, error)


def run(batch_id: str, data_dir: Path, until: str) -> str:
    report = validate_files.run(data_dir, validate_files.DEFAULT_CONTRACT, validate_files.DEFAULT_REPORT_DIR)
    if report["status"] != "PASSED":
        raise SystemExit(f"Validation failed - nothing loaded. See {report['report_path']}")
    log.info("Validation passed (%s)", report["report_path"])

    contract = validate_files.load_contract(validate_files.DEFAULT_CONTRACT)
    run_id = f"local_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:8]}"
    load_conn = db.connect()
    ops_conn = db.connect(autocommit=True)
    ops_conn.execute("EXEC ops.usp_run_start @run_id = ?, @pipeline_name = ?, @batch_id = ?, @trigger_source = N'local'",
                     run_id, PIPELINE_NAME, batch_id)
    log.info("Run %s started (batch '%s')", run_id, batch_id)

    try:
        log.info("RAW load:")
        for entity, spec in contract["entities"].items():
            step_id = step_start(ops_conn, run_id, f"copy {spec['file']}", f"raw.{entity}")
            try:
                rows = load_data.load_entity(load_conn, entity, spec, data_dir, batch_id, run_id)
            except Exception as exc:
                step_end(ops_conn, step_id, "FAILED", error=str(exc)[:4000])
                raise
            step_end(ops_conn, step_id, "SUCCEEDED", rows_read=rows, rows_written=rows)

        procedures = {"raw": [], "stg": STAGING_PROCEDURES, "dw": TRANSFORM_PROCEDURES}[until]
        if procedures:
            log.info("TRANSFORM:")
        for proc in procedures:
            ops_conn.execute(f"EXEC {proc} @run_id = ?, @batch_id = ?", run_id, batch_id)
            log.info("  %s done", proc)

        ops_conn.execute("EXEC ops.usp_run_end @run_id = ?, @status = N'SUCCEEDED'", run_id)
    except Exception as exc:
        ops_conn.execute("EXEC ops.usp_run_end @run_id = ?, @status = N'FAILED', @error_message = ?",
                         run_id, str(exc)[:4000])
        raise
    finally:
        load_conn.close()
        ops_conn.close()
    log.info("Run %s SUCCEEDED", run_id)
    return run_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local pipeline (validate -> raw -> stg -> dw)")
    parser.add_argument("--batch-id", default="full_load", help="batch to (re)load; reruns replace it")
    parser.add_argument("--data-dir", type=Path, default=validate_files.DEFAULT_DATA_DIR)
    parser.add_argument("--until", choices=["raw", "stg", "dw"], default="dw", help="last layer to process")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    run(args.batch_id, args.data_dir, args.until)
    return 0


if __name__ == "__main__":
    sys.exit(main())
