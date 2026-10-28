"""Database connection helper shared by the loader, the deploy script and the tests.

Settings come from environment variables (optionally from a git-ignored .env file);
see .env.example. No passwords are used:
  * SQL_AUTH=windows            -> Windows authentication (local LocalDB)
  * SQL_AUTH=azure_cli          -> Microsoft Entra ID access token from the `az login` session (Azure SQL)
  * SQL_AUTH=entra_interactive  -> Microsoft Entra ID browser sign-in by the ODBC driver (Azure SQL)
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

import pyodbc
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_DATABASE = "retail_intelligence"
SQL_COPT_SS_ACCESS_TOKEN = 1256  # ODBC pre-connect attribute that carries an Entra access token
AZURE_SQL_SCOPE = "https://database.windows.net/.default"


def database_name() -> str:
    return os.getenv("SQL_DATABASE", DEFAULT_DATABASE)


def is_local() -> bool:
    return "localdb" in os.getenv("SQL_SERVER", r"(localdb)\MSSQLLocalDB").lower()


def connection_string(database: str | None = None) -> str:
    driver = os.getenv("SQL_DRIVER", "ODBC Driver 17 for SQL Server")
    server = os.getenv("SQL_SERVER", r"(localdb)\MSSQLLocalDB")
    auth = os.getenv("SQL_AUTH", "windows")

    parts = [f"Driver={{{driver}}}", f"Server={server}"]
    if database:
        parts.append(f"Database={database}")
    if auth == "windows":
        parts.append("Trusted_Connection=yes")
    elif auth == "azure_cli":
        parts += ["Encrypt=yes", "TrustServerCertificate=no"]  # the token is passed separately
    elif auth == "entra_interactive":
        parts += ["Authentication=ActiveDirectoryInteractive", "Encrypt=yes", "TrustServerCertificate=no"]
    else:
        raise ValueError(f"Unsupported SQL_AUTH '{auth}' (expected 'windows', 'azure_cli' or 'entra_interactive')")
    return ";".join(parts) + ";"


def _access_token_attribute() -> dict[int, bytes]:
    """Entra access token in the UTF-16-LE, length-prefixed layout the ODBC driver expects."""
    from azure.identity import AzureCliCredential
    token = AzureCliCredential().get_token(AZURE_SQL_SCOPE).token.encode("utf-16-le")
    return {SQL_COPT_SS_ACCESS_TOKEN: struct.pack("<I", len(token)) + token}


def connect(database: str | None = None, autocommit: bool = False) -> pyodbc.Connection:
    """Connect to the project database (or to the server only, with database='')."""
    db = database_name() if database is None else database
    attrs = _access_token_attribute() if os.getenv("SQL_AUTH", "windows") == "azure_cli" else None
    # Serverless Azure SQL can take ~1 minute to resume from auto-pause; allow for it.
    return pyodbc.connect(connection_string(db or None), autocommit=autocommit, attrs_before=attrs, timeout=120)
