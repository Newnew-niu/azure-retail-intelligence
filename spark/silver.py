"""Silver: typed, validated, latest version per business key.

The PySpark port of sql/staging/usp_load_<entity>.sql, for the four entities in scope:

  1. Take this batch's bronze rows and keep the latest version of each business key.
  2. Cast every column to the type config/source_schema.yml gives it. The rejection rules
     are generated from the same file, in column order, so a row gets the same first
     reason as in staging (e.g. 'price is empty or not a decimal(10,2)').
  3. Rejected rows go to silver_quarantine with the reason and the raw values. They are
     reported, never silently dropped.
  4. Valid rows are MERGEd into silver_<entity>: new keys inserted, existing keys updated
     only when a value really changed. Re-running a batch therefore writes 0 rows, and
     _updated_at is a trustworthy change marker for the gold watermark (decision #4).

What source_schema.yml does not know lives in SPECS below: the business key, which columns
are 32-character hex ids, how text is normalised, and the readable target names (the same
renames as sql/staging/01_tables.sql).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from delta.tables import DeltaTable
from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from spark.bronze import ENTITIES, load_contract
from spark.config import LakehouseConfig

HEX32 = r"^[0-9a-fA-F]{32}$"   # T-SQL's LIKE '[0-9a-f]' is case-insensitive under the default collation
INTEGER = r"^\s*[+-]?\d+\s*$"  # Spark would cast '1.5' to 1; TRY_CONVERT(INT, '1.5') is NULL
DECIMAL = r"^\s*[+-]?(\d+(\.\d*)?|\.\d+)\s*$"  # Spark would also accept '1e5'; T-SQL does not
TIMESTAMP_FORMAT = "yyyy-MM-dd HH:mm:ss"
MONEY = "decimal(10,2)"  # DECIMAL(10,2) in stg.order_items / stg.order_payments
TYPE_LABELS = {"integer": "an integer", "decimal": "a decimal(10,2)", "timestamp": "a timestamp"}
# Reason texts for the 'pattern' rules in source_schema.yml, worded as in staging.
PATTERN_REASONS = {r"\d{5}": "is not 5 digits", "[A-Z]{2}": "is not a 2-letter code"}


@dataclass(frozen=True)
class SilverSpec:
    keys: list[str]                                         # business key (source names)
    hex_ids: tuple[str, ...]                                # must be 32-character hex ids
    rename: dict[str, str] = field(default_factory=dict)    # source name -> silver name
    normalise: dict[str, str] = field(default_factory=dict) # 'lower' | 'upper' | 'trim'
    date_only: tuple[str, ...] = ()                         # timestamps stored as DATE


SPECS = {
    "orders": SilverSpec(
        keys=["order_id"],
        hex_ids=("order_id", "customer_id"),
        normalise={"order_status": "lower"},
        rename={"order_purchase_timestamp": "purchased_at", "order_approved_at": "approved_at",
                "order_delivered_carrier_date": "delivered_carrier_at",
                "order_delivered_customer_date": "delivered_customer_at",
                "order_estimated_delivery_date": "estimated_delivery_date"},
        date_only=("order_estimated_delivery_date",),
    ),
    "order_items": SilverSpec(
        keys=["order_id", "order_item_id"],
        hex_ids=("order_id", "product_id", "seller_id"),
        rename={"shipping_limit_date": "shipping_limit_at"},
    ),
    "order_payments": SilverSpec(
        keys=["order_id", "payment_sequential"],
        hex_ids=("order_id",),
        normalise={"payment_type": "lower"},
    ),
    "customers": SilverSpec(
        keys=["customer_id"],
        hex_ids=("customer_id", "customer_unique_id"),
        normalise={"customer_city": "trim", "customer_state": "upper"},
        rename={"customer_zip_code_prefix": "zip_code_prefix", "customer_city": "city", "customer_state": "state"},
    ),
}
LINEAGE = ["_batch_id", "_run_id", "_inserted_at", "_updated_at"]


def typed_value(raw: Column, column: dict, spec: SilverSpec) -> Column:
    """The value converted to its target type, or NULL when it cannot be converted."""
    name, kind = column["name"], column["type"]
    if kind == "integer":
        return F.when(raw.rlike(INTEGER), F.trim(raw).cast("int"))
    if kind == "decimal":
        return F.when(raw.rlike(DECIMAL), F.trim(raw).cast(MONEY))
    if kind == "timestamp":
        return F.to_timestamp(raw, TIMESTAMP_FORMAT)
    how = spec.normalise.get(name)
    if how is None:
        return raw
    value = {"lower": F.lower(F.trim(raw)), "upper": F.upper(F.trim(raw)), "trim": F.trim(raw)}[how]
    return F.when(value != "", value)  # NULLIF(..., N'')


def reject_reason(raw: dict[str, Column], value: dict[str, Column], columns: list[dict], spec: SilverSpec) -> Column:
    """The first rule the row breaks, checked in column order, or NULL for a valid row."""
    rules = []
    for column in columns:
        name, kind = column["name"], column["type"]
        if name in spec.hex_ids:
            rules.append((~F.coalesce(raw[name].rlike(HEX32), F.lit(False)), f"{name} is not a 32-character hex id"))
        elif "pattern" in column:
            matches = value[name].rlike(f"^{column['pattern']}$")
            rules.append((~F.coalesce(matches, F.lit(False)), f"{name} {PATTERN_REASONS[column['pattern']]}"))
        elif kind == "string":
            if column["required"]:
                rules.append((value[name].isNull(), f"{name} is empty"))
        elif column["required"]:
            rules.append((value[name].isNull(), f"{name} is empty or not {TYPE_LABELS[kind]}"))
        else:
            rules.append((raw[name].isNotNull() & value[name].isNull(), f"{name} is not {TYPE_LABELS[kind]}"))
        if name in spec.date_only:
            rules.append((F.date_format(value[name], "HH:mm:ss") != "00:00:00",
                          f"{name} has a time part; DATE would lose it"))
    return F.coalesce(*[F.when(broken, F.lit(reason)) for broken, reason in rules])


def latest_versions(rows: DataFrame, spec: SilverSpec) -> DataFrame:
    """One row per business key: the most recently ingested version.

    Rows with an empty key are all kept, so each one is counted as a reject. (Two versions
    of one key inside the same file have no defined order, exactly as in staging.)
    """
    newest_first = Window.partitionBy(*spec.keys).orderBy(F.col("_ingested_at").desc(), F.col("_batch_id").desc())
    ranked = rows.withColumn("_version_rank", F.row_number().over(newest_first))
    any_key_missing = F.lit(False)
    for key in spec.keys:
        any_key_missing = any_key_missing | F.col(key).isNull()
    return ranked.where((F.col("_version_rank") == 1) | any_key_missing).drop("_version_rank")


def prepare(bronze_rows: DataFrame, entity: str, contract: dict) -> DataFrame:
    """Latest versions with typed silver columns plus _reject_reason and _record_key."""
    spec, columns = SPECS[entity], contract["entities"][entity]["columns"]
    rows = latest_versions(bronze_rows, spec)
    raw = {c["name"]: F.col(c["name"]) for c in columns}
    value = {c["name"]: typed_value(raw[c["name"]], c, spec) for c in columns}
    record_key = F.concat_ws("|", *[F.coalesce(F.col(key), F.lit("")) for key in spec.keys])
    # date_only columns become DATE only here, after the time-part rule has seen the timestamp
    typed = [
        (value[c["name"]].cast("date") if c["name"] in spec.date_only else value[c["name"]])
        .alias(spec.rename.get(c["name"], c["name"]))
        for c in columns
    ]
    return rows.select(
        *typed,
        F.col("_batch_id"),
        reject_reason(raw, value, columns, spec).alias("_reject_reason"),
        record_key.alias("_record_key"),
        F.to_json(F.struct(*[F.col(c["name"]) for c in columns])).alias("_raw_record"),
    )


def quarantine(prepared: DataFrame, entity: str, run_id: str, run_ts: str) -> DataFrame:
    """Rejected rows in the shape of ops.rejected_row, plus the raw values."""
    return prepared.where(F.col("_reject_reason").isNotNull()).select(
        F.lit(run_id).alias("run_id"),
        F.lit(f"bronze_{entity}").alias("source_table"),
        F.col("_batch_id").alias("batch_id"),
        F.col("_record_key").alias("record_key"),
        F.col("_reject_reason").alias("reason"),
        F.col("_raw_record").alias("raw_record"),
        F.lit(run_ts).cast("timestamp").alias("quarantined_at"),
    )


def merge_valid(spark: SparkSession, path: str, valid: DataFrame, keys: list[str],
                run_id: str, run_ts: str) -> dict[str, int]:
    """Insert new keys, update changed rows only. Returns the MERGE's row counts."""
    now = F.lit(run_ts).cast("timestamp")
    values = [c for c in valid.columns if c not in keys and c != "_batch_id"]
    if not DeltaTable.isDeltaTable(spark, path):
        empty = valid.limit(0).select("*", F.lit(run_id).alias("_run_id"), now.alias("_inserted_at"),
                                      now.alias("_updated_at"))
        empty.write.format("delta").save(path)

    # <=> is null-safe equality: NULL <=> NULL is true, so NULL is not seen as a change
    # (the role EXCEPT plays in the staging MERGE).
    changed = " OR ".join(f"NOT (t.{c} <=> s.{c})" for c in values)
    on = " AND ".join(f"t.{k} = s.{k}" for k in keys)
    business = {c: f"s.{c}" for c in keys + values}
    (DeltaTable.forPath(spark, path).alias("t")
        .merge(valid.alias("s"), on)
        .whenMatchedUpdate(condition=changed,
                           set={**{c: F.col(f"s.{c}") for c in values}, "_batch_id": F.col("s._batch_id"),
                                "_run_id": F.lit(run_id), "_updated_at": now})
        .whenNotMatchedInsert(values={**{c: F.col(v) for c, v in business.items()},
                                      "_batch_id": F.col("s._batch_id"), "_run_id": F.lit(run_id),
                                      "_inserted_at": now, "_updated_at": F.lit(None).cast("timestamp")})
        .execute())
    return last_operation_metrics(spark, path)


def last_operation_metrics(spark: SparkSession, path: str) -> dict[str, int]:
    """Row counts of the latest commit, from the Delta transaction log."""
    metrics = DeltaTable.forPath(spark, path).history(1).collect()[0]["operationMetrics"]
    return {name: int(metrics.get(key, 0)) for name, key in
            [("inserted", "numTargetRowsInserted"), ("updated", "numTargetRowsUpdated"),
             ("deleted", "numTargetRowsDeleted")]}


def load(spark: SparkSession, config: LakehouseConfig, batch_id: str, run_id: str, run_ts: str,
         contract: dict | None = None) -> dict[str, dict[str, int]]:
    """Silver load of one batch for every entity. Returns read/rejected/inserted/updated counts."""
    contract = contract or load_contract()
    results = {}
    for entity in ENTITIES:
        bronze_rows = spark.read.format("delta").load(config.table("bronze", entity)) \
                           .where(F.col("_batch_id") == batch_id)
        prepared = prepare(bronze_rows, entity, contract).cache()
        rejected = quarantine(prepared, entity, run_id, run_ts)
        rejected.write.format("delta").mode("append").save(config.table("silver", "quarantine"))
        valid = prepared.where(F.col("_reject_reason").isNull()) \
                        .drop("_reject_reason", "_record_key", "_raw_record")
        keys = [SPECS[entity].rename.get(k, k) for k in SPECS[entity].keys]
        merged = merge_valid(spark, config.table("silver", entity), valid, keys, run_id, run_ts)
        results[entity] = {"read": prepared.count(), "rejected": rejected.count(), **merged}
        prepared.unpersist()
    return results
