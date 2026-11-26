"""Database access review: the grants approved in version control against the grants in the database.

The approved grants are read from the same SQL files that create them, so the review cannot
drift from what was deployed on purpose:
  * sql/security/adf_access.sql        -> the Data Factory managed identity
  * serving/sql/serving_reader.sql     -> the serving reader identity
Anything else a database principal holds is reported as unexpected, and anything approved
but missing is reported as missing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, order=True)
class Grant:
    principal: str
    permission: str      # SELECT, INSERT, EXECUTE, ...
    securable: str       # "SCHEMA::raw", "OBJECT::dw.dim_customer" or "DATABASE"
    column: str = ""     # column name for a column-level grant

    def describe(self) -> str:
        target = self.securable + (f" ({self.column})" if self.column else "")
        return f"{self.permission} on {target}"


@dataclass(frozen=True)
class ApprovedIdentity:
    key: str            # stable id used in the report
    label: str          # what the identity is
    env_var: str        # environment variable that holds its database user name
    grants_file: Path
    required: bool      # False: not created yet is a known gap, not a failure
    note: str = ""


IDENTITIES = (
    ApprovedIdentity("data_factory", "Data Factory managed identity", "AZURE_DATA_FACTORY",
                     ROOT / "sql" / "security" / "adf_access.sql", required=True),
    ApprovedIdentity("serving_reader", "Serving reader identity", "SERVING_IDENTITY",
                     ROOT / "serving" / "sql" / "serving_reader.sql", required=False,
                     note="Not created yet: GOVERNANCE.md gap G1."),
)

# Principals SQL Server creates in every database. dbo is the database owner (on Azure SQL,
# the Microsoft Entra admin signs in as dbo), and is reviewed through the Entra admin setting.
SYSTEM_PRINCIPALS = {"dbo", "guest", "INFORMATION_SCHEMA", "sys"}
SYSTEM_SCHEMAS = {"sys", "INFORMATION_SCHEMA"}
# Database-level permissions the public role holds by default in SQL Server and Azure SQL.
PUBLIC_DEFAULTS = {"VIEW ANY COLUMN ENCRYPTION KEY DEFINITION", "VIEW ANY COLUMN MASTER KEY DEFINITION"}

_COMMENT = re.compile(r"/\*.*?\*/|--[^\n]*", re.S)
_SCHEMA_GRANT = re.compile(r"GRANT\s+([A-Z ,]+?)\s+ON\s+SCHEMA::(\w+)", re.I)
_OBJECT_GRANT = re.compile(r"GRANT\s+([A-Z ,]+?)\s+ON\s+(?!SCHEMA::)(\w+)\.(\w+)\s*(?:\(([^)]*)\))?\s+TO", re.I)


def approved_grants(sql: str, principal: str) -> set[Grant]:
    """Every grant a security script gives, for the given database user name.

    A connecting user also holds CONNECT on the database, which CREATE USER grants implicitly.
    """
    sql = _COMMENT.sub("", sql)
    grants = {Grant(principal, "CONNECT", "DATABASE")}
    for permissions, schema in _SCHEMA_GRANT.findall(sql):
        for permission in _split(permissions):
            grants.add(Grant(principal, permission, f"SCHEMA::{schema}"))
    for permissions, schema, name, columns in _OBJECT_GRANT.findall(sql):
        targets = [c.strip() for c in columns.split(",")] if columns.strip() else [""]
        for permission in _split(permissions):
            for column in targets:
                grants.add(Grant(principal, permission, f"OBJECT::{schema}.{name}", column))
    return grants


def _split(permissions: str) -> list[str]:
    return [" ".join(p.split()).upper() for p in permissions.split(",") if p.strip()]


# One row per GRANT or DENY a database principal holds (column grants: one row per column),
# plus fixed-role memberships, read from the catalog views every user can see.
ACTUAL_GRANTS_SQL = """
SELECT pr.name AS principal, pr.type_desc, pe.state_desc, pe.permission_name, pe.class_desc,
       s.name AS schema_name, OBJECT_SCHEMA_NAME(pe.major_id) AS object_schema,
       OBJECT_NAME(pe.major_id) AS object_name, c.name AS column_name
  FROM sys.database_permissions AS pe
  JOIN sys.database_principals AS pr ON pr.principal_id = pe.grantee_principal_id
  LEFT JOIN sys.schemas AS s ON pe.class = 3 AND s.schema_id = pe.major_id
  LEFT JOIN sys.columns AS c ON pe.class = 1 AND pe.minor_id > 0
                            AND c.object_id = pe.major_id AND c.column_id = pe.minor_id
"""
PRINCIPALS_SQL = """
SELECT name, type_desc FROM sys.database_principals
 WHERE is_fixed_role = 0 AND name NOT IN ('dbo', 'guest', 'INFORMATION_SCHEMA', 'sys', 'public')
"""
ROLE_MEMBERS_SQL = """
SELECT USER_NAME(role_principal_id) AS role_name, USER_NAME(member_principal_id) AS member
  FROM sys.database_role_members
"""


@dataclass
class DatabaseState:
    grants: set[Grant]
    denies: set[Grant]
    principals: dict[str, str]          # name -> type_desc (users and custom roles)
    role_members: set[tuple[str, str]]  # (role, member)


def read_database_state(cursor) -> DatabaseState:
    grants, denies = set(), set()
    for row in cursor.execute(ACTUAL_GRANTS_SQL).fetchall():
        principal, _type, state, permission, cls, schema, obj_schema, obj_name, column = row
        if principal in SYSTEM_PRINCIPALS:
            continue
        if cls == "SCHEMA":
            securable = f"SCHEMA::{schema}"
        elif cls == "OBJECT_OR_COLUMN":
            if obj_schema in SYSTEM_SCHEMAS:
                continue  # the public role's default access to catalog views
            securable = f"OBJECT::{obj_schema}.{obj_name}"
        elif cls == "DATABASE":
            if principal == "public" and permission in PUBLIC_DEFAULTS:
                continue
            securable = "DATABASE"
        else:
            securable = cls
        grant = Grant(principal, permission, securable, column or "")
        (denies if state == "DENY" else grants).add(grant)
    principals = {name: kind for name, kind in cursor.execute(PRINCIPALS_SQL).fetchall()}
    members = {(role, member) for role, member in cursor.execute(ROLE_MEMBERS_SQL).fetchall()
               if member not in SYSTEM_PRINCIPALS}
    return DatabaseState(grants, denies, principals, members)


@dataclass
class IdentityReview:
    identity: ApprovedIdentity
    user_name: str | None       # None: the environment variable is not set
    exists: bool
    approved: set[Grant]
    actual: set[Grant]

    @property
    def unexpected(self) -> set[Grant]:
        return self.actual - self.approved

    @property
    def missing(self) -> set[Grant]:
        return self.approved - self.actual if self.exists else set()

    @property
    def status(self) -> str:
        if not self.exists:
            return "FAIL" if self.identity.required else "WARN"
        return "FAIL" if self.unexpected or self.missing else "PASS"


@dataclass
class AccessReview:
    identities: list[IdentityReview]
    unknown_principals: dict[str, set[Grant]]   # principals that no approved identity explains
    role_members: set[tuple[str, str]]          # every role membership is unexpected
    denies: set[Grant]
    public_grants: set[Grant]                   # anything the public role holds beyond the defaults

    @property
    def status(self) -> str:
        if self.unknown_principals or self.role_members or self.public_grants:
            return "FAIL"
        statuses = {r.status for r in self.identities}
        return "FAIL" if "FAIL" in statuses else "WARN" if "WARN" in statuses else "PASS"


def review(state: DatabaseState, names: dict[str, str | None]) -> AccessReview:
    """Compare the database with the approved identities. names: identity key -> database user name."""
    reviews, known = [], set()
    for identity in IDENTITIES:
        name = names.get(identity.key)
        approved = approved_grants(identity.grants_file.read_text(encoding="utf-8"), name) if name else set()
        actual = {g for g in state.grants if g.principal == name} if name else set()
        reviews.append(IdentityReview(identity, name, bool(name) and name in state.principals, approved, actual))
        if name:
            known.add(name)
    unknown: dict[str, set[Grant]] = {}
    for principal in state.principals:
        if principal not in known:
            unknown[principal] = {g for g in state.grants if g.principal == principal}
    public = {g for g in state.grants if g.principal == "public"}
    return AccessReview(reviews, unknown, state.role_members, state.denies, public)
