"""The SparkSession used by the CLI and the tests.

In a Fabric (or Databricks) notebook a session with Delta Lake already exists, and
get_spark() simply returns it. Locally it builds one with the delta-spark package.
"""
from __future__ import annotations

from pyspark.sql import SparkSession

# Settings the results depend on, applied to new and existing sessions alike.
SETTINGS = {
    # Timestamps in the source have no time zone. With UTC as the session zone there is no
    # daylight-saving shift when Spark converts them, so minute differences stay exact.
    "spark.sql.session.timeZone": "UTC",
    # An unparseable timestamp becomes NULL (and the row is quarantined) instead of raising
    # an upgrade error from Spark's date parser.
    "spark.sql.legacy.timeParserPolicy": "CORRECTED",
    # Non-ANSI casts return NULL on bad input, like T-SQL TRY_CONVERT. Spark 3.5 already
    # defaults to this; it is set explicitly because Spark 4 changes the default.
    "spark.sql.ansi.enabled": "false",
}


def get_spark(app_name: str = "retail-lakehouse", local_cores: str = "*") -> SparkSession:
    active = SparkSession.getActiveSession()
    if active is not None:
        spark = active
    else:
        from delta import configure_spark_with_delta_pip

        builder = (
            SparkSession.builder.appName(app_name)
            .master(f"local[{local_cores}]")
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
            .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
            # ~100k rows per table: a handful of partitions is faster than the default 200.
            .config("spark.sql.shuffle.partitions", "8")
            .config("spark.ui.enabled", "false")
            .config("spark.ui.showConsoleProgress", "false")
            # Delta rebuilds a table's state from its log with 50 tasks by default; for
            # small local tables a few are faster.
            .config("spark.databricks.delta.snapshotPartitions", "4")
        )
        spark = configure_spark_with_delta_pip(builder).getOrCreate()
    for key, value in SETTINGS.items():
        spark.conf.set(key, value)
    return spark
