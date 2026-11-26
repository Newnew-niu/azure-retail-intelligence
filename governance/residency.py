"""EU data residency checks over what Azure reports: resource regions, the location policy, encryption.

Every function here takes plain JSON (as returned by the Azure CLI), so the rules are tested
without Azure; scripts/access_review.py does the collecting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPROVED_REGIONS_FILE = ROOT / "infra" / "approved_regions.txt"

# Built-in Azure Policy definitions (the same IDs in every tenant).
ALLOWED_LOCATIONS = "e56962a6-4747-49cd-b67b-bf8b01975c4c"
ALLOWED_RG_LOCATIONS = "e765b5de-1225-4ba3-bd56-1ac6695af988"
# Location of resources that have no region; the built-in policy exempts them as well.
NON_REGIONAL = {"global"}


def approved_regions(path: Path = APPROVED_REGIONS_FILE) -> list[str]:
    lines = (line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line]


def normalise(location: str | None) -> str:
    """'France Central' and 'francecentral' are the same region."""
    return (location or "").replace(" ", "").lower()


@dataclass
class Check:
    name: str
    status: str            # PASS, WARN or FAIL
    detail: str
    rows: list[list[str]] = field(default_factory=list)


def check_regions(groups: list[dict], resources: list[dict], approved: list[str]) -> Check:
    allowed = {normalise(r) for r in approved} | NON_REGIONAL
    rows, outside = [], 0
    for group in sorted(groups, key=lambda g: g["name"]):
        ok = normalise(group["location"]) in allowed
        outside += not ok
        rows.append([group["name"], "resource group", group["location"], "yes" if ok else "**NO**"])
    for res in sorted(resources, key=lambda r: (r.get("resourceGroup", ""), r["type"], r["name"])):
        ok = normalise(res["location"]) in allowed
        outside += not ok
        rows.append([res["name"], res["type"], res["location"], "yes" if ok else "**NO**"])
    total = len(groups) + len(resources)
    if not total:
        return Check("Resources in approved EU regions", "FAIL", "No project resources found to check.")
    status = "FAIL" if outside else "PASS"
    return Check("Resources in approved EU regions", status,
                 f"{total - outside} of {total} in an approved region.", rows)


def _allowed_list(assignment: dict) -> list[str]:
    params = assignment.get("parameters") or {}
    for key in ("listOfAllowedLocations", "listofallowedlocations"):
        if key in params:
            value = params[key]
            return list(value.get("value", []) if isinstance(value, dict) else value)
    return []


def check_policy(assignments: list[dict], approved: list[str]) -> Check:
    """An enforced Allowed-locations assignment must exist and allow approved regions only."""
    allowed = {normalise(r) for r in approved}
    rows, good, bad = [], [], []
    for a in assignments:
        definition = (a.get("policyDefinitionId") or "").lower()
        kind = ("resources" if definition.endswith(ALLOWED_LOCATIONS)
                else "resource groups" if definition.endswith(ALLOWED_RG_LOCATIONS) else None)
        if kind is None:
            continue
        regions = sorted(normalise(r) for r in _allowed_list(a))
        enforced = (a.get("enforcementMode") or "Default") == "Default"
        extra = [r for r in regions if r not in allowed]
        owned = a.get("name", "").startswith("eu-residency")
        rows.append([a.get("displayName") or a.get("name", ""), kind, "this project" if owned else "inherited",
                     "yes" if enforced else "no (audit only)", ", ".join(regions) or "(none)",
                     ", ".join(extra) or "–"])
        (good if enforced and not extra and regions else bad).append(kind)
    if {"resources", "resource groups"} <= set(good):
        return Check("Allowed-locations policy", "PASS",
                     "Enforced for resources and resource groups; every allowed region is approved.", rows)
    if not rows:
        return Check("Allowed-locations policy", "FAIL", "No Allowed-locations policy applies to the subscription.")
    missing = sorted({"resources", "resource groups"} - set(good))
    return Check("Allowed-locations policy", "FAIL",
                 f"No enforced EU-only assignment for: {', '.join(missing)}.", rows)


def check_encryption(storage_accounts: list[dict], databases: list[dict]) -> Check:
    """Encryption at rest is a platform default; this makes it evidence instead of an assumption.

    databases: [{"name": ..., "tde": "Enabled" | ...}]
    """
    rows, failures = [], 0
    for acct in sorted(storage_accounts, key=lambda a: a["name"]):
        services = (acct.get("encryption") or {}).get("services") or {}
        for service in ("blob", "file"):
            enabled = bool((services.get(service) or {}).get("enabled"))
            failures += not enabled
            rows.append([acct["name"], f"storage {service} encryption", "on" if enabled else "**off**"])
        rows.append([acct["name"], "shared key access",
                     "disabled" if acct.get("allowSharedKeyAccess") is False else "enabled (G9)"])
    for db in databases:
        enabled = db.get("tde") == "Enabled"
        failures += not enabled
        rows.append([db["name"], "transparent data encryption", "on" if enabled else f"**{db.get('tde')}**"])
    if not rows:
        return Check("Encryption at rest", "FAIL", "Nothing found to check.")
    return Check("Encryption at rest", "FAIL" if failures else "PASS",
                 f"{failures} store(s) without encryption at rest." if failures else
                 "Every storage service and database is encrypted at rest.", rows)


def check_sql_auditing(audit_states: list[dict]) -> Check:
    """audit_states: [{"name": server, "state": "Enabled" | "Disabled"}]. Known gap G7 when off."""
    rows = [[a["name"], a.get("state") or "unknown"] for a in audit_states]
    off = [a for a in audit_states if a.get("state") != "Enabled"]
    return Check("Azure SQL auditing", "WARN" if off else "PASS",
                 "Auditing is off: known gap G7." if off else "Auditing is on.", rows)
