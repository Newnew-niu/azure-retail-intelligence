"""Run the lakehouse: bronze -> silver -> gold -> data quality, for one or more batches.

    python -m spark.run --mode full        --data-dir data/raw     --base-path lakehouse/full
    python -m spark.run --mode incremental --data-dir data/batches --base-path lakehouse/incremental

full         one batch ('full') from the CSV files in --data-dir
incremental  every SIMULATED batch folder in --data-dir (sim_01_..., sim_02_..., oldest
             first), as written by scripts/make_incremental_batches.py. Not CDC.

Every step is safe to re-run: a batch that is loaded again changes nothing.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from datetime import datetime, timezone

from spark import bronze, gold, quality, silver
from spark.config import LakehouseConfig
from spark.session import get_spark


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def run_batch(spark, config: LakehouseConfig, source_dir: str, batch_id: str) -> dict:
    """Load one batch through every layer. Raises DataQualityError if the gate fails."""
    run_ts = utc_now()  # one timestamp per run: lineage, change markers and the watermark
    run_id = f"spark-{run_ts[:19].replace(' ', 'T')}-{batch_id}"
    started = time.perf_counter()
    contract = bronze.load_contract()
    summary = {"batch_id": batch_id, "run_id": run_id}
    summary["bronze"] = bronze.ingest(spark, config, source_dir, batch_id, run_ts, contract)
    summary["silver"] = silver.load(spark, config, batch_id, run_id, run_ts, contract)
    summary["gold"] = gold.load(spark, config, run_id)
    summary["dq"] = quality.run(spark, config, run_id, run_ts)
    summary["seconds"] = round(time.perf_counter() - started, 1)
    return summary


def batch_folders(spark, data_dir: str, mode: str) -> list[tuple[str, str]]:
    """(source folder, batch id) pairs in load order."""
    if mode == "full":
        return [(data_dir, "full")]
    # Listed through Hadoop's FileSystem, which Spark itself uses, so the same call works
    # for a local folder and for an abfss:// OneLake path.
    folder = spark._jvm.org.apache.hadoop.fs.Path(data_dir)
    fs = folder.getFileSystem(spark._jsc.hadoopConfiguration())
    names = sorted(s.getPath().getName() for s in fs.listStatus(folder) if s.isDirectory())
    batches = [name for name in names if name.startswith("sim_")]
    if not batches:
        raise SystemExit(f"No sim_* batch folders in {data_dir} - run scripts/make_incremental_batches.py first")
    return [(f"{data_dir.rstrip('/')}/{name}", name) for name in batches]


def print_summary(summary: dict) -> None:
    silver_counts = summary["silver"]
    dq_passed = sum(1 for row in summary["dq"] if row[6] == "PASS")
    facts = summary["gold"]["facts"]
    changes = ", ".join(f"{fact} +{m['inserted']:,} ~{m['updated']:,} -{m['deleted']:,}" for fact, m in facts.items())
    print(f"{summary['batch_id']:<22} {summary['seconds']:6.1f} s  "
          f"silver rejected={sum(c['rejected'] for c in silver_counts.values())}  "
          f"orders rebuilt={summary['gold']['affected_orders']:,}  DQ {dq_passed}/{len(summary['dq'])} PASS  "
          f"{changes or 'no gold changes'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--mode", choices=["full", "incremental"], required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--base-path", help="lakehouse folder or abfss:// URL (default: LAKEHOUSE_BASE_PATH)")
    parser.add_argument("--reset", action="store_true", help="delete a LOCAL base path first")
    args = parser.parse_args(argv)

    config = LakehouseConfig.from_env(args.base_path)
    if args.reset:
        if "://" in config.base_path:
            raise SystemExit("--reset only deletes local folders")
        shutil.rmtree(config.base_path, ignore_errors=True)

    spark = get_spark()
    started = time.perf_counter()
    try:
        for source_dir, batch_id in batch_folders(spark, args.data_dir, args.mode):
            print_summary(run_batch(spark, config, source_dir, batch_id))
    except quality.DataQualityError as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    print(f"Done in {time.perf_counter() - started:.1f} s -> {config.base_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
