"""Gold: the three fact tables at their natural grain, rebuilt per changed order.

The PySpark port of sql/dw/usp_load_fact_{orders,order_items,payments}.sql.

    gold_fact_orders       one row per order                 key: order_id
    gold_fact_order_items  one row per order item            key: order_id, order_item_id
    gold_fact_payments     one row per payment record        key: order_id, payment_sequential

No fan-out (decision #5): items and payments are each aggregated to one row per order on
their own, and only then joined 1:1 to the order. They are never joined to each other.

Incremental loading (decision #8):
  1. old mark = gold_watermark; new mark = latest _inserted_at/_updated_at in silver.
  2. affected orders = orders with any silver change in (old mark, new mark].
  3. Rebuild every row of those orders from current silver.
  4. New version of each fact = untouched rows + rebuilt rows. One Delta MERGE applies the
     difference in a single commit: changed rows updated, new rows inserted, rows that no
     longer exist deleted. Unchanged rows are not rewritten.
  5. Save the new mark. Delta has no transaction across tables, so this is a separate
     commit; if the run stops before it, the next run rebuilds the same orders again and
     gets the same result, because a rebuild from silver is idempotent.

Differences from the SQL warehouse, on purpose:
  * Natural keys (customer_id, product_id, seller_id) instead of surrogate keys. IDENTITY
    values depend on the engine and load order, so no second engine can reproduce them;
    the parity check maps the SQL keys back to natural keys instead.
  * Because there are no dimensions, there are no Unknown (-1) members to retry.
  * fact_orders has no review columns: reviews are outside this module's scope.
"""
from __future__ import annotations

from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from spark.config import LakehouseConfig
from spark.silver import last_operation_metrics

FACT_KEYS = {
    "fact_orders": ["order_id"],
    "fact_order_items": ["order_id", "order_item_id"],
    "fact_payments": ["order_id", "payment_sequential"],
}
TOTAL = "decimal(12,2)"  # per-order sums, as DECIMAL(12,2) in dw.fact_orders
EPOCH = "1900-01-01 00:00:00"


def date_key(column: str) -> F.Column:
    """yyyymmdd as an integer, like CONVERT(INT, CONVERT(CHAR(8), x, 112))."""
    return F.date_format(F.col(column), "yyyyMMdd").cast("int")


def build_fact_order_items(items: DataFrame, orders: DataFrame) -> DataFrame:
    order = orders.select("order_id", "customer_id", "purchased_at", "order_status")
    return items.join(order, "order_id", "left").select(
        "order_id", "order_item_id", "product_id", "seller_id", "customer_id",
        date_key("purchased_at").alias("purchase_date_key"),
        date_key("shipping_limit_at").alias("shipping_limit_date_key"),
        "order_status", "price", "freight_value",
    )


def build_fact_payments(payments: DataFrame, orders: DataFrame) -> DataFrame:
    order = orders.select("order_id", "customer_id", "purchased_at", "order_status")
    return payments.join(order, "order_id", "left").select(
        "order_id", "payment_sequential", "customer_id",
        date_key("purchased_at").alias("purchase_date_key"),
        "order_status", "payment_type", "payment_installments", "payment_value",
    )


def build_fact_orders(orders: DataFrame, items: DataFrame, payments: DataFrame) -> DataFrame:
    # Aggregate FIRST, each table on its own: one row per order...
    item_totals = items.groupBy("order_id").agg(
        F.count("*").cast("int").alias("item_count"),
        F.sum("price").cast(TOTAL).alias("items_price"),
        F.sum("freight_value").cast(TOTAL).alias("items_freight"),
    )
    payment_totals = payments.groupBy("order_id").agg(
        F.count("*").cast("int").alias("payment_count"),
        F.sum("payment_value").cast(TOTAL).alias("payment_value"),
    )
    # ...THEN join, so every join is one order to at most one row.
    joined = orders.join(item_totals, "order_id", "left").join(payment_totals, "order_id", "left")

    # Delivered = status 'delivered' AND a delivery timestamp (8 'delivered' orders have none).
    delivered = (F.col("order_status") == "delivered") & F.col("delivered_customer_at").isNotNull()
    delivered_date = F.to_date("delivered_customer_at")
    late = delivered_date > F.col("estimated_delivery_date")
    # DATEDIFF(MINUTE, a, b) counts minute boundaries crossed, i.e. whole minutes since the
    # epoch of b minus those of a. Integer arithmetic, then exact decimal division.
    minutes = (F.floor(F.unix_timestamp("delivered_customer_at") / 60)
               - F.floor(F.unix_timestamp("purchased_at") / 60))
    days = (minutes.cast("decimal(12,0)") / F.lit(1440).cast("decimal(4,0)")).cast("decimal(7,2)")

    return joined.select(
        "order_id", "customer_id",
        date_key("purchased_at").alias("purchase_date_key"),
        date_key("approved_at").alias("approved_date_key"),
        date_key("delivered_carrier_at").alias("delivered_carrier_date_key"),
        date_key("delivered_customer_at").alias("delivered_customer_date_key"),
        date_key("estimated_delivery_date").alias("estimated_delivery_date_key"),
        "order_status", "purchased_at", "delivered_customer_at", "estimated_delivery_date",
        F.coalesce("item_count", F.lit(0)).alias("item_count"),
        F.coalesce("items_price", F.lit(0).cast(TOTAL)).alias("items_price"),
        F.coalesce("items_freight", F.lit(0).cast(TOTAL)).alias("items_freight"),
        F.coalesce("payment_count", F.lit(0)).alias("payment_count"),
        F.coalesce("payment_value", F.lit(0).cast(TOTAL)).alias("payment_value"),
        F.when(delivered, days).alias("delivery_days"),
        F.datediff("estimated_delivery_date", F.to_date("purchased_at")).alias("estimated_delivery_days"),
        F.when(delivered, F.datediff(delivered_date, "estimated_delivery_date")).alias("delivery_vs_estimate_days"),
        delivered.cast("int").alias("is_delivered"),
        F.when(delivered, late.cast("int")).alias("is_late"),
        F.when(~delivered, "Not delivered").when(late, "Late").otherwise("On time").alias("delivery_status"),
    )


def changed_at() -> F.Column:
    return F.coalesce("_updated_at", "_inserted_at")


def read_mark(spark: SparkSession, config: LakehouseConfig) -> str:
    path = config.table("gold", "watermark")
    if not DeltaTable.isDeltaTable(spark, path):
        return EPOCH
    row = spark.read.format("delta").load(path).first()
    return str(row["last_change_utc"])


def save_mark(spark: SparkSession, config: LakehouseConfig, mark: str, run_id: str) -> None:
    row = spark.createDataFrame([("gold_facts", mark, run_id)], "target_object string, mark string, run_id string")
    (row.select("target_object", F.col("mark").cast("timestamp").alias("last_change_utc"), "run_id")
        .write.format("delta").mode("overwrite").save(config.table("gold", "watermark")))


def affected_orders(silver: dict[str, DataFrame], old_mark: str, new_mark: str) -> DataFrame:
    in_window = (changed_at() > F.lit(old_mark).cast("timestamp")) & (changed_at() <= F.lit(new_mark).cast("timestamp"))
    ids = [silver[name].where(in_window).select("order_id") for name in ("orders", "order_items", "order_payments")]
    return ids[0].unionByName(ids[1]).unionByName(ids[2]).distinct()


def apply_rebuild(spark: SparkSession, path: str, rebuilt: DataFrame, affected: DataFrame,
                  keys: list[str]) -> dict[str, int]:
    """Replace the rows of the affected orders with their rebuilt rows, in one commit."""
    if not DeltaTable.isDeltaTable(spark, path):
        rebuilt.write.format("delta").save(path)
        return {"inserted": spark.read.format("delta").load(path).count(), "updated": 0, "deleted": 0}

    current = spark.read.format("delta").load(path)
    untouched = current.join(affected, "order_id", "left_anti")
    desired = untouched.unionByName(rebuilt)
    values = [c for c in rebuilt.columns if c not in keys and c != "_run_id"]
    changed = " OR ".join(f"NOT (t.{c} <=> s.{c})" for c in values)
    (DeltaTable.forPath(spark, path).alias("t")
        .merge(desired.alias("s"), " AND ".join(f"t.{k} = s.{k}" for k in keys))
        .whenMatchedUpdateAll(condition=changed)
        .whenNotMatchedInsertAll()
        .whenNotMatchedBySourceDelete()
        .execute())
    return last_operation_metrics(spark, path)


def load(spark: SparkSession, config: LakehouseConfig, run_id: str) -> dict:
    """Rebuild the gold facts for every order changed since the last run."""
    silver = {name: spark.read.format("delta").load(config.table("silver", name))
              for name in ("orders", "order_items", "order_payments")}
    old_mark = read_mark(spark, config)
    marks = [silver[name].agg(F.max(changed_at())).first()[0] for name in silver]
    new_mark = str(max(mark for mark in marks if mark is not None)) if any(marks) else old_mark

    affected = affected_orders(silver, old_mark, new_mark).cache()
    result = {"affected_orders": affected.count(), "facts": {}}
    if result["affected_orders"] == 0:
        affected.unpersist()
        return result  # nothing changed: no commit at all, the tables keep their version

    orders, items, payments = (silver[name].join(affected, "order_id", "left_semi")
                               for name in ("orders", "order_items", "order_payments"))
    builds = {
        "fact_orders": build_fact_orders(orders, items, payments),
        "fact_order_items": build_fact_order_items(items, silver["orders"]),
        "fact_payments": build_fact_payments(payments, silver["orders"]),
    }
    for fact, rebuilt in builds.items():
        rebuilt = rebuilt.withColumn("_run_id", F.lit(run_id))
        result["facts"][fact] = apply_rebuild(spark, config.table("gold", fact), rebuilt, affected, FACT_KEYS[fact])
    save_mark(spark, config, new_mark, run_id)
    affected.unpersist()
    return result
