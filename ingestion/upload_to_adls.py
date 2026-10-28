"""Validate the source CSV files, then upload them to the ADLS Gen2 raw zone as one batch.

    python -m ingestion.upload_to_adls [--batch-id full_load] [--data-dir data/raw]

Layout in the `raw` container (file system):
    olist/batch_id=<batch_id>/<source file>.csv
    olist/batch_id=<batch_id>/_validation_report.json     <- the validator's report for exactly these files

Nothing is uploaded unless every file passes validation, so the raw zone only holds
batches that met the source contract. Re-uploading a batch overwrites its files
(idempotent). Each file carries its SHA-256 and row count as blob metadata for lineage.

Authentication: the signed-in `az login` identity (needs Storage Blob Data Contributor);
the storage account has shared-key access disabled, so no account key or SAS exists.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from azure.identity import AzureCliCredential
from azure.storage.filedatalake import DataLakeServiceClient

from ingestion import db  # noqa: F401  (importing it loads .env)
from ingestion import validate_files

log = logging.getLogger("upload_to_adls")

FILE_SYSTEM = "raw"
SOURCE_PREFIX = "olist"


def batch_directory(batch_id: str) -> str:
    return f"{SOURCE_PREFIX}/batch_id={batch_id}"


def upload_batch(account: str, data_dir: Path, batch_id: str) -> dict:
    report = validate_files.run(data_dir, validate_files.DEFAULT_CONTRACT, validate_files.DEFAULT_REPORT_DIR)
    if report["status"] != "PASSED":
        raise RuntimeError(f"Validation failed ({report['files_failed']} file(s)); nothing uploaded. "
                           f"See {report.get('report_path')}")

    service = DataLakeServiceClient(f"https://{account}.dfs.core.windows.net", credential=AzureCliCredential())
    directory = service.get_file_system_client(FILE_SYSTEM).get_directory_client(batch_directory(batch_id))
    directory.create_directory()

    for result in report["results"]:
        path = data_dir / result["file"]
        with path.open("rb") as stream:
            directory.get_file_client(result["file"]).upload_data(
                stream, overwrite=True,
                metadata={"sha256": result["sha256"], "row_count": str(result["row_count"]),
                          "validation_run_id": report["run_id"]})
        log.info("uploaded %-45s %10s rows  %.1f MB", result["file"], f"{result['row_count']:,}",
                 path.stat().st_size / 1e6)

    directory.get_file_client("_validation_report.json").upload_data(
        json.dumps(report, indent=2).encode("utf-8"), overwrite=True)
    log.info("uploaded _validation_report.json -> %s/%s", FILE_SYSTEM, batch_directory(batch_id))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--batch-id", default="full_load")
    parser.add_argument("--data-dir", type=Path, default=validate_files.DEFAULT_DATA_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Keep the SDK's per-request HTTP logging out of the output
    logging.getLogger("azure").setLevel(logging.WARNING)

    account = os.getenv("AZURE_STORAGE_ACCOUNT")
    if not account:
        log.error("AZURE_STORAGE_ACCOUNT is not set (see .env.example)")
        return 2
    try:
        upload_batch(account, args.data_dir, args.batch_id)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
