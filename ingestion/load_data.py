"""Load validated source CSVs into the RAW layer (local development path).

In Azure, this step is performed by the Data Factory Copy activity
(ADLS Gen2 -> raw.* tables). Locally, this module plays the same role so the
SQL layers can be developed and tested without cloud resources. Both paths
follow the same contract:

  * values are inserted as text, exactly as read; empty fields become NULL
  * each row is stamped with batch_id, source_file and run_id
  * a load first deletes any rows of the same batch_id, so rerunning a batch
    replaces it instead of duplicating it (idempotent)
  * delete + insert + row-count check run in one transaction per table, so a
    failure leaves the previous state of that batch untouched
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pyodbc

log = logging.getLogger("load_data")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNK_ROWS = 50_000
METADATA_COLUMNS = ["batch_id", "source_file", "run_id"]


class LoadError(RuntimeError):
    pass


def read_source(path: Path, columns: list[str]) -> list[tuple]:
    """Read a CSV as text in contract column order; empty fields -> None."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8-sig")
    df = df[columns]  # the validator has already confirmed these columns exist
    return list(df.astype(object).where(df.notna(), None).itertuples(index=False, name=None))


def load_entity(conn: pyodbc.Connection, entity: str, spec: dict, data_dir: Path,
                batch_id: str, run_id: str) -> int:
    """Replace one batch of raw.<entity> with the contents of its source file. Returns rows loaded."""
    path = data_dir / spec["file"]
    columns = [c["name"] for c in spec["columns"]]
    table = f"raw.{entity}"
    try:
        source_file = path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        source_file = str(path)

    rows = read_source(path, columns)
    metadata = (batch_id, source_file, run_id)
    insert = (f"INSERT INTO {table} ({', '.join(columns + METADATA_COLUMNS)}) "
              f"VALUES ({', '.join('?' * (len(columns) + len(METADATA_COLUMNS)))})")

    cursor = conn.cursor()
    cursor.fast_executemany = True
    try:
        cursor.execute(f"DELETE FROM {table} WHERE batch_id = ?", batch_id)
        replaced = cursor.rowcount
        for start in range(0, len(rows), CHUNK_ROWS):
            cursor.executemany(insert, [r + metadata for r in rows[start:start + CHUNK_ROWS]])
        loaded = cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE batch_id = ?", batch_id).fetchval()
        if loaded != len(rows):
            raise LoadError(f"{table}: {len(rows)} rows read from {path.name} but {loaded} rows in table")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()

    log.info("  %-36s %10s rows  (replaced %s existing rows of batch '%s')",
             table, f"{loaded:,}", f"{max(replaced, 0):,}", batch_id)
    return loaded
