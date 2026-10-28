"""Unit tests for ingestion/validate_files.py.

Each test writes a tiny CSV that breaks exactly one rule and asserts the
validator reports it with the right severity and check name.
"""
from pathlib import Path

import pytest

from ingestion import validate_files as vf

CONTRACT = {
    "defaults": {"encoding": "utf-8", "delimiter": ",", "timestamp_format": "%Y-%m-%d %H:%M:%S"},
    "entities": {
        "orders": {
            "file": "orders.csv",
            "min_rows": 1,
            "columns": [
                {"name": "order_id", "type": "string", "required": True},
                {"name": "item_count", "type": "integer", "required": True},
                {"name": "price", "type": "decimal", "required": False},
                {"name": "purchased_at", "type": "timestamp", "required": True},
                {"name": "zip", "type": "string", "required": True, "pattern": r"\d{5}"},
            ],
        }
    },
}
HEADER = "order_id,item_count,price,purchased_at,zip\n"
GOOD_ROW = "a1,2,10.50,2018-01-31 23:59:59,01037\n"


def validate(tmp_path: Path, content: str | bytes) -> vf.FileResult:
    path = tmp_path / "orders.csv"
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    results, _ = vf.validate_directory(tmp_path, CONTRACT)
    return results[0]


def checks(result: vf.FileResult, severity: str = vf.ERROR) -> set[str]:
    return {i.check for i in result.issues if i.severity == severity}


def test_valid_file_passes(tmp_path):
    result = validate(tmp_path, HEADER + GOOD_ROW + "a2,1,,2018-02-01 00:00:00,99999\n")
    assert result.status == "PASSED", result.issues
    assert result.row_count == 2
    assert result.sha256 is not None


def test_utf8_bom_is_tolerated(tmp_path):
    result = validate(tmp_path, b"\xef\xbb\xbf" + (HEADER + GOOD_ROW).encode())
    assert result.status == "PASSED", result.issues


def test_leading_zero_zip_is_preserved(tmp_path):
    # Values are read as text, so '01037' must not be turned into 1037 and then fail the pattern.
    result = validate(tmp_path, HEADER + GOOD_ROW)
    assert "pattern" not in checks(result)


def test_missing_file(tmp_path):
    results, _ = vf.validate_directory(tmp_path, CONTRACT)
    assert results[0].status == "FAILED"
    assert checks(results[0]) == {"presence"}


def test_empty_file(tmp_path):
    result = validate(tmp_path, "")
    assert result.status == "FAILED"
    assert "parse" in checks(result)


def test_header_only_fails_min_rows(tmp_path):
    result = validate(tmp_path, HEADER)
    assert checks(result) == {"row_count"}


def test_missing_column(tmp_path):
    result = validate(tmp_path, "order_id,item_count,purchased_at,zip\na1,2,2018-01-31 23:59:59,01037\n")
    assert "header" in checks(result)
    assert any("missing required column(s): price" in i.message for i in result.issues)


def test_unexpected_column(tmp_path):
    result = validate(tmp_path, HEADER.strip() + ",discount\n" + GOOD_ROW.strip() + ",5\n")
    assert any("unexpected column(s)" in i.message and "discount" in i.message for i in result.issues)


def test_column_order_is_only_a_warning(tmp_path):
    result = validate(tmp_path, "item_count,order_id,price,purchased_at,zip\n2,a1,10.50,2018-01-31 23:59:59,01037\n")
    assert result.status == "PASSED_WITH_WARNINGS"
    assert checks(result, vf.WARNING) == {"header"}


def test_required_value_missing(tmp_path):
    result = validate(tmp_path, HEADER + ",2,10.50,2018-01-31 23:59:59,01037\n")
    issue = next(i for i in result.issues if i.check == "required")
    assert issue.column == "order_id" and issue.failed_count == 1
    assert issue.samples == ["record 1"]


def test_optional_value_missing_is_fine(tmp_path):
    result = validate(tmp_path, HEADER + "a1,2,,2018-01-31 23:59:59,01037\n")
    assert result.status == "PASSED"


@pytest.mark.parametrize("bad_value", ["2.5", "two", "1e3"])
def test_bad_integer(tmp_path, bad_value):
    result = validate(tmp_path, HEADER + f"a1,{bad_value},10.50,2018-01-31 23:59:59,01037\n")
    issue = next(i for i in result.issues if i.check == "type")
    assert issue.column == "item_count"


@pytest.mark.parametrize("bad_value", ['"10,50"', "abc", "1e3"])
def test_bad_decimal(tmp_path, bad_value):
    result = validate(tmp_path, HEADER + f"a1,2,{bad_value},2018-01-31 23:59:59,01037\n")
    assert any(i.check == "type" and i.column == "price" for i in result.issues)


@pytest.mark.parametrize("bad_value", ["2018-13-01 00:00:00", "31/01/2018 10:00:00", "2018-01-31"])
def test_bad_timestamp(tmp_path, bad_value):
    result = validate(tmp_path, HEADER + f"a1,2,10.50,{bad_value},01037\n")
    issue = next(i for i in result.issues if i.check == "type")
    assert issue.column == "purchased_at"
    assert bad_value in issue.samples[0]


def test_pattern_violation_reports_record_number(tmp_path):
    # A zip that lost its leading zero (e.g. after being opened in Excel) is caught.
    result = validate(tmp_path, HEADER + GOOD_ROW + "a2,1,1.00,2018-01-31 23:59:59,1037\n")
    issue = next(i for i in result.issues if i.check == "pattern")
    assert issue.failed_count == 1
    assert issue.samples == ["record 2: '1037'"]


def test_ragged_row_fails_parse(tmp_path):
    result = validate(tmp_path, HEADER + GOOD_ROW + "a2,1,1.00,2018-01-31 23:59:59,01037,EXTRA,EXTRA\n")
    assert checks(result) == {"parse"}


def test_invalid_encoding(tmp_path):
    result = validate(tmp_path, (HEADER + "a1,2,10.50,2018-01-31 23:59:59,01037\n").encode() + "são\n".encode("latin-1"))
    assert checks(result) == {"encoding"}


def test_quoted_multiline_text_is_one_record(tmp_path):
    # Review comments in the real data contain line breaks inside quotes.
    result = validate(tmp_path, HEADER + '"a\nb",2,10.50,2018-01-31 23:59:59,01037\n')
    assert result.status == "PASSED" and result.row_count == 1


def test_unexpected_extra_file_is_reported(tmp_path):
    (tmp_path / "orders.csv").write_text(HEADER + GOOD_ROW, encoding="utf-8")
    (tmp_path / "notes.csv").write_text("x\n1\n", encoding="utf-8")
    _, unexpected = vf.validate_directory(tmp_path, CONTRACT)
    assert unexpected == ["notes.csv"]


def test_cli_exit_codes_and_report(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    contract = tmp_path / "contract.yml"
    import yaml
    contract.write_text(yaml.safe_dump(CONTRACT), encoding="utf-8")
    reports = tmp_path / "reports"

    (data / "orders.csv").write_text(HEADER + GOOD_ROW, encoding="utf-8")
    assert vf.main(["--data-dir", str(data), "--contract", str(contract), "--report-dir", str(reports)]) == 0
    assert len(list(reports.glob("validation_*.json"))) == 1

    (data / "orders.csv").write_text(HEADER + ",x,,bad,1\n", encoding="utf-8")
    assert vf.main(["--data-dir", str(data), "--contract", str(contract), "--no-report"]) == 1

    assert vf.main(["--data-dir", str(data), "--contract", str(tmp_path / "missing.yml")]) == 2
