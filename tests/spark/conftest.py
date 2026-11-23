"""Fixtures for the Spark tests: one local SparkSession for the whole session, a fresh
lakehouse folder per test, and a helper that loads one batch through every layer.

Not collected when PySpark, Delta Lake or Java is missing (e.g. on the Windows development
machine), like the SQL tests skip without LocalDB; the pytest header says why.
Run them on Linux/WSL2 with:  python -m pytest tests/spark --confcutdir=tests/spark
"""
from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

MISSING = [name for name in ("pyspark", "delta") if importlib.util.find_spec(name) is None]
if shutil.which("java") is None:
    MISSING.append("java")

if MISSING:
    collect_ignore_glob = ["test_*.py"]

    def pytest_report_header(config):
        return f"Spark tests not collected: {', '.join(MISSING)} not installed (see requirements-spark.txt)"
else:
    from spark import run as lakehouse
    from spark.config import LakehouseConfig


@pytest.fixture(scope="session")
def spark():
    from spark.session import get_spark
    session = get_spark("retail-lakehouse-tests", local_cores="2")
    session.conf.set("spark.sql.shuffle.partitions", "1")  # tiny fixtures: one task per shuffle
    session.conf.set("spark.databricks.delta.snapshotPartitions", "1")
    yield session
    session.stop()


@pytest.fixture
def lake(tmp_path):
    return LakehouseConfig.create(str(tmp_path / "lakehouse"))


@pytest.fixture
def load(spark, lake):
    """load(folder, batch_id) runs one batch through every layer and returns its summary."""
    def _load(folder: Path, batch_id: str, config=lake) -> dict:
        return lakehouse.run_batch(spark, config, folder.as_posix(), batch_id)
    return _load
