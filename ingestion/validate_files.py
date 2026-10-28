"""Validate Olist source CSV files against the contract in config/source_schema.yml.

This is the quality gate that runs BEFORE files are uploaded to the data lake.
It answers one question: "is each file structurally what the pipeline expects?"

Checks per file:
  * file is present and readable as UTF-8 (a byte-order mark is tolerated)
  * the CSV parses (consistent number of fields per record)
  * header matches the contract (missing / unexpected columns, column order)
  * minimum row count
  * required columns contain no empty values
  * values parse as the declared type (integer, decimal, timestamp)
  * values match the declared pattern (e.g. 5-digit zip prefix)

Cross-table rules (key uniqueness, referential integrity, business rules) are
NOT checked here; they run in SQL after loading - see sql/quality/.

Usage:
    python -m ingestion.validate_files [--data-dir data/raw] [--contract config/source_schema.yml]

Exit codes: 0 = all files valid (warnings allowed), 1 = at least one ERROR,
2 = the validator itself could not run (e.g. contract not found).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

log = logging.getLogger("validate_files")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_CONTRACT = PROJECT_ROOT / "config" / "source_schema.yml"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "logs" / "validation"

ERROR = "ERROR"
WARNING = "WARNING"

# Full-match patterns for the numeric types. Kept strict on purpose: values such as
# "1,5" or "1e3" would load differently depending on locale and are rejected.
TYPE_PATTERNS = {
    "integer": r"-?\d+",
    "decimal": r"-?\d+(\.\d+)?",
}
MAX_SAMPLES = 3  # example bad values shown per failed check


@dataclass
class Issue:
    severity: str
    check: str
    message: str
    column: str | None = None
    failed_count: int | None = None
    samples: list[str] = field(default_factory=list)


@dataclass
class FileResult:
    entity: str
    file: str
    status: str = "PASSED"
    row_count: int | None = None
    sha256: str | None = None
    issues: list[Issue] = field(default_factory=list)

    def add(self, issue: Issue) -> None:
        self.issues.append(issue)
        if issue.severity == ERROR:
            self.status = "FAILED"
        elif self.status == "PASSED":
            self.status = "PASSED_WITH_WARNINGS"


def load_contract(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        contract = yaml.safe_load(f)
    if not isinstance(contract, dict) or "entities" not in contract:
        raise ValueError(f"{path}: contract must contain an 'entities' section")
    return contract


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _samples(values: pd.Series) -> list[str]:
    """First few failing values, labelled with their 1-based data record number."""
    return [f"record {idx + 1}: {val!r}" for idx, val in values.head(MAX_SAMPLES).items()]


def _check_header(result: FileResult, actual: list[str], expected: list[str]) -> None:
    missing = [c for c in expected if c not in actual]
    unexpected = [c for c in actual if c not in expected]
    if missing:
        result.add(Issue(ERROR, "header", f"missing required column(s): {', '.join(missing)}"))
    if unexpected:
        result.add(Issue(ERROR, "header",
                         f"unexpected column(s) not in the contract: {', '.join(unexpected)} "
                         "(source schema changed? update config/source_schema.yml deliberately)"))
    if not missing and not unexpected and actual != expected:
        # Loads map columns by name, so order alone does not break the pipeline.
        result.add(Issue(WARNING, "header", "columns are in a different order than the contract"))


def _check_column(result: FileResult, series: pd.Series, spec: dict, ts_format: str) -> None:
    name = spec["name"]
    present = series.dropna()

    if spec.get("required"):
        nulls = series.isna()
        if nulls.any():
            result.add(Issue(ERROR, "required", f"column '{name}' has {int(nulls.sum())} empty value(s)",
                             column=name, failed_count=int(nulls.sum()),
                             samples=[f"record {i + 1}" for i in nulls[nulls].index[:MAX_SAMPLES]]))

    col_type = spec.get("type", "string")
    if col_type in TYPE_PATTERNS:
        bad = present[~present.str.fullmatch(TYPE_PATTERNS[col_type])]
    elif col_type == "timestamp":
        parsed = pd.to_datetime(present, format=ts_format, errors="coerce")
        bad = present[parsed.isna()]
    elif col_type == "string":
        bad = present.iloc[0:0]
    else:
        raise ValueError(f"contract error: column '{name}' has unknown type '{col_type}'")
    if len(bad):
        expected = f"format {ts_format}" if col_type == "timestamp" else col_type
        result.add(Issue(ERROR, "type", f"column '{name}' has {len(bad)} value(s) that are not a valid {expected}",
                         column=name, failed_count=len(bad), samples=_samples(bad)))

    if pattern := spec.get("pattern"):
        bad = present[~present.str.fullmatch(pattern)]
        if len(bad):
            result.add(Issue(ERROR, "pattern", f"column '{name}' has {len(bad)} value(s) not matching /{pattern}/",
                             column=name, failed_count=len(bad), samples=_samples(bad)))


def validate_file(path: Path, entity: str, spec: dict, defaults: dict) -> FileResult:
    result = FileResult(entity=entity, file=spec["file"])
    if not path.is_file():
        result.add(Issue(ERROR, "presence", f"file not found: {path}"))
        return result
    result.sha256 = sha256_of(path)

    try:
        # Everything is read as text: the gate inspects the values exactly as they
        # appear in the file. Only truly empty fields count as missing ("NA" stays a value).
        df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""],
                         sep=defaults.get("delimiter", ","),
                         # utf-8-sig decodes plain UTF-8 too, and strips a BOM if present
                         encoding="utf-8-sig" if defaults.get("encoding", "utf-8") == "utf-8"
                         else defaults["encoding"])
    except UnicodeDecodeError as exc:
        result.add(Issue(ERROR, "encoding", f"file is not valid {defaults.get('encoding', 'utf-8')}: {exc}"))
        return result
    except pd.errors.EmptyDataError:
        result.add(Issue(ERROR, "parse", "file is empty (no header row)"))
        return result
    except pd.errors.ParserError as exc:
        result.add(Issue(ERROR, "parse", f"CSV could not be parsed: {exc}"))
        return result

    result.row_count = len(df)
    expected = [c["name"] for c in spec["columns"]]
    _check_header(result, list(df.columns), expected)

    min_rows = spec.get("min_rows", 1)
    if len(df) < min_rows:
        result.add(Issue(ERROR, "row_count", f"{len(df)} data row(s); at least {min_rows} expected"))

    ts_format = defaults.get("timestamp_format", "%Y-%m-%d %H:%M:%S")
    for col_spec in spec["columns"]:
        if col_spec["name"] in df.columns:
            _check_column(result, df[col_spec["name"]], col_spec, ts_format)
    return result


def validate_directory(data_dir: Path, contract: dict) -> tuple[list[FileResult], list[str]]:
    defaults = contract.get("defaults", {})
    results = [validate_file(data_dir / spec["file"], entity, spec, defaults)
               for entity, spec in contract["entities"].items()]
    known = {spec["file"] for spec in contract["entities"].values()}
    unexpected = sorted(p.name for p in data_dir.glob("*.csv") if p.name not in known) if data_dir.is_dir() else []
    return results, unexpected


def write_report(report: dict, report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"validation_{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def run(data_dir: Path, contract_path: Path, report_dir: Path | None) -> dict:
    started = datetime.now(timezone.utc)
    contract = load_contract(contract_path)
    results, unexpected = validate_directory(data_dir, contract)
    failed = [r for r in results if r.status == "FAILED"]
    report = {
        "run_id": started.strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8],
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_dir": str(data_dir),
        "contract": str(contract_path),
        "status": "FAILED" if failed else "PASSED",
        "files_checked": len(results),
        "files_failed": len(failed),
        "unexpected_files": unexpected,
        "results": [asdict(r) for r in results],
    }
    if report_dir is not None:
        report["report_path"] = str(write_report(report, report_dir))
    return report


def _print_summary(report: dict) -> None:
    for r in report["results"]:
        rows = "-" if r["row_count"] is None else f"{r['row_count']:,}"
        log.info("%-22s %-40s rows=%s", r["status"], r["file"], rows)
        for issue in r["issues"]:
            log.info("    [%s] %s: %s", issue["severity"], issue["check"], issue["message"])
            for s in issue["samples"]:
                log.info("        e.g. %s", s)
    for name in report["unexpected_files"]:
        log.info("[WARNING] unexpected file ignored (not in contract): %s", name)
    log.info("Overall: %s (%d/%d files failed)", report["status"], report["files_failed"], report["files_checked"])
    if "report_path" in report:
        log.info("Report written to %s", report["report_path"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--no-report", action="store_true", help="do not write the JSON report")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        report = run(args.data_dir, args.contract, None if args.no_report else args.report_dir)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        log.error("Validator could not run: %s", exc)
        return 2
    _print_summary(report)
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
