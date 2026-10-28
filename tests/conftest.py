"""Shared fixtures for the SQL tests.

SQL logic tests run in a dedicated LocalDB database (retail_intelligence_test) that is
rebuilt from the version-controlled scripts at the start of the session and dropped at
the end, so they never touch the development data. They are skipped automatically when
LocalDB is not available (e.g. on a machine without SQL Server).
"""
import os
import sys
from pathlib import Path

import pyodbc
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

TEST_DATABASE = "retail_intelligence_test"


def _localdb_available() -> bool:
    from ingestion import db
    if not db.is_local():
        return False
    try:
        db.connect(database="master").close()
        return True
    except pyodbc.Error:
        return False


@pytest.fixture(scope="session")
def sql_test_db():
    """Autocommit connection to a freshly deployed, empty test database."""
    from ingestion import db
    if not _localdb_available():
        pytest.skip("LocalDB not available")

    previous = os.environ.get("SQL_DATABASE")
    os.environ["SQL_DATABASE"] = TEST_DATABASE
    import deploy_sql
    deploy_sql.ensure_local_database(reset=True)
    deploy_sql.deploy()

    conn = db.connect(autocommit=True)
    yield conn
    conn.close()

    with db.connect(database="master", autocommit=True) as master:
        master.execute(f"ALTER DATABASE [{TEST_DATABASE}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                       f"DROP DATABASE [{TEST_DATABASE}]")
    if previous is None:
        os.environ.pop("SQL_DATABASE", None)
    else:
        os.environ["SQL_DATABASE"] = previous
