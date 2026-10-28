"""Download the Olist Brazilian E-Commerce dataset into data/raw/.

Source: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
License: CC BY-NC-SA 4.0 (Olist). The data is not committed to this repository;
run this script to reproduce the exact inputs.

Uses Kaggle's public dataset download endpoint (no account needed for this
public dataset at the time of writing). If it ever requires authentication,
download the zip manually from the page above and pass it with --zip.

Only the CSV files named in config/source_schema.yml are extracted.

Usage:
    python scripts/download_data.py            # download + extract
    python scripts/download_data.py --zip path/to/archive.zip
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "raw"
CONTRACT = PROJECT_ROOT / "config" / "source_schema.yml"
URL = "https://www.kaggle.com/api/v1/datasets/download/olistbr/brazilian-ecommerce"
# Archive hash observed on 2026-10-28. A different hash means Kaggle published a
# new version: the pipeline may still work, but re-run validation and re-check results.
KNOWN_SHA256 = "967e41e04fc306fe604e2a693f488995a8b41e5047418f8a5c8e4abd6deca784"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract(zip_path: Path, target: Path) -> None:
    with CONTRACT.open(encoding="utf-8") as f:
        expected = {spec["file"] for spec in yaml.safe_load(f)["entities"].values()}
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        # Match on the base name only and write to a fixed folder, so archive paths
        # such as '../x.csv' can never escape data/raw/.
        members = {Path(m).name: m for m in zf.namelist() if Path(m).name in expected}
        missing = expected - members.keys()
        if missing:
            sys.exit(f"Archive is missing expected file(s): {', '.join(sorted(missing))}")
        for name, member in sorted(members.items()):
            (target / name).write_bytes(zf.read(member))
            print(f"  extracted {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download the Olist dataset into data/raw/")
    parser.add_argument("--zip", type=Path, help="use an already downloaded archive instead")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = args.zip
        if zip_path is None:
            zip_path = Path(tmp) / "olist.zip"
            print(f"Downloading {URL} ...")
            urllib.request.urlretrieve(URL, zip_path)

        actual = sha256_of(zip_path)
        if actual == KNOWN_SHA256:
            print("Archive SHA-256 matches the version this project was built with.")
        else:
            print(f"WARNING: archive SHA-256 {actual} differs from the known version {KNOWN_SHA256}.")
        extract(zip_path, DATA_DIR)

    print(f"Done. Next: python -m ingestion.validate_files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
