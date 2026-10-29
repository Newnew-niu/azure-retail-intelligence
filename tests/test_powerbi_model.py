"""Static checks of the Power BI semantic model definition (no Power BI needed).

Every DAX reference must resolve to a defined column or measure, every imported column must
exist in the dw tables, and every relationship must join defined columns. These catch the
mistakes that otherwise only show up as a broken visual after a refresh.
"""
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import build_powerbi_model as model  # noqa: E402

DW_SQL = (PROJECT_ROOT / "sql" / "dw" / "01_tables.sql").read_text(encoding="utf-8")
MEASURE_NAMES = {m[1] for m in model.MEASURES}
COLUMN_NAMES = {t: {c for c, _, _ in cols} | {c for c, _, _ in model.CALCULATED_COLUMNS.get(t, [])}
                for t, cols in model.COLUMNS.items()}


def dw_columns(table: str) -> set[str]:
    body = re.search(rf"CREATE TABLE dw\.{table} \((.*?)\n\);", DW_SQL, re.S).group(1)
    return {m.group(1).strip("[]") for m in re.finditer(r"^\s+(\[?\w+\]?)\s+[A-Z]", body, re.M)} - {"CONSTRAINT"}


@pytest.mark.parametrize("table", list(model.COLUMNS))
def test_imported_columns_exist_in_dw(table):
    missing = {c for c, _, _ in model.COLUMNS[table]} - dw_columns(table)
    assert not missing, f"dw.{table} has no column(s) {missing}"


@pytest.mark.parametrize("measure", model.MEASURES, ids=lambda m: m[1])
def test_measure_references_resolve(measure):
    table, name, dax, *_ = measure
    variables = set(re.findall(r'"(@\w+)"', dax))
    for ref_table, ref_column in re.findall(r"(\w+)\[([^\]]+)\]", dax):
        assert ref_column in COLUMN_NAMES.get(ref_table, set()), f"{name}: {ref_table}[{ref_column}] not defined"
    for ref in re.findall(r"(?<![\w\]])\[([^\]]+)\]", dax):
        assert ref in MEASURE_NAMES or ref in variables, f"{name}: measure [{ref}] not defined"


def test_measure_names_are_unique():
    names = [m[1] for m in model.MEASURES]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("relationship", model.RELATIONSHIPS, ids=lambda r: f"{r[0]}.{r[1]}")
def test_relationship_columns_exist(relationship):
    from_table, from_col, to_table, to_col = relationship
    assert from_col in COLUMN_NAMES[from_table] and to_col in COLUMN_NAMES[to_table]
    assert to_table.startswith("dim_") and from_table.startswith("fact_")  # dimensions filter facts only


def test_facts_are_not_related_to_each_other():
    assert not [r for r in model.RELATIONSHIPS if r[2].startswith("fact_")]


def test_build_writes_one_file_per_table(tmp_path):
    model.build(tmp_path, "server", "db")
    written = {p.stem for p in (tmp_path / "definition" / "tables").glob("*.tmdl")}
    assert written == set(model.COLUMNS)
    assert "\t" in (tmp_path / "definition" / "tables" / "fact_orders.tmdl").read_text(encoding="utf-8")


def report_fields(tmp_path):
    import build_powerbi_report as report
    (tmp_path / "definition").mkdir()
    (tmp_path / "definition" / "report.json").write_text("{}", encoding="utf-8")
    report.build(tmp_path)
    text = "\n".join(p.read_text(encoding="utf-8") for p in (tmp_path / "definition" / "pages").rglob("visual.json"))
    return re.findall(r'"(Measure|Column)": \{\s*"Expression": \{\s*"SourceRef": \{\s*"Entity": "(\w+)"\s*\}\s*\},\s*'
                      r'"Property": "([^"]+)"', text)


def test_every_report_field_exists_in_the_model(tmp_path):
    measure_tables = {m[1]: m[0] for m in model.MEASURES}
    fields = report_fields(tmp_path)
    assert fields, "no fields found in the generated report"
    for kind, table, prop in fields:
        if kind == "Measure":
            assert measure_tables.get(prop) == table, f"measure [{prop}] is not defined on {table}"
        else:
            assert prop in COLUMN_NAMES[table], f"column {table}[{prop}] not in the model"
