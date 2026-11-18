import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from verialign.privacy import redact_pii
from verialign.proxy.config import get_settings
from verialign.verification.models import VerificationResult

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
_SENSITIVE_KEYS = {
    "authorization",
    "proxy_authorization",
    "api_key",
    "x_api_key",
    "x_admin_key",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
}


def redact_sensitive_data(obj: Any) -> Any:
    return redact_pii(_redact_credentials(obj))


def _redact_credentials(obj: Any) -> Any:
    if isinstance(obj, str):
        if obj.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(obj)
            except ValueError:
                pass
            else:
                if isinstance(parsed, (dict, list)):
                    masked = _redact_credentials(parsed)
                    return json.dumps(masked, ensure_ascii=False) if masked != parsed else obj
        redacted = obj
        for pattern, replacement in SENSITIVE_PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        return redacted
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            field = str(key).lower().replace("-", "_")
            if (
                field == "authorization"
                and isinstance(value, str)
                and value.lower().startswith("bearer ")
            ):
                result[key] = "Bearer [REDACTED]"
            else:
                result[key] = (
                    "[REDACTED]" if field in _SENSITIVE_KEYS else _redact_credentials(value)
                )
        return result
    if isinstance(obj, list):
        return [_redact_credentials(item) for item in obj]
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
        report = verification.to_dict()
        model = str(request_payload.get("model", ""))

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                insert into traces(created_at, model, request_json, response_json, verification_json)
                values (?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    redact_sensitive_data(model) if self.redact else model,
                    json.dumps(request_to_store),
                    json.dumps(response_to_store),
                    json.dumps(redact_sensitive_data(report) if self.redact else report),
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
                },
            )
        return redact_sensitive_data(traces) if self.redact else traces

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
                """,
            )
