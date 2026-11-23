"""The data quality gate: results recorded like ops.dq_result, ERROR findings stop the run."""
import pytest
from delta.tables import DeltaTable
from pyspark.sql import functions as F

from spark import quality
from tests.spark.helpers import hex_id, item, order, payment, table, write_batch


def clean_batch(folder):
    return write_batch(folder, orders=[order(1), order(2)], items=[item(1, 1), item(1, 2), item(2, 1)],
                       payments=[payment(1, 1), payment(1, 2), payment(2, 1)])


def test_clean_load_passes_every_check(spark, lake, load, tmp_path):
    summary = load(clean_batch(tmp_path / "b1"), "b1")

    assert len(summary["dq"]) == 12
    assert {row[6] for row in summary["dq"]} == {"PASS"}
    recorded = table(spark, lake, "gold", "dq_result")
    assert recorded.columns == ["run_id", "check_name", "check_category", "target_object", "severity",
                                "failed_rows", "status", "description", "checked_at_utc"]
    assert recorded.where(F.col("run_id") == summary["run_id"]).count() == 12


def test_broken_gold_row_fails_the_step_and_is_recorded(spark, lake, load, tmp_path):
    load(clean_batch(tmp_path / "b1"), "b1")
    # Simulate a fan-out bug: one order's items_price doubled in gold.
    DeltaTable.forPath(spark, lake.table("gold", "fact_orders")).update(
        condition=F.col("order_id") == hex_id(1), set={"items_price": (F.col("items_price") * 2).cast("decimal(12,2)")})

    with pytest.raises(quality.DataQualityError, match=r"fact_orders_items_price_matches_stg \(1\)"):
        quality.run(spark, lake, "manual-check", "2030-01-01 00:00:00")

    failed = table(spark, lake, "gold", "dq_result").where("run_id = 'manual-check' AND status = 'FAIL'").collect()
    assert [(r["check_name"], r["failed_rows"]) for r in failed] == [("fact_orders_items_price_matches_stg", 1)]


def test_duplicate_gold_key_fails_the_uniqueness_check(spark, lake, load, tmp_path):
    load(clean_batch(tmp_path / "b1"), "b1")
    path = lake.table("gold", "fact_payments")
    spark.read.format("delta").load(path).limit(1).write.format("delta").mode("append").save(path)

    with pytest.raises(quality.DataQualityError, match="fact_payments_key_unique"):
        quality.run(spark, lake, "manual-check", "2030-01-01 00:00:00")
