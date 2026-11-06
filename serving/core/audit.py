"""Audit log: one JSON line per query attempt, including the ones that were rejected."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()  # FastAPI runs requests on several threads

    def record(self, client: str, sql: str, status: str, duration_ms: float,
               row_count: int | None = None, reason: str | None = None) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "client": client,
            "sql": sql,
            "status": status,  # ok | rejected | error
            "reason": reason,
            "row_count": row_count,
            "duration_ms": round(duration_ms, 1),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
