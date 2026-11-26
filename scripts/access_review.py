"""Periodic access and residency review of the Azure deployment (GOVERNANCE.md, C11, C17, G6).

Checks, with an `az login` session and the names in .env:
  1. every resource group tagged project=retail-intelligence, and every resource in it, is in a
     region listed in infra/approved_regions.txt;
  2. an enforced Allowed-locations policy (resources and resource groups) applies to the
     subscription and allows approved regions only;
  3. storage and SQL are encrypted at rest; whether SQL auditing is on;
  4. the database grants equal the approved security scripts (governance/access.py).

Writes a redacted Markdown report to reports/access_review.md and a dated copy to logs/governance/.
Exits 1 when any check fails. Read-only: it changes nothing in Azure or in the database.

    .venv/Scripts/python scripts/access_review.py            # everything
    .venv/Scripts/python scripts/access_review.py --no-db    # skip the database (it may be paused)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance import access, report, residency  # noqa: E402

PROJECT_TAG = "project=retail-intelligence"


def az(*args: str):
    exe = shutil.which("az") or shutil.which("az.cmd")
    if not exe:
        raise SystemExit("Azure CLI not found; install it and run `az login`.")
    result = subprocess.run([exe, *args, "-o", "json", "--only-show-errors"], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"az {' '.join(args[:3])} failed: {result.stderr.strip()[:300]}")
    return json.loads(result.stdout or "null")


def collect_azure(subscription_id: str):
    groups = az("group", "list", "--tag", PROJECT_TAG)
    resources = [r for g in groups for r in az("resource", "list", "-g", g["name"])]
    assignments = az("policy", "assignment", "list", "--disable-scope-strict-match",
                     "--scope", f"/subscriptions/{subscription_id}")
    storage = [az("storage", "account", "show", "--ids", r["id"]) for r in resources
               if r["type"] == "Microsoft.Storage/storageAccounts"]
    databases, audits = [], []
    for server in (r for r in resources if r["type"] == "Microsoft.Sql/servers"):
        group = server["resourceGroup"]
        audits.append({"name": server["name"], "state": az("sql", "server", "audit-policy", "show",
                                                           "-g", group, "-n", server["name"]).get("state")})
        for db in az("sql", "db", "list", "-g", group, "-s", server["name"]):
            if db["name"] == "master":
                continue
            tde = az("sql", "db", "tde", "show", "-g", group, "-s", server["name"], "-d", db["name"])
            databases.append({"name": f"{server['name']}/{db['name']}", "tde": tde.get("state")})
    return groups, resources, assignments, storage, databases, audits


def collect_database(env: dict) -> access.DatabaseState:
    server = env["AZURE_SQL_SERVER"]
    if "." not in server:
        server += ".database.windows.net"
    os.environ.update(SQL_SERVER=server, SQL_AUTH="azure_cli", SQL_DATABASE="retail_intelligence")
    from ingestion import db
    with db.connect() as conn:
        return access.read_database_state(conn.cursor())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--no-db", action="store_true", help="skip the database grant review")
    args = parser.parse_args()

    env = {**dotenv_values(ROOT / ".env"), **{k: v for k, v in os.environ.items() if k.startswith(("AZURE_", "SERVING_IDENTITY"))}}
    subscription_id = az("account", "show")["id"]
    approved = residency.approved_regions()

    groups, resources, assignments, storage, databases, audits = collect_azure(subscription_id)
    checks = [residency.check_regions(groups, resources, approved),
              residency.check_policy(assignments, approved),
              residency.check_encryption(storage, databases),
              residency.check_sql_auditing(audits)]
    notes = [f"Approved regions: {', '.join(approved)} (`infra/approved_regions.txt`)."]

    access_part = None
    if args.no_db:
        notes.append("Database grants were not reviewed in this run (`--no-db`).")
    else:
        state = collect_database(env)
        names = {"data_factory": env.get("AZURE_DATA_FACTORY") or None,
                 "serving_reader": env.get("SERVING_IDENTITY") or None}
        access_part = report.access_section(access.review(state, names))
        notes.append("The Microsoft Entra admin of the SQL server signs in as `dbo` and is reviewed "
                     "through the server's admin setting, not through database grants.")

    server_host = env.get("AZURE_SQL_SERVER") or ""
    text = report.redact(report.render(date.today().isoformat(), "resource groups tagged "
                                       f"`{PROJECT_TAG}` and the subscription's policy assignments",
                                       checks, access_part, notes),
                         subscription_id, [server_host, server_host.split(".")[0]])
    out = ROOT / "reports" / "access_review.md"
    out.write_text(text, encoding="utf-8")
    dated = ROOT / "logs" / "governance" / f"access_review_{date.today().isoformat()}.md"
    dated.parent.mkdir(parents=True, exist_ok=True)
    dated.write_text(text, encoding="utf-8")

    all_checks = checks + ([access_part[0]] if access_part else [])
    for c in all_checks:
        print(f"{c.status:4}  {c.name}: {c.detail}")
    print(f"\nReport: {out.relative_to(ROOT)} (dated copy in {dated.parent.relative_to(ROOT)})")
    return 1 if any(c.status == "FAIL" for c in all_checks) else 0


if __name__ == "__main__":
    sys.exit(main())
