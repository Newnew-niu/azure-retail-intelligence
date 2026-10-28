"""Database connection helper shared by the loader, the deploy script and the tests.

Settings come from environment variables (optionally from a git-ignored .env file);
see .env.example. No passwords are used:
  * SQL_AUTH=windows            -> Windows authentication (local LocalDB)
  * SQL_AUTH=entra_interactive  -> Microsoft Entra ID sign-in (Azure SQL Database)
"""
from __future__ import annotations

import os
from pathlib import Path

import pyodbc
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_DATABASE = "retail_intelligence"


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
    elif auth == "entra_interactive":
        parts += ["Authentication=ActiveDirectoryInteractive", "Encrypt=yes", "TrustServerCertificate=no"]
    else:
        raise ValueError(f"Unsupported SQL_AUTH '{auth}' (expected 'windows' or 'entra_interactive')")
    return ";".join(parts) + ";"


def connect(database: str | None = None, autocommit: bool = False) -> pyodbc.Connection:
    """Connect to the project database (or to the server only, with database='')."""
    db = database_name() if database is None else database
    return pyodbc.connect(connection_string(db or None), autocommit=autocommit)
