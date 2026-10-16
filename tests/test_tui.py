"""Tests for the TUI data layer and the Textual console."""

import sqlite3

import pytest

from verialign.storage.trace_store import TraceStore
from verialign.tui.data import (
    extract_response_text,
    load_trace_detail,
    load_trace_rows,
    render_detail_markdown,
    verdict_for,
)
from verialign.verification.models import (
    ChecklistItem,
    Contradiction,
    SourceMatch,
    VerificationResult,
    VerifiedClaim,
)

RESPONSE_TEXT = "Paris is the capital of France."


def _seed(db_path, trust: float = 0.42) -> None:
    store = TraceStore(str(db_path), redact=False)
    claims = [
        VerifiedClaim(
            text="Paris is the capital of France.",
            status="supported",
            confidence=0.91,
            sources=[SourceMatch(source_id="doc-1", score=0.9, excerpt="Paris is the capital.")],
            claim_id="claim-0",
        ),
        VerifiedClaim(
            text="Its population is 5 million.",
            status="unsupported",
            confidence=0.2,
            sources=[],
            claim_id="claim-1",
        ),
    ]
    result = VerificationResult(
        claims=claims,
        contradictions=[
            Contradiction(claim_a="a", claim_b="b", type="numeric", confidence=0.8),
        ],
        checklist=[
            ChecklistItem(
                description="Confirm the population figure.",
                category="fact",
                priority="high",
                related_claims=["claim-1"],
            )
        ],
        trust_score=trust,
    )
    store.write_trace(
        {"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
        {
            "choices": [{"message": {"role": "assistant", "content": RESPONSE_TEXT}}],
            "usage": {"total_tokens": 42},
        },
        result,
    )


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (None, "unknown"),
        (0.1, "low"),
        (0.49, "low"),
        (0.5, "medium"),
        (0.74, "medium"),
        (0.75, "high"),
        (0.99, "high"),
    ],
)
def test_verdict_bands(score, expected) -> None:
    assert verdict_for(score) == expected


def test_load_trace_rows_reads_summary_and_trust(tmp_path) -> None:
    db = tmp_path / "traces.sqlite3"
    _seed(db, trust=0.42)

    rows = load_trace_rows(str(db))
    assert len(rows) == 1
    row = rows[0]
    assert row.model == "gpt-4"
    assert row.trust_score == pytest.approx(0.42)
    assert row.verdict == "low"
    assert row.total_claims == 2
    assert row.unsupported == 1
    assert row.contradictions == 1
    assert row.checklist_items == 1


def test_load_trace_rows_min_trust_filter(tmp_path) -> None:
    db = tmp_path / "traces.sqlite3"
    _seed(db, trust=0.42)
    assert load_trace_rows(str(db), min_trust=0.9) == []
    assert len(load_trace_rows(str(db), min_trust=0.4)) == 1


def test_load_trace_rows_missing_db(tmp_path) -> None:
    assert load_trace_rows(str(tmp_path / "absent.sqlite3")) == []


def test_validate_db_path_rejects_database_urls() -> None:
    from verialign.tui.data import validate_db_path

    with pytest.raises(ValueError, match="SQLite"):
        validate_db_path("postgresql+asyncpg://u:p@host/verialign")
    assert validate_db_path("/tmp/verialign.sqlite3") == "/tmp/verialign.sqlite3"


def test_load_trace_rows_without_traces_table(tmp_path) -> None:
    db = tmp_path / "empty.sqlite3"
    sqlite3.connect(db).close()
    assert load_trace_rows(str(db)) == []


def test_load_trace_detail_and_response_text(tmp_path) -> None:
    db = tmp_path / "traces.sqlite3"
    _seed(db)
    rows = load_trace_rows(str(db))
    detail = load_trace_detail(str(db), rows[0].id)
    assert detail is not None
    assert detail["model"] == "gpt-4"
    assert extract_response_text(detail) == RESPONSE_TEXT
    assert load_trace_detail(str(db), 9999) is None


def test_render_detail_markdown_includes_claims_and_contradictions(tmp_path) -> None:
    db = tmp_path / "traces.sqlite3"
    _seed(db)
    detail = load_trace_detail(str(db), load_trace_rows(str(db))[0].id)
    assert detail is not None

    markdown = render_detail_markdown(detail)
    assert "Trace 1" in markdown
    assert "| # | Status | Conf | Claim |" in markdown
    assert "supported" in markdown
    assert "unsupported" in markdown
    assert "numeric" in markdown
    assert "Confirm the population figure." in markdown
    assert RESPONSE_TEXT in markdown


def test_render_detail_markdown_tolerates_corrupt_verification() -> None:
    markdown = render_detail_markdown({"id": 7, "model": "demo", "verification": "not-a-dict"})
    assert "Trace 7" in markdown
    assert "unknown" in markdown


# --------------------------------------------------------------------- Textual


textual = pytest.importorskip("textual")


def test_verification_markdown_reports_bad_context() -> None:
    from verialign.tui.app import _verification_markdown

    out = _verification_markdown("hello", '{"not": "a list"}')
    assert "Verification failed" in out


async def test_tui_lists_traces_and_renders_detail(tmp_path) -> None:
    from textual.widgets import DataTable

    from verialign.tui.app import VeriAlignTUI

    db = tmp_path / "traces.sqlite3"
    _seed(db)

    app = VeriAlignTUI(str(db), limit=10, refresh=0)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one("#traces", DataTable)
        assert table.row_count == 1

        table.move_cursor(row=0)
        await pilot.pause()
        assert "Trace 1" in app.last_detail_markdown
        assert "Paris is the capital of France." in app.last_detail_markdown


async def test_tui_verify_modal_opens_and_cancels(tmp_path) -> None:
    from verialign.tui.app import VeriAlignTUI, VerifyScreen

    db = tmp_path / "traces.sqlite3"
    _seed(db)

    app = VeriAlignTUI(str(db), limit=10, refresh=0)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_verify()
        await pilot.pause()
        assert isinstance(app.screen, VerifyScreen)

        app.screen.action_cancel()
        await pilot.pause()
        assert not isinstance(app.screen, VerifyScreen)
