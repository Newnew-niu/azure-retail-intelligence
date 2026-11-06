"""The catalog is the allow-list, so its content is part of the security design."""
import re
from pathlib import Path

import pytest

from serving.core.catalog import Catalog
from serving.core.errors import DatasetNotFound
from serving.core.service import LATEST_DQ_SQL, LATEST_RUN_SQL

SERVING = Path(__file__).resolve().parents[1]
CATALOG = Catalog.load(SERVING / "catalog.yml")
READER_SQL = (SERVING / "sql" / "serving_reader.sql").read_text(encoding="utf-8")


def test_only_mart_and_dw_are_exposed():
    assert {dataset["layer"] for dataset in CATALOG.datasets.values()} == {"mart", "dw"}


def test_every_dataset_has_the_required_metadata():
    for name, dataset in CATALOG.datasets.items():
        for field in ("description", "grain", "source", "owner", "columns"):
            assert dataset[field], f"{name} has no {field}"
        assert (SERVING.parent / dataset["source"]).is_file()


def test_every_column_has_a_type_and_a_definition():
    for dataset in CATALOG.datasets.values():
        for column in dataset["columns"]:
            assert column["type"] and column["definition"]


def test_lineage_columns_are_not_exposed():
    names = {column["name"] for dataset in CATALOG.datasets.values() for column in dataset["columns"]}
    assert not names & {"run_id", "loaded_at_utc", "updated_at_utc", "inserted_at_utc"}


def test_the_reporting_window_and_kpis_are_in_the_catalog():
    window = CATALOG.content["reporting_window"]
    assert window["first_purchase_date_key"] < window["last_purchase_date_key"] and window["note"]
    assert {"Sales orders", "Late rate", "Customers"} <= set(CATALOG.content["kpi_definitions"])


def test_unknown_dataset_raises():
    with pytest.raises(DatasetNotFound):
        CATALOG.dataset("stg.orders")


def test_reader_identity_can_read_exactly_the_catalog_datasets():
    granted = set(re.findall(r"GRANT SELECT ON (\w+\.\w+)\s+TO", READER_SQL))
    assert granted == set(CATALOG.datasets)


@pytest.mark.parametrize("table, query", [("ops.pipeline_run", LATEST_RUN_SQL), ("ops.dq_result", LATEST_DQ_SQL)])
def test_reader_identity_has_the_ops_columns_the_status_query_needs(table, query):
    granted = re.search(rf"GRANT SELECT ON {table} \((.*?)\)", READER_SQL, flags=re.S)[1]
    granted_columns = {column.strip() for column in granted.split(",")}
    selected = query.split("FROM")[0].replace("SELECT", "")
    assert {column.strip() for column in selected.split(",")} <= granted_columns
    assert "error_message" not in granted_columns
