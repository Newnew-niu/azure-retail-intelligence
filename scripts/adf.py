"""Deploy the version-controlled Data Factory definitions, and run/monitor a pipeline.

    python scripts/adf.py deploy                       # linked services -> datasets -> pipelines
    python scripts/adf.py run [--batch-id full_load]   # trigger pl_olist_master and wait for it

Definitions live in adf/ in the same layout ADF Git integration uses. Environment-specific
values are written as {{NAME}} placeholders and filled from .env at deploy time, so the
JSON in git contains no account names and no secrets (ADF uses its managed identity).
Calls the Azure Resource Manager REST API with the `az login` identity.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from azure.identity import AzureCliCredential  # noqa: E402

from ingestion import db  # noqa: E402,F401  (importing it loads .env)

ADF_DIR = PROJECT_ROOT / "adf"
API_VERSION = "2018-06-01"
# Order matters: a resource can only reference resources that already exist.
RESOURCE_FOLDERS = [("linkedService", "linkedservices"), ("dataset", "datasets"), ("pipeline", "pipelines")]
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
MASTER_PIPELINE = "pl_olist_master"
TERMINAL_STATES = {"Succeeded", "Failed", "Cancelled"}

_credential = AzureCliCredential()


def factory_url() -> str:
    names = {k: os.getenv(k) for k in ["AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_GROUP", "AZURE_DATA_FACTORY"]}
    missing = [k for k, v in names.items() if not v]
    if missing:
        raise SystemExit(f"Not set (see .env.example): {', '.join(missing)}")
    return (f"https://management.azure.com/subscriptions/{names['AZURE_SUBSCRIPTION_ID']}"
            f"/resourceGroups/{names['AZURE_RESOURCE_GROUP']}/providers/Microsoft.DataFactory"
            f"/factories/{names['AZURE_DATA_FACTORY']}")


def arm(method: str, url: str, body: dict | None = None) -> dict:
    token = _credential.get_token("https://management.azure.com/.default").token
    sep = "&" if "?" in url else "?"
    request = urllib.request.Request(
        f"{url}{sep}api-version={API_VERSION}", method=method,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {url} -> HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}") from exc
    return json.loads(payload) if payload else {}


def render(path: Path) -> dict:
    """Load a definition and fill its {{NAME}} placeholders from the environment."""
    def value(match: re.Match) -> str:
        name = match.group(1)
        if not os.getenv(name):
            raise SystemExit(f"{path.relative_to(PROJECT_ROOT)} needs {name}, which is not set")
        return os.environ[name]
    return json.loads(PLACEHOLDER.sub(value, path.read_text(encoding="utf-8")))


def deploy() -> None:
    base = factory_url()
    for folder, collection in RESOURCE_FOLDERS:
        for path in sorted((ADF_DIR / folder).glob("*.json")):
            definition = render(path)
            arm("PUT", f"{base}/{collection}/{definition['name']}", {"properties": definition["properties"]})
            print(f"  deployed {folder}/{definition['name']}")


def run(batch_id: str, poll_seconds: int = 20) -> int:
    base = factory_url()
    run_id = arm("POST", f"{base}/pipelines/{MASTER_PIPELINE}/createRun", {"batch_id": batch_id})["runId"]
    print(f"Started {MASTER_PIPELINE} batch_id={batch_id} run_id={run_id}")
    while True:
        status = arm("GET", f"{base}/pipelineruns/{run_id}")
        if status["status"] in TERMINAL_STATES:
            break
        print(f"  {datetime.now():%H:%M:%S} {status['status']}")
        time.sleep(poll_seconds)

    print(f"Pipeline {status['status']} in {status.get('durationInMs', 0) / 1000:.0f} s")
    if status.get("message"):
        print(f"  message: {status['message']}")
    print_activity_runs(base, run_id)
    return 0 if status["status"] == "Succeeded" else 1


def print_activity_runs(base: str, master_run_id: str) -> None:
    """Activity runs of the master run and of the child pipeline run it started."""
    now = datetime.now(timezone.utc)
    window = {"lastUpdatedAfter": (now - timedelta(days=1)).isoformat(), "lastUpdatedBefore": (now + timedelta(hours=1)).isoformat()}
    pending = [master_run_id]
    while pending:
        run_id = pending.pop(0)
        for a in sorted(arm("POST", f"{base}/pipelineruns/{run_id}/queryActivityruns", window)["value"],
                        key=lambda a: a["activityRunStart"]):
            out = a.get("output") or {}
            detail = ""
            if a["activityType"] == "Copy" and "rowsCopied" in out:
                detail = f"rowsRead={out.get('rowsRead')} rowsCopied={out.get('rowsCopied')} {out.get('copyDuration')} s"
            if a["status"] == "Failed":
                detail = (a.get("error") or {}).get("message", "")[:300]
            print(f"  {a['status']:<10} {a['activityType']:<26} {a['activityName']:<26} {detail}")
            if a["activityType"] == "ExecutePipeline" and out.get("pipelineRunId"):
                pending.append(out["pipelineRunId"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("deploy", help="deploy adf/ definitions to the factory")
    run_parser = commands.add_parser("run", help=f"trigger {MASTER_PIPELINE} and wait")
    run_parser.add_argument("--batch-id", default="full_load")
    args = parser.parse_args()

    if args.command == "deploy":
        deploy()
        return 0
    return run(args.batch_id)


if __name__ == "__main__":
    sys.exit(main())
