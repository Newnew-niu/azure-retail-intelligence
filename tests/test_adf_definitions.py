"""Static checks of the Data Factory definitions in adf/ (no Azure access needed).

They keep the cloud pipeline in step with the local code: the same entities as the
source contract, the same transform procedures in the same order as the local runner,
and no credentials or environment-specific names in the committed JSON.
"""
import json
import re
import sys
from pathlib import Path

import pytest

from ingestion import validate_files

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import adf  # noqa: E402
import run_local_pipeline  # noqa: E402

DEFINITIONS = sorted(adf.ADF_DIR.rglob("*.json"))
CONTRACT = validate_files.load_contract(validate_files.DEFAULT_CONTRACT)


def load(name: str) -> dict:
    return json.loads((adf.ADF_DIR / "pipeline" / f"{name}.json").read_text(encoding="utf-8"))


def child_parameter(name: str):
    return load("pl_olist_load_raw_and_stg")["properties"]["parameters"][name]["defaultValue"]


@pytest.mark.parametrize("path", DEFINITIONS, ids=lambda p: p.stem)
def test_definition_is_valid_json_named_after_its_file(path):
    assert json.loads(path.read_text(encoding="utf-8"))["name"] == path.stem


@pytest.mark.parametrize("path", DEFINITIONS, ids=lambda p: p.stem)
def test_no_credentials_or_hardcoded_environment_names(path):
    text = path.read_text(encoding="utf-8")
    # Properties that would hold a secret in a linked service, and SAS tokens anywhere
    assert not re.search(r'(?i)"(password|accountKey|sasUri|sasToken|servicePrincipalKey|connectionString)"\s*:', text)
    assert "sig=" not in text
    # Account and server names must come from {{PLACEHOLDERS}}, never be written into the JSON
    assert not re.search(r"[a-z0-9-]+\.(dfs\.core|database)\.windows\.net", text)


def test_every_placeholder_is_documented_in_env_example():
    documented = set(re.findall(r"^(\w+)=", (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8"), re.M))
    used = {name for p in DEFINITIONS for name in adf.PLACEHOLDER.findall(p.read_text(encoding="utf-8"))}
    assert used <= documented, f"placeholders missing from .env.example: {used - documented}"


def test_copy_entities_match_the_source_contract():
    entities = {e["entity"]: e["file"] for e in child_parameter("entities")}
    assert entities == {name: spec["file"] for name, spec in CONTRACT["entities"].items()}


def test_transform_procedures_match_the_local_runner_in_order():
    assert child_parameter("transform_procedures") == run_local_pipeline.TRANSFORM_PROCEDURES


def test_every_referenced_resource_is_defined():
    defined = {p.stem for p in DEFINITIONS}
    references = {name for p in DEFINITIONS
                  for name in re.findall(r'"referenceName":\s*"(\w+)"', p.read_text(encoding="utf-8"))}
    assert references <= defined, f"undefined references: {references - defined}"
