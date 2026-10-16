"""Read-only access to stored verification traces, plus rendering helpers.

Reads the SQLite trace store (the store used by the default single-container
deployment and by ``verialign seed``). Kept free of any Textual import so the
CLI, the TUI and the tests can all use it.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

TRACES_TABLE = "traces"

# Heuristic bands for display only. The proxy's own response policy is driven by
# VERIALIGN_BLOCK_THRESHOLD; we deliberately do not re-implement policy here.
HIGH_TRUST = 0.75
MEDIUM_TRUST = 0.5


@dataclass(frozen=True)
class TraceRow:
    id: int
    created_at: str
    model: str
    trust_score: float | None
    total_claims: int
    supported: int
    unsupported: int
    contradictions: int
    checklist_items: int
    verdict: str

    def to_dict(self) -> dict:
        return asdict(self)


def verdict_for(trust_score: float | None) -> str:
    if trust_score is None:
        return "unknown"
    if trust_score >= HIGH_TRUST:
        return "high"
    if trust_score >= MEDIUM_TRUST:
        return "medium"
    return "low"


def _is_url(target: str) -> bool:
    return "://" in target


def validate_db_path(target: str) -> str:
    """Reject database URLs: this reader handles SQLite files only."""
    if _is_url(target):
        msg = (
            f"the trace reader supports SQLite files only: {target!r} looks like a "
            "database URL. Point --db at a .sqlite3 file."
        )
        raise ValueError(msg)
    return target


def _connect(db_path: str) -> sqlite3.Connection | None:
    validate_db_path(db_path)
    if not Path(db_path).exists():
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _has_traces_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "select name from sqlite_master where type='table' and name=?",
        (TRACES_TABLE,),
    ).fetchone()
    return row is not None


def _coerce_trust(verification: Any) -> float | None:
    if not isinstance(verification, dict):
        return None
    value = verification.get("trust_score")
    if value is None:
        summary = verification.get("summary")
        if isinstance(summary, dict):
            value = summary.get("trust_score")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _row_from_record(record: sqlite3.Row) -> TraceRow:
    try:
        verification = json.loads(record["verification_json"])
    except (TypeError, json.JSONDecodeError):
        verification = {}
    summary = verification.get("summary") if isinstance(verification, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    trust = _coerce_trust(verification)
    return TraceRow(
        id=record["id"],
        created_at=str(record["created_at"]),
        model=str(record["model"]),
        trust_score=trust,
        total_claims=int(summary.get("total_claims", 0) or 0),
        supported=int(summary.get("supported", 0) or 0),
        unsupported=int(summary.get("unsupported", 0) or 0),
        contradictions=int(
            summary.get("contradictions_found", 0)
            or len(verification.get("contradictions", []) or []),
        ),
        checklist_items=int(summary.get("checklist_items", 0) or 0),
        verdict=verdict_for(trust),
    )


def load_trace_rows(
    db_path: str,
    limit: int = 200,
    min_trust: float | None = None,
) -> list[TraceRow]:
    """Return recent traces (newest first), optionally filtered by trust score."""
    conn = _connect(db_path)
    if conn is None:
        return []
    try:
        if not _has_traces_table(conn):
            return []
        rows = conn.execute(
            "select id, created_at, model, verification_json from traces order by id desc limit ?",
            (max(int(limit), 1),),
        ).fetchall()
    finally:
        conn.close()

    parsed = [_row_from_record(row) for row in rows]
    if min_trust is None:
        return parsed
    return [row for row in parsed if row.trust_score is not None and row.trust_score >= min_trust]


def load_trace_detail(db_path: str, trace_id: int) -> dict | None:
    """Return the full stored record for one trace, or None when absent."""
    conn = _connect(db_path)
    if conn is None:
        return None
    try:
        if not _has_traces_table(conn):
            return None
        row = conn.execute(
            "select id, created_at, model, request_json, response_json, verification_json "
            "from traces where id = ?",
            (int(trace_id),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None

    def _maybe_json(value: Any) -> Any:
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return value

    return {
        "id": row["id"],
        "created_at": str(row["created_at"]),
        "model": str(row["model"]),
        "request": _maybe_json(row["request_json"]),
        "response": _maybe_json(row["response_json"]),
        "verification": _maybe_json(row["verification_json"]),
    }


def extract_response_text(detail: dict) -> str:
    """Pull the assistant message out of a stored OpenAI-style response."""
    response = detail.get("response")
    if isinstance(response, dict):
        choices = response.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
    return ""


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render_detail_markdown(detail: dict, title: str | None = None) -> str:
    """Render one trace (or an ad-hoc verification) as Markdown for the TUI."""
    verification = detail.get("verification")
    verification = verification if isinstance(verification, dict) else {}
    summary = verification.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    claims = verification.get("claims") or []
    contradictions = verification.get("contradictions") or []
    checklist = verification.get("checklist") or []
    trust = _coerce_trust(verification)

    heading = title or f"Trace {detail.get('id')}"

    lines: list[str] = [
        f"# {heading}",
        "",
        f"**Model:** {detail.get('model', '-')}  ",
        f"**When:** {detail.get('created_at', '-')}  ",
        f"**Trust score:** {'-' if trust is None else f'{trust:.3f}'} ({verdict_for(trust)})  ",
        f"**Claims:** {len(claims)} · **Contradictions:** {len(contradictions)}"
        f" · **Checklist:** {len(checklist)}",
        "",
        "## Response",
        "",
        extract_response_text(detail) or "_(no assistant content stored)_",
        "",
    ]

    if summary:
        lines += [
            "## Summary",
            "",
            f"supported {summary.get('supported', 0)} · "
            f"partially {summary.get('partially_supported', 0)} · "
            f"unsupported {summary.get('unsupported', 0)} · "
            f"unclear {summary.get('unclear', 0)}",
            "",
        ]

    if claims:
        lines += ["## Claims", "", "| # | Status | Conf | Claim |", "|---|--------|------|-------|"]
        for index, claim in enumerate(claims, start=1):
            if not isinstance(claim, dict):
                continue
            confidence = claim.get("confidence")
            conf_text = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "-"
            lines.append(
                f"| {index} | {claim.get('status', '-')} | {conf_text} | "
                f"{_escape_cell(str(claim.get('text', '')))} |",
            )
        lines.append("")

    if contradictions:
        lines += ["## Contradictions", ""]
        for item in contradictions:
            if isinstance(item, dict):
                lines.append(
                    f"- **{item.get('type', 'contradiction')}** "
                    f"({item.get('confidence', '-')}): "
                    f"{_escape_cell(str(item.get('claim_a', '')))} ⟷ "
                    f"{_escape_cell(str(item.get('claim_b', '')))}",
                )
        lines.append("")

    if checklist:
        lines += ["## Checklist", ""]
        for item in checklist:
            if isinstance(item, dict):
                lines.append(
                    f"- `{item.get('priority', '-')}` {_escape_cell(str(item.get('description', '')))}",
                )
        lines.append("")

    return "\n".join(lines)


TABLE_COLUMNS = (
    "ID",
    "When",
    "Model",
    "Trust",
    "Verdict",
    "Claims",
    "Unsup.",
    "Contra.",
)

__all__ = [
    "TABLE_COLUMNS",
    "TraceRow",
    "extract_response_text",
    "load_trace_detail",
    "load_trace_rows",
    "render_detail_markdown",
    "validate_db_path",
    "verdict_for",
]
