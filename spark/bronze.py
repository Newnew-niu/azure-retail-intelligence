"""Bronze: source CSV files -> Delta tables, every column as text.

Same idea as the raw layer of the SQL warehouse (design decision #2): nothing is typed here,
so a bad value can never fail the load. Typing and rejects happen in silver.

Each row gets three lineage columns:
    _batch_id     the batch the file belongs to ('full' or 'sim_01_2017-12', ...)
    _source_file  the file the row was read from
    _ingested_at  when this run read it (UTC)

Loading a batch replaces that batch's rows and nothing else (Delta replaceWhere), so
re-running a batch never duplicates it.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from spark.config import SOURCE_SCHEMA, LakehouseConfig

# The money-critical part of the warehouse, plus customers as the one lookup the KPIs need
# (customer_unique_id identifies the person behind an order).
ENTITIES = ["orders", "order_items", "order_payments", "customers"]


def load_contract(path: Path = SOURCE_SCHEMA) -> dict:
    """config/source_schema.yml, the same file the Python validator enforces."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def text_schema(columns: list[dict]) -> StructType:
    return StructType([StructField(column["name"], StringType(), True) for column in columns])


def read_csv(spark: SparkSession, path: str, columns: list[dict]) -> DataFrame:
    """Read one source file as text. Empty fields become NULL, as in the SQL raw layer."""
    # The header is checked first: with an explicit schema Spark would otherwise map
    # columns by position and silently accept a file whose columns were reordered.
    header = spark.read.option("header", True).csv(path).columns
    expected = [column["name"] for column in columns]
    if [name.lstrip("﻿") for name in header] != expected:
        raise ValueError(f"{path}: header {header} does not match the contract {expected}")
    return (
        spark.read.option("header", True)
        .option("multiLine", True)  # quoted values may contain line breaks
        .option("escape", '"')      # a quote inside a quoted value is written as ""
        .schema(text_schema(columns))
        .csv(path)
    )


def ingest(spark: SparkSession, config: LakehouseConfig, source_dir: str, batch_id: str,
           ingested_at: str, contract: dict | None = None) -> dict[str, int]:
    """Load one batch folder into the bronze tables. Returns rows read per entity."""
    contract = contract or load_contract()
    counts = {}
    for entity in ENTITIES:
        spec = contract["entities"][entity]
        path = f"{source_dir.rstrip('/')}/{spec['file']}"
        rows = (
            read_csv(spark, path, spec["columns"])
            .withColumn("_batch_id", F.lit(batch_id))
            .withColumn("_source_file", F.col("_metadata.file_path"))
            .withColumn("_ingested_at", F.lit(ingested_at).cast("timestamp"))
        )
        (rows.write.format("delta")
             .mode("overwrite")
             .option("replaceWhere", f"_batch_id = '{batch_id}'")
             .save(config.table("bronze", entity)))
        counts[entity] = spark.read.format("delta").load(config.table("bronze", entity)) \
                              .where(F.col("_batch_id") == batch_id).count()
    return counts
