"""Deploy the version-controlled SQL scripts to the target database.

Runs every file listed in sql/deploy_manifest.txt, in order. Scripts are written
to be re-runnable (CREATE OR ALTER, IF OBJECT_ID(...) IS NULL), so deploying twice
is safe. Batches are split on 'GO' lines, as in SSMS and sqlcmd.

Local LocalDB only: the database is created if it does not exist, and --reset
drops and recreates it (refused for any non-local server).

Usage:
    python scripts/deploy_sql.py [--reset]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ingestion import db  # noqa: E402

SQL_DIR = PROJECT_ROOT / "sql"
MANIFEST = SQL_DIR / "deploy_manifest.txt"
GO_LINE = re.compile(r"^\s*GO\s*$", re.IGNORECASE | re.MULTILINE)


def manifest_files() -> list[Path]:
    lines = MANIFEST.read_text(encoding="utf-8").splitlines()
    files = [SQL_DIR / line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        raise FileNotFoundError(f"Listed in {MANIFEST.name} but not found: {', '.join(missing)}")
    return files


def ensure_local_database(reset: bool) -> None:
    name = db.database_name()
    if not re.fullmatch(r"\w+", name):
        raise ValueError(f"Unsafe database name: {name!r}")
    with db.connect(database="master", autocommit=True) as conn:
        if reset:
            print(f"Dropping local database {name} ...")
            conn.execute(f"IF DB_ID(N'{name}') IS NOT NULL BEGIN "
                         f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{name}]; END")
        conn.execute(f"IF DB_ID(N'{name}') IS NULL CREATE DATABASE [{name}]")


def deploy() -> None:
    with db.connect(autocommit=True) as conn:
        for path in manifest_files():
            batches = [b for b in GO_LINE.split(path.read_text(encoding="utf-8")) if b.strip()]
            for i, batch in enumerate(batches, start=1):
                try:
                    conn.execute(batch)
                except Exception as exc:
                    raise RuntimeError(f"{path.relative_to(PROJECT_ROOT)} batch {i} failed: {exc}") from exc
            print(f"  deployed {path.relative_to(SQL_DIR)} ({len(batches)} batch(es))")


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy SQL scripts listed in sql/deploy_manifest.txt")
    parser.add_argument("--reset", action="store_true", help="LOCAL ONLY: drop and recreate the database first")
    args = parser.parse_args()

    if db.is_local():
        ensure_local_database(args.reset)
    elif args.reset:
        print("--reset is only allowed against LocalDB.", file=sys.stderr)
        return 2
    print(f"Deploying to database '{db.database_name()}' ...")
    deploy()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
