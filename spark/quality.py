"""Data quality gate for the lakehouse: the ERROR checks of ops.usp_run_dq_checks that apply
to these tables, plus key uniqueness (enforced by primary keys in SQL, not by Delta).

Results are appended to gold_dq_result with the columns of ops.dq_result (without its
IDENTITY id). Like the SQL procedure, the results are written first and the run is then
stopped with DataQualityError if any ERROR check found rows, so the failure is explained.
failed_rows = rows (or orders) violating the check; 0 = PASS.
"""
from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from spark.config import LakehouseConfig
from spark.gold import FACT_KEYS

DQ_COLUMNS = "run_id string, check_name string, check_category string, target_object string, severity string, " \
             "failed_rows bigint, status string, description string, checked_at_utc string"


class DataQualityError(RuntimeError):
    pass


def total(df: DataFrame, column: str):
    return df.agg(F.sum(column)).first()[0]  # a Python Decimal: compared exactly, never as float


def duplicate_keys(df: DataFrame, keys: list[str]) -> int:
    return df.count() - df.select(*keys).distinct().count()


def checks(spark: SparkSession, config: LakehouseConfig) -> list[tuple]:
    """(check_name, check_category, target_object, severity, failed_rows, description)"""
    def read(layer, name):
        return spark.read.format("delta").load(config.table(layer, name))

    s_orders, s_items, s_payments = read("silver", "orders"), read("silver", "order_items"), read("silver", "order_payments")
    g_orders, g_items, g_payments = read("gold", "fact_orders"), read("gold", "fact_order_items"), read("gold", "fact_payments")

    # Per-order sums from silver, computed separately for items and for payments
    silver_sums = (s_orders.select("order_id")
                   .join(s_items.groupBy("order_id").agg(F.sum("price").alias("s_items_price")), "order_id", "left")
                   .join(s_payments.groupBy("order_id").agg(F.sum("payment_value").alias("s_payment_value")), "order_id", "left"))
    per_order = g_orders.join(silver_sums, "order_id")

    results = [
        ("fact_orders_row_count", "reconciliation", "gold_fact_orders", abs(g_orders.count() - s_orders.count()),
         "fact_orders must have exactly one row per silver order"),
        ("fact_order_items_row_count", "reconciliation", "gold_fact_order_items", abs(g_items.count() - s_items.count()),
         "fact_order_items must have exactly one row per silver order item"),
        ("fact_payments_row_count", "reconciliation", "gold_fact_payments", abs(g_payments.count() - s_payments.count()),
         "fact_payments must have exactly one row per silver payment record"),
        ("fact_orders_items_price_matches_stg", "reconciliation", "gold_fact_orders",
         per_order.where(F.col("items_price") != F.coalesce("s_items_price", F.lit(0))).count(),
         "Orders whose items_price differs from the sum of their silver item prices (fan-out or lost rows)"),
        ("fact_orders_payment_value_matches_stg", "reconciliation", "gold_fact_orders",
         per_order.where(F.col("payment_value") != F.coalesce("s_payment_value", F.lit(0))).count(),
         "Orders whose payment_value differs from the sum of their silver payments"),
        ("fact_order_items_price_total", "reconciliation", "gold_fact_order_items",
         0 if total(g_items, "price") == total(s_items, "price") else 1,
         "Total item price in the fact equals silver (1 = totals differ)"),
        ("fact_payments_value_total", "reconciliation", "gold_fact_payments",
         0 if total(g_payments, "payment_value") == total(s_payments, "payment_value") else 1,
         "Total payment value in the fact equals silver (1 = totals differ)"),
        ("item_price_positive", "validity", "silver_order_items",
         s_items.where((F.col("price") <= 0) | (F.col("freight_value") < 0)).count(),
         "Item prices must be > 0 and freight >= 0"),
        ("payment_value_not_negative", "validity", "silver_order_payments",
         s_payments.where(F.col("payment_value") < 0).count(),
         "Payment values must be >= 0"),
    ]
    tables = {"fact_orders": g_orders, "fact_order_items": g_items, "fact_payments": g_payments}
    for fact, df in tables.items():
        results.append((f"{fact}_key_unique", "uniqueness", f"gold_{fact}", duplicate_keys(df, FACT_KEYS[fact]),
                        f"Rows sharing a key ({', '.join(FACT_KEYS[fact])}); a Delta table has no primary key"))
    return [(name, category, target, "ERROR", failed, description)
            for name, category, target, failed, description in results]


def run(spark: SparkSession, config: LakehouseConfig, run_id: str, run_ts: str) -> list[tuple]:
    """Run the checks, record them, and raise DataQualityError if any ERROR check failed."""
    found = checks(spark, config)
    rows = [(run_id, name, category, target, severity, failed,
             "PASS" if failed == 0 else ("FAIL" if severity == "ERROR" else "WARN"), description, run_ts)
            for name, category, target, severity, failed, description in found]
    (spark.createDataFrame(rows, DQ_COLUMNS)
        .withColumn("checked_at_utc", F.col("checked_at_utc").cast("timestamp"))
        .write.format("delta").mode("append").save(config.table("gold", "dq_result")))

    failed = [f"{name} ({count})" for _, name, _, _, severity, count, *_ in rows if severity == "ERROR" and count > 0]
    if failed:
        raise DataQualityError(f"Data quality: {len(failed)} ERROR check(s) failed: {', '.join(failed)}")
    return rows
