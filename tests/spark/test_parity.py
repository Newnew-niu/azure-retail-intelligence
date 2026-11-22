"""Parity on the real data: a full Spark load equals SQL Server.

Runs only when the Olist files, data/serving_baseline.json and data/serving.duckdb exist
(they are not committed: licence), like the LocalDB tests skip without LocalDB. The
complete proof, including the 9 simulated batches, is `python -m spark.parity`.
"""
import json
from decimal import Decimal

import pytest

from spark import parity
from spark import run as lakehouse
from spark.config import LakehouseConfig
from spark.gold import FACT_KEYS

pytestmark = pytest.mark.skipif(
    not ((parity.DATA / "raw" / "olist_orders_dataset.csv").exists() and parity.BASELINE.exists()
         and parity.EXPORT.exists()),
    reason="needs data/raw, data/serving_baseline.json and data/serving.duckdb")


@pytest.fixture(scope="module")
def full_load(spark, tmp_path_factory):
    config = LakehouseConfig.create(str(tmp_path_factory.mktemp("parity") / "lakehouse"))
    lakehouse.run_batch(spark, config, (parity.DATA / "raw").as_posix(), "full")
    return config


def test_golden_kpis_equal_sql_server(spark, full_load):
    baseline = json.loads(parity.BASELINE.read_text(encoding="utf-8"))
    ours = parity.kpi_values(spark, full_load)
    for name, expected in baseline.items():
        ok, how = parity.compare_kpi(name, ours[name], Decimal(expected))
        assert ok, f"{name}: Spark {ours[name]} vs SQL Server {expected} ({how})"


def test_every_fact_row_equals_sql_server(spark, full_load, tmp_path):
    pytest.importorskip("duckdb")
    exported = parity.export_facts(spark, tmp_path)
    for fact in FACT_KEYS:
        ours = parity.gold(spark, full_load, fact)
        result = parity.row_diff(ours, parity.align(exported[fact], ours))
        assert parity.diff_ok(result), (fact, result)
