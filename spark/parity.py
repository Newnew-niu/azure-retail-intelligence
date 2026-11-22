"""Parity proof: the Spark lakehouse reproduces the T-SQL warehouse. Writes reports/spark_parity.md.

    python -m spark.parity                      # runs both loads, then compares
    python -m spark.parity --skip-run           # compare existing tables only

1. Full load (data/raw) and incremental load (the 9 SIMULATED batches in data/batches),
   each into its own fresh lakehouse folder, timed.
2. Incremental = full: every gold fact compared row by row (exceptAll both ways).
3. KPIs = SQL Server: the GOLDEN_KPIS SQL of serving/golden_kpis.py, run on the gold tables,
   compared with data/serving_baseline.json (computed by SQL Server).
4. Rows = SQL Server: every gold fact compared row by row with the dw facts in the DuckDB
   export (data/serving.duckdb), after mapping surrogate keys back to natural keys.
Exit code 0 only if every comparison matches.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, localcontext
from importlib.metadata import version
from pathlib import Path

import pyspark
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from spark import run as lakehouse
from spark.config import LakehouseConfig
from spark.gold import FACT_KEYS
from spark.session import get_spark

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from serving.golden_kpis import GOLDEN_KPIS  # noqa: E402

DATA = PROJECT_ROOT / "data"
BASELINE = DATA / "serving_baseline.json"
EXPORT = DATA / "serving.duckdb"
REPORT = PROJECT_ROOT / "reports" / "spark_parity.md"
WORK = PROJECT_ROOT / "lakehouse"
EXACT_KPIS = {"sales_orders", "product_sales"}  # a count and a money sum: no division involved
# For an average, its exact value is shown as SUM / COUNT, which both engines compute exactly.
AVERAGE_PARTS = {"average_delivery_days": ("AVG(delivery_days)", "SUM(delivery_days), COUNT(delivery_days)")}

# The dw facts of the export with natural keys instead of surrogate keys (as in
# scripts/verify_incremental.py). fact_orders' review columns are outside the Spark scope.
EXPORT_QUERIES = {
    "fact_orders": "SELECT f.order_id, c.customer_id, f.purchase_date_key, f.approved_date_key, "
                   "f.delivered_carrier_date_key, f.delivered_customer_date_key, f.estimated_delivery_date_key, "
                   "f.order_status, f.purchased_at, f.delivered_customer_at, f.estimated_delivery_date, f.item_count, "
                   "f.items_price, f.items_freight, f.payment_count, f.payment_value, f.delivery_days, "
                   "f.estimated_delivery_days, f.delivery_vs_estimate_days, f.is_delivered, f.is_late, f.delivery_status "
                   "FROM dw.fact_orders AS f JOIN dw.dim_customer AS c ON c.customer_key = f.customer_key",
    "fact_order_items": "SELECT f.order_id, f.order_item_id, p.product_id, s.seller_id, c.customer_id, "
                        "f.purchase_date_key, f.shipping_limit_date_key, f.order_status, f.price, f.freight_value "
                        "FROM dw.fact_order_items AS f JOIN dw.dim_product AS p ON p.product_key = f.product_key "
                        "JOIN dw.dim_seller AS s ON s.seller_key = f.seller_key "
                        "JOIN dw.dim_customer AS c ON c.customer_key = f.customer_key",
    "fact_payments": "SELECT f.order_id, f.payment_sequential, c.customer_id, f.purchase_date_key, f.order_status, "
                     "f.payment_type, f.payment_installments, f.payment_value FROM dw.fact_payments AS f "
                     "JOIN dw.dim_customer AS c ON c.customer_key = f.customer_key",
}


def gold(spark: SparkSession, config: LakehouseConfig, fact: str) -> DataFrame:
    return spark.read.format("delta").load(config.table("gold", fact)).drop("_run_id")


def money_columns(df: DataFrame) -> list[str]:
    return [f.name for f in df.schema.fields if f.dataType.typeName() == "decimal"]


def row_diff(left: DataFrame, right: DataFrame) -> dict:
    """Row count, money totals and rows found on one side only (duplicates counted)."""
    money = money_columns(left)
    left_totals = left.agg(*[F.sum(c) for c in money]).first() if money else []
    right_totals = right.agg(*[F.sum(c) for c in money]).first() if money else []
    return {
        "rows": (left.count(), right.count()),
        "totals": {c: (left_totals[i], right_totals[i]) for i, c in enumerate(money)},
        "only_left": left.exceptAll(right).count(),
        "only_right": right.exceptAll(left).count(),
    }


def diff_ok(result: dict) -> bool:
    same_totals = all(a == b for a, b in result["totals"].values())
    return result["rows"][0] == result["rows"][1] and same_totals and result["only_left"] == result["only_right"] == 0


def kpi_values(spark: SparkSession, config: LakehouseConfig) -> dict[str, Decimal]:
    """The GOLDEN_KPIS SQL on the gold tables.

    Spark temporary views cannot have a schema prefix, so `dw.x` is read as `dw_x`; the SQL
    is otherwise run unchanged. customer_key is the natural customer_id here (no surrogates).
    """
    gold(spark, config, "fact_orders").withColumn("customer_key", F.col("customer_id")) \
        .createOrReplaceTempView("dw_fact_orders")
    gold(spark, config, "fact_order_items").createOrReplaceTempView("dw_fact_order_items")
    spark.read.format("delta").load(config.table("silver", "customers")) \
        .select(F.col("customer_id").alias("customer_key"), "customer_id", "customer_unique_id") \
        .createOrReplaceTempView("dw_dim_customer")
    return {name: Decimal(str(spark.sql(re.sub(r"\bdw\.", "dw_", kpi["sql"])).first()[0]))
            for name, kpi in GOLDEN_KPIS.items()}


def compare_kpi(name: str, ours: Decimal, theirs: Decimal) -> tuple[bool, str]:
    if ours == theirs:
        return True, "exact"
    if name in EXACT_KPIS:
        return False, "DIFFERENT"
    # An average or ratio ends in a division, and the engines keep a different number of
    # digits and round the last one differently. Compared at the precision of the less
    # precise result, the two may differ by at most one unit in that last place.
    places = min(-ours.as_tuple().exponent, -theirs.as_tuple().exponent)
    unit = Decimal(1).scaleb(-places)
    same = abs(ours - theirs) <= unit
    return same, f"within one unit of the {places}th decimal place" if same else "DIFFERENT"


def exact_averages(spark: SparkSession, ours: dict[str, Decimal], baseline: dict[str, str]) -> list[str]:
    """Explain an average that is not digit-for-digit equal: its exact SUM / COUNT."""
    notes = []
    for name, (average, parts) in AVERAGE_PARTS.items():
        if ours[name] == Decimal(baseline[name]):
            continue
        sql = re.sub(r"\bdw\.", "dw_", GOLDEN_KPIS[name]["sql"]).replace(average, parts)
        total, count = spark.sql(sql).first()
        with localcontext() as context:
            context.prec = 40
            exact = Decimal(total) / Decimal(count)
        places = -Decimal(baseline[name]).as_tuple().exponent
        step = Decimal(1).scaleb(-places)
        rule = {exact.quantize(step, ROUND_DOWN): "truncates", exact.quantize(step, ROUND_HALF_UP): "rounds half up"}
        notes.append(f"`{name}`: SUM {total} / COUNT {count:,} = {exact} exactly. To {places} decimal places, "
                     f"SQL Server's {baseline[name]} {rule.get(Decimal(baseline[name]), 'neither truncates nor rounds')} "
                     f"and Spark's {ours[name]} {rule.get(ours[name], 'neither truncates nor rounds')}.")
    return notes


def export_facts(spark: SparkSession, folder: Path) -> dict[str, DataFrame]:
    """The DuckDB export's facts, with natural keys, as Spark DataFrames (via Parquet)."""
    import duckdb

    if not EXPORT.exists():
        raise FileNotFoundError(f"{EXPORT.relative_to(PROJECT_ROOT)} not found - run scripts/export_serving_db.py")
    con = duckdb.connect(str(EXPORT), read_only=True)
    try:
        for fact, query in EXPORT_QUERIES.items():
            con.execute(f"COPY ({query}) TO '{(folder / fact).as_posix()}.parquet' (FORMAT parquet)")
    finally:
        con.close()
    return {fact: spark.read.parquet(f"{(folder / fact).as_posix()}.parquet") for fact in EXPORT_QUERIES}


def align(df: DataFrame, like: DataFrame) -> DataFrame:
    """Same columns and types as `like` (DuckDB stores BIT as TINYINT, timestamps without zone)."""
    return df.select(*[F.col(f.name).cast(f.dataType).alias(f.name) for f in like.schema.fields])


def run_loads(spark: SparkSession, full: LakehouseConfig, incremental: LakehouseConfig) -> dict:
    timings = {}
    for label, config, data_dir, mode in [("full", full, DATA / "raw", "full"),
                                          ("incremental", incremental, DATA / "batches", "incremental")]:
        shutil.rmtree(config.base_path, ignore_errors=True)
        started = time.perf_counter()
        batches = []
        for source_dir, batch_id in lakehouse.batch_folders(spark, data_dir.as_posix(), mode):
            summary = lakehouse.run_batch(spark, config, source_dir, batch_id)
            lakehouse.print_summary(summary)
            batches.append(summary)
        timings[label] = {"seconds": round(time.perf_counter() - started, 1), "batches": batches}
    return timings


def fmt(value) -> str:
    return f"{value:,}" if isinstance(value, int) else str(value)


def report(results: dict) -> str:
    lines = [
        "# Spark parity report",
        "",
        f"Generated by `python -m spark.parity` on {results['generated']} "
        f"(PySpark {pyspark.__version__}, Delta Lake {results['delta']}, Python {platform.python_version()}, "
        f"{platform.system()} {platform.release()}). Do not edit by hand.",
        "",
    ]
    if results.get("timings"):
        lines += ["## Runtime", "", "| Load | Batches | Seconds |", "|---|---:|---:|"]
        for label, t in results["timings"].items():
            lines.append(f"| {label} | {len(t['batches'])} | {t['seconds']} |")
        lines += ["", f"Spark session start-up: {results['startup_seconds']} s (not included above).", ""]
        lines += ["Incremental batches (SIMULATED monthly replays, not change data capture):", "",
                  "| Batch | Seconds | Orders rebuilt | fact_orders inserted / updated / deleted | DQ checks passed |",
                  "|---|---:|---:|---|---:|"]
        for b in results["timings"]["incremental"]["batches"]:
            m = b["gold"]["facts"].get("fact_orders", {"inserted": 0, "updated": 0, "deleted": 0})
            passed = sum(1 for row in b["dq"] if row[6] == "PASS")
            lines.append(f"| {b['batch_id']} | {b['seconds']} | {b['gold']['affected_orders']:,} | "
                         f"{m['inserted']:,} / {m['updated']:,} / {m['deleted']:,} | {passed} of {len(b['dq'])} |")
        lines.append("")

    def diff_table(title: str, left: str, right: str, diffs: dict) -> list[str]:
        out = [f"## {title}", "", f"| Table | Rows ({left}) | Rows ({right}) | Only in {left} | Only in {right} | "
               "Money totals | Result |", "|---|---:|---:|---:|---:|---|---|"]
        for fact, d in diffs.items():
            totals = "; ".join(f"{c} {a} vs {b}" for c, (a, b) in d["totals"].items())
            out.append(f"| {fact} | {d['rows'][0]:,} | {d['rows'][1]:,} | {d['only_left']:,} | {d['only_right']:,} | "
                       f"{totals} | {'PASS' if diff_ok(d) else 'FAIL'} |")
        return out + [""]

    lines += diff_table("Incremental = full (Spark)", "incremental", "full", results["incremental_vs_full"])
    lines += ["## KPIs = SQL Server", "",
              "GOLDEN_KPIS from `serving/golden_kpis.py` on the Spark gold tables vs `data/serving_baseline.json`.",
              "", "| KPI | Spark | SQL Server | Result |", "|---|---:|---:|---|"]
    for name, (ours, theirs, ok, how) in results["kpis"].items():
        lines.append(f"| {name} | {ours} | {theirs} | {'PASS' if ok else 'FAIL'} ({how}) |")
    lines += [""] + [f"- {note}" for note in results["kpi_notes"]] + ([""] if results["kpi_notes"] else [])
    if results.get("export"):
        lines += diff_table("Rows = SQL Server (DuckDB export of dw)", "Spark", "SQL Server", results["export"])
    else:
        lines += ["## Rows = SQL Server", "", f"Not run: {results['export_skipped']}", ""]
    lines += [f"**Overall: {'PASS' if results['passed'] else 'FAIL'}**", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--skip-run", action="store_true", help="compare the existing lakehouse folders")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    spark = get_spark()
    results = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
               "startup_seconds": round(time.perf_counter() - started, 1),
               "delta": version("delta-spark")}
    full, incremental = LakehouseConfig.create(str(WORK / "full")), LakehouseConfig.create(str(WORK / "incremental"))
    if not args.skip_run:
        results["timings"] = run_loads(spark, full, incremental)

    results["incremental_vs_full"] = {fact: row_diff(gold(spark, incremental, fact), gold(spark, full, fact))
                                      for fact in FACT_KEYS}
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    ours = kpi_values(spark, full)
    results["kpis"] = {name: (ours[name], Decimal(baseline[name]), *compare_kpi(name, ours[name], Decimal(baseline[name])))
                       for name in GOLDEN_KPIS}
    results["kpi_notes"] = exact_averages(spark, ours, baseline)

    try:
        with tempfile.TemporaryDirectory() as folder:
            exported = export_facts(spark, Path(folder))
            results["export"] = {fact: row_diff(gold(spark, full, fact),
                                                align(exported[fact], gold(spark, full, fact)))
                                 for fact in FACT_KEYS}
    except (ImportError, FileNotFoundError) as error:
        results["export"], results["export_skipped"] = None, str(error)

    results["passed"] = (all(diff_ok(d) for d in results["incremental_vs_full"].values())
                         and all(ok for _, _, ok, _ in results["kpis"].values())
                         and results["export"] is not None
                         and all(diff_ok(d) for d in results["export"].values()))
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(report(results), encoding="utf-8")
    print(report(results))
    return 0 if results["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
