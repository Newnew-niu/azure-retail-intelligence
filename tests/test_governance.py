"""Governance checks: approved grants, the access review, residency rules and report redaction.

The LocalDB test applies the real security scripts to users WITHOUT LOGIN and reads the grants
back through the same query the Azure review uses, so parser and database must agree.
"""
import re
import subprocess
from pathlib import Path

import pytest

from governance import access, report, residency
from governance.access import Grant

ROOT = Path(__file__).resolve().parents[1]
ADF_SQL = (ROOT / "sql" / "security" / "adf_access.sql").read_text(encoding="utf-8")
READER_SQL = (ROOT / "serving" / "sql" / "serving_reader.sql").read_text(encoding="utf-8")


# --- approved grants parsed from the security scripts ---

def test_adf_grants_are_parsed_from_the_dynamic_sql():
    grants = access.approved_grants(ADF_SQL, "adf")
    assert {g.describe() for g in grants} == {
        "CONNECT on DATABASE", "SELECT on SCHEMA::raw", "INSERT on SCHEMA::raw", "DELETE on SCHEMA::raw",
        "EXECUTE on SCHEMA::stg", "EXECUTE on SCHEMA::dw", "EXECUTE on SCHEMA::ops"}


def test_reader_grants_cover_the_catalog_and_listed_ops_columns_only():
    grants = access.approved_grants(READER_SQL, "reader")
    objects = {g.securable for g in grants if not g.column and g.securable.startswith("OBJECT::")}
    assert len(objects) == 13 and all(g.permission in {"SELECT", "CONNECT"} for g in grants)
    run_columns = {g.column for g in grants if g.securable == "OBJECT::ops.pipeline_run"}
    assert "error_message" not in run_columns and {"run_id", "status"} <= run_columns
    assert len(run_columns) == 7
    assert len({g.column for g in grants if g.securable == "OBJECT::ops.dq_result"}) == 8


def test_grants_inside_comments_are_ignored():
    sql = "/* GRANT CONTROL ON SCHEMA::dw TO x */\n-- GRANT ALTER ON SCHEMA::raw TO x\nGRANT SELECT ON mart.v TO [x];"
    assert {g.describe() for g in access.approved_grants(sql, "x")} == {"CONNECT on DATABASE",
                                                                         "SELECT on OBJECT::mart.v"}


# --- the comparison ---

def _state(grants, principals=None, members=(), denies=()):
    names = principals or {g.principal: "EXTERNAL_USER" for g in grants if g.principal != "public"}
    return access.DatabaseState(set(grants), set(denies), names, set(members))


def test_exact_grants_pass_and_a_missing_optional_identity_warns():
    state = _state(access.approved_grants(ADF_SQL, "adf-x"))
    result = access.review(state, {"data_factory": "adf-x", "serving_reader": None})
    assert [r.status for r in result.identities] == ["PASS", "WARN"]
    assert result.status == "WARN"


def test_extra_and_missing_grants_fail():
    approved = access.approved_grants(ADF_SQL, "adf-x")
    extra = Grant("adf-x", "SELECT", "SCHEMA::dw")
    dropped = Grant("adf-x", "EXECUTE", "SCHEMA::ops")
    result = access.review(_state(approved - {dropped} | {extra}), {"data_factory": "adf-x"})
    adf = result.identities[0]
    assert adf.unexpected == {extra} and adf.missing == {dropped} and result.status == "FAIL"


def test_required_identity_that_does_not_exist_fails():
    result = access.review(_state([]), {"data_factory": "adf-x"})
    assert result.identities[0].status == "FAIL"


def test_unknown_principals_role_members_and_public_grants_fail():
    base = access.approved_grants(ADF_SQL, "adf-x")
    for state in (_state(base | {Grant("someone", "SELECT", "SCHEMA::dw")}),
                  _state(base, members={("db_datareader", "adf-x")}),
                  _state(base | {Grant("public", "SELECT", "OBJECT::dw.dim_customer")})):
        assert access.review(state, {"data_factory": "adf-x"}).status == "FAIL"


@pytest.mark.usefixtures("sql_test_db")
def test_review_reads_the_real_scripts_back_from_sql_server(sql_test_db):
    """Create both identities from the committed scripts, then review the database."""
    cur = sql_test_db.cursor()
    adf = re.sub(r"/\*.*?\*/", "", ADF_SQL, flags=re.S).replace("FROM EXTERNAL PROVIDER", "WITHOUT LOGIN")
    reader = re.sub(r"/\*.*?\*/", "", READER_SQL, flags=re.S).replace("FROM EXTERNAL PROVIDER", "WITHOUT LOGIN")
    reader = reader.replace("[<SERVING_IDENTITY>]", "[gov_reader]")
    users = ["gov_adf", "gov_reader", "gov_intruder"]
    try:
        cur.execute(adf, "gov_adf")
        for batch in (b for b in reader.split("GO") if b.strip()):
            cur.execute(batch)
        names = {"data_factory": "gov_adf", "serving_reader": "gov_reader"}
        clean = access.review(access.read_database_state(cur), names)
        assert [(r.status, r.unexpected, r.missing) for r in clean.identities] == [("PASS", set(), set())] * 2
        assert clean.public_grants == set() and clean.denies == set()

        cur.execute("GRANT SELECT ON dw.fact_orders TO gov_adf")
        cur.execute("REVOKE SELECT ON ops.dq_result (status) FROM gov_reader")
        cur.execute("CREATE USER gov_intruder WITHOUT LOGIN; ALTER ROLE db_datareader ADD MEMBER gov_intruder")
        dirty = access.review(access.read_database_state(cur), names)
        adf_r, reader_r = dirty.identities
        assert adf_r.unexpected == {Grant("gov_adf", "SELECT", "OBJECT::dw.fact_orders")}
        assert reader_r.missing == {Grant("gov_reader", "SELECT", "OBJECT::ops.dq_result", "status")}
        assert "gov_intruder" in dirty.unknown_principals
        assert ("db_datareader", "gov_intruder") in dirty.role_members
        assert dirty.status == "FAIL"
    finally:
        for user in users:
            cur.execute(f"IF DATABASE_PRINCIPAL_ID('{user}') IS NOT NULL DROP USER [{user}]")


# --- residency rules ---

APPROVED = residency.approved_regions()


def test_approved_regions_are_eu_and_include_the_deployed_region():
    assert "francecentral" in APPROVED
    assert not {"uksouth", "switzerlandnorth", "norwayeast", "eastus"} & set(APPROVED)


def test_regions_check_flags_anything_outside_the_list():
    groups = [{"name": "rg", "location": "francecentral"}]
    ok = [{"name": "a", "type": "t", "location": "France Central", "resourceGroup": "rg"},
          {"name": "b", "type": "t", "location": "global", "resourceGroup": "rg"}]
    assert residency.check_regions(groups, ok, APPROVED).status == "PASS"
    bad = ok + [{"name": "c", "type": "t", "location": "eastus", "resourceGroup": "rg"}]
    assert residency.check_regions(groups, bad, APPROVED).status == "FAIL"
    assert residency.check_regions([], [], APPROVED).status == "FAIL"


def _assignment(definition, regions, mode="Default", name="eu-residency-x"):
    return {"name": name, "policyDefinitionId": f"/providers/Microsoft.Authorization/policyDefinitions/{definition}",
            "enforcementMode": mode, "parameters": {"listOfAllowedLocations": {"value": regions}}}


def test_policy_check_needs_both_enforced_eu_only_assignments():
    both = [_assignment(residency.ALLOWED_LOCATIONS, ["francecentral"]),
            _assignment(residency.ALLOWED_RG_LOCATIONS, ["francecentral", "westeurope"])]
    assert residency.check_policy(both, APPROVED).status == "PASS"
    assert residency.check_policy(both[:1], APPROVED).status == "FAIL"
    assert residency.check_policy([], APPROVED).status == "FAIL"
    leaky = [both[0], _assignment(residency.ALLOWED_RG_LOCATIONS, ["francecentral", "eastus"])]
    assert residency.check_policy(leaky, APPROVED).status == "FAIL"
    audit_only = [both[0], _assignment(residency.ALLOWED_RG_LOCATIONS, ["francecentral"], mode="DoNotEnforce")]
    assert residency.check_policy(audit_only, APPROVED).status == "FAIL"


def test_encryption_check_reads_storage_services_and_tde():
    account = {"name": "st", "allowSharedKeyAccess": False,
               "encryption": {"services": {"blob": {"enabled": True}, "file": {"enabled": True}}}}
    assert residency.check_encryption([account], [{"name": "db", "tde": "Enabled"}]).status == "PASS"
    assert residency.check_encryption([account], [{"name": "db", "tde": "Disabled"}]).status == "FAIL"


def test_infra_scripts_refuse_unapproved_regions():
    for script in ("provision.sh", "seller_api.sh"):
        text = (ROOT / "infra" / script).read_text(encoding="utf-8")
        assert "approved_regions.txt" in text and text.index("approved_regions.txt") < text.index("az group create")


@pytest.mark.parametrize("region, allowed", [("francecentral", True), ("eastus", False), ("uksouth", False)])
def test_region_guard_runs_in_bash(region, allowed):
    bash = "bash"
    try:
        subprocess.run([bash, "--version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("bash not available")
    text = (ROOT / "infra" / "provision.sh").read_text(encoding="utf-8")
    guard = text[text.index("# EU data residency"):text.index("\nfi\n", text.index("# EU data residency")) + 4]
    result = subprocess.run([bash, "-c", f'LOCATION={region}; set -- ; {guard}', "infra/provision.sh"],
                            cwd=ROOT, capture_output=True, text=True)
    assert (result.returncode == 0) == allowed


# --- report redaction ---

def test_report_redacts_subscription_suffix_and_server_name():
    sub = "00000000-1111-2222-3333-444444444444"
    suffix = report.resource_suffix(sub)
    rows = [[f"sql-retail-intel-{suffix}", "Microsoft.Sql/servers", "francecentral", "yes"]]
    check = residency.Check("Resources in approved EU regions", "PASS", "1 of 1", rows)
    text = report.render("2026-11-26", "test", [check], None, [f"subscription {sub}"])
    host = f"sql-retail-intel-{suffix}.database.windows.net"
    clean = report.redact(text + host, sub, [host])
    assert suffix not in clean and sub not in clean and "database.windows.net" not in clean
    assert "sql-retail-intel-xxxxxx" in clean
