import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from verialign.verification.models import VerificationResult
from verialign.proxy.config import get_settings


SENSITIVE_PATTERNS = [
    (
        re.compile(r"(?i)Authorization\s*:\s*Bearer\s+[A-Za-z0-9\-_]+"),
        "Authorization: Bearer [REDACTED]",
    ),
    (re.compile(r"(?i)Bearer\s+[A-Za-z0-9\-_]{8,}"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S+"), "[REDACTED]"),
    (re.compile(r"(?i)sk-[A-Za-z0-9]{32,}"), "[REDACTED]"),
    (re.compile(r"(?i)pk-[A-Za-z0-9]{32,}"), "[REDACTED]"),
]


def redact_sensitive_data(obj: Any) -> Any:
    if isinstance(obj, str):
        redacted = obj
        for pattern, replacement in SENSITIVE_PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        return redacted
    if isinstance(obj, dict):
        return {k: redact_sensitive_data(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_sensitive_data(item) for item in obj]
    return obj


class TraceStore:
    def __init__(self, db_path: str, redact: bool | None = None) -> None:
        self.db_path = db_path
        if redact is None:
            settings = get_settings()
            self.redact = settings.redact_traces
        else:
            self.redact = redact
        self._init_db()

    def write_trace(
        self,
        request_payload: dict,
        response_payload: dict,
        verification: VerificationResult,
    ) -> None:
        request_to_store = (
            redact_sensitive_data(request_payload) if self.redact else request_payload
        )
        response_to_store = (
            redact_sensitive_data(response_payload) if self.redact else response_payload
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                insert into traces(created_at, model, request_json, response_json, verification_json)
                values (?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    str(request_payload.get("model", "")),
                    json.dumps(request_to_store),
                    json.dumps(response_to_store),
                    json.dumps(verification.to_dict()),
                ),
            )

    def list_recent(self, limit: int = 25) -> list[dict]:
        bounded_limit = min(max(limit, 1), 100)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                select id, created_at, model, request_json, response_json, verification_json
                from traces
                order by id desc
                limit ?
                """,
                (bounded_limit,),
            ).fetchall()

        traces: list[dict] = []
        for row in rows:
            verification = json.loads(row["verification_json"])
            traces.append(
                {
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "model": row["model"],
                    "request": json.loads(row["request_json"]),
                    "response": json.loads(row["response_json"]),
                    "verification": verification,
                    "summary": verification.get("summary", {}),
                }
            )
        return traces

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute(
                """
                create table if not exists traces (
                    id integer primary key autoincrement,
                    created_at text not null,
                    model text not null,
                    request_json text not null,
                    response_json text not null,
                    verification_json text not null
                )
                """
            )
