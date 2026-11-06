"""Settings of the serving layer, read from environment variables (or the git-ignored .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_ROW_LIMIT = 500
MAX_ROW_LIMIT = 5_000


@dataclass(frozen=True)
class Settings:
    backend: str = "duckdb"  # "duckdb" (demo export) or "azuresql" (ingestion/db.py connection)
    duckdb_path: Path = PROJECT_ROOT / "data" / "serving.duckdb"
    catalog_path: Path = PROJECT_ROOT / "serving" / "catalog.yml"
    audit_path: Path = PROJECT_ROOT / "logs" / "serving_audit.jsonl"
    api_key: str = ""  # the API refuses every request while this is empty
    query_timeout_seconds: float = 10.0
    default_row_limit: int = DEFAULT_ROW_LIMIT
    max_row_limit: int = MAX_ROW_LIMIT

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            backend=os.getenv("SERVING_BACKEND", defaults.backend),
            duckdb_path=Path(os.getenv("SERVING_DUCKDB_PATH", defaults.duckdb_path)),
            audit_path=Path(os.getenv("SERVING_AUDIT_PATH", defaults.audit_path)),
            api_key=os.getenv("SERVING_API_KEY", ""),
            query_timeout_seconds=float(os.getenv("SERVING_QUERY_TIMEOUT", defaults.query_timeout_seconds)),
        )
