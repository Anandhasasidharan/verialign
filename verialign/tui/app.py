"""Interactive verification console (Textual TUI).

Turns the stored verification traces into something a human can read: a list of
runs on the left, the claim-level verification report on the right, and an
ad-hoc "verify this text" dialog.

``textual`` is an optional dependency (``verialign[tui]``) and is imported only
when the TUI is actually launched.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Markdown,
    Static,
    TextArea,
)

from verialign.tui.data import (
    TABLE_COLUMNS,
    load_trace_detail,
    load_trace_rows,
    render_detail_markdown,
)


async def _run_verification(text: str, context: list) -> dict:
    from verialign.verification.engine import VerificationEngine

    engine = VerificationEngine()
    result = await engine.verify(text, context)
    return result.to_dict()


def _verification_markdown(text: str, context_raw: str) -> str:
    """Blocking helper (runs in a worker thread) that verifies text."""
    try:
        context = json.loads(context_raw) if context_raw.strip() else []
        if not isinstance(context, list):
            msg = "context must be a JSON list of strings or {id, text} objects"
            raise ValueError(msg)  # noqa: TRY301
        payload = asyncio.run(_run_verification(text, context))
    except Exception as exc:  # noqa: BLE001 - surfaced to the user in the pane
        return f"# Verification failed\n\n```\n{exc}\n```\n"

    detail = {
        "id": "manual",
        "model": "manual verification",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "response": {"choices": [{"message": {"content": text}}]},
        "verification": payload,
    }
    return render_detail_markdown(detail, title="Manual verification")


class VerifyScreen(ModalScreen[tuple[str, str] | None]):
    """Collect text + optional context JSON, then dismiss with both."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    VerifyScreen { align: center middle; }
    #verify-dialog {
        width: 80%; height: 80%;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    #verify-title { text-style: bold; padding-bottom: 1; }
    #verify-text { height: 1fr; }
    #verify-context { margin-top: 1; }
    #verify-buttons { height: auto; align-horizontal: right; margin-top: 1; }
    #verify-buttons Button { margin-left: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="verify-dialog"):
            yield Static("Verify text against context", id="verify-title")
            yield TextArea(id="verify-text")
            yield Input(
                placeholder='optional context JSON, e.g. ["Paris is the capital of France."]',
                id="verify-context",
            )
            with Horizontal(id="verify-buttons"):
                yield Button("Run verification", variant="primary", id="run")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run":
            self.dismiss(
                (
                    self.query_one("#verify-text", TextArea).text,
                    self.query_one("#verify-context", Input).value,
                ),
            )
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class VeriAlignTUI(App[None]):
    """Trace browser + verification report viewer."""

    TITLE = "VeriAlign"
    SUB_TITLE = "verification console"

    BINDINGS = [
        Binding("r", "reload", "Refresh"),
        Binding("v", "verify", "Verify text"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    #body { height: 1fr; }
    #traces { width: 60%; border-right: solid $primary; }
    #detail { width: 40%; padding: 0 1; }
    #status { height: 1; background: $panel; color: $text-muted; padding: 0 1; }
    """

    def __init__(self, db_path: str, limit: int = 200, refresh: float = 5.0) -> None:
        super().__init__()
        self.db_path = db_path
        self.limit = limit
        self.refresh_seconds = refresh
        self._selected_id: int | None = None
        self.last_detail_markdown: str = ""

    # ------------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield DataTable(id="traces", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="detail"):
                yield Markdown(self._empty_message(), id="detail-body")
        yield Static(self._status_text(0), id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#traces", DataTable)
        table.add_columns(*TABLE_COLUMNS)
        self._reload()
        if self.refresh_seconds and self.refresh_seconds > 0:
            self.set_interval(self.refresh_seconds, self._reload)

    # ------------------------------------------------------------------- state

    def _empty_message(self) -> str:
        return (
            "# No trace selected\n\n"
            "Pick a run on the left to see its claims, contradictions and trust "
            "breakdown.\n\n"
            "Press `v` to verify your own text, `r` to refresh."
        )

    def _status_text(self, row_count: int) -> str:
        return f"db: {self.db_path}   ·   traces: {row_count}   ·   r refresh · v verify · q quit"

    def _reload(self) -> None:
        try:
            rows = load_trace_rows(self.db_path, limit=self.limit)
        except ValueError as exc:
            self.query_one("#status", Static).update(str(exc))
            self._show_detail(f"# Cannot read the trace store\n\n```\n{exc}\n```\n")
            return
        table = self.query_one("#traces", DataTable)
        table.clear()
        for row in rows:
            table.add_row(
                str(row.id),
                row.created_at.replace("T", " ")[:19],
                row.model,
                "-" if row.trust_score is None else f"{row.trust_score:.3f}",
                row.verdict,
                str(row.total_claims),
                str(row.unsupported),
                str(row.contradictions),
                key=str(row.id),
            )
        self.query_one("#status", Static).update(self._status_text(len(rows)))
        self._restore_selection(table)

    def _restore_selection(self, table: DataTable) -> None:
        if self._selected_id is None or table.row_count == 0:
            return
        try:
            index = table.get_row_index(str(self._selected_id))
        except Exception:  # noqa: BLE001 - row no longer present
            return
        table.move_cursor(row=index)

    # ---------------------------------------------------------------- handlers

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        key = event.row_key.value if event.row_key is not None else None
        if key is None:
            return
        try:
            trace_id = int(key)
        except (TypeError, ValueError):
            return
        self._selected_id = trace_id
        detail = load_trace_detail(self.db_path, trace_id)
        if detail is None:
            markdown = f"# Trace {trace_id}\n\n_No longer present._"
        else:
            markdown = render_detail_markdown(detail)
        self.last_detail_markdown = markdown
        self.query_one("#detail-body", Markdown).update(markdown)

    def action_reload(self) -> None:
        self._reload()

    def action_verify(self) -> None:
        self.push_screen(VerifyScreen(), self._on_verify_dismissed)

    def _on_verify_dismissed(self, result: tuple[str, str] | None) -> None:
        if not result:
            return
        text, context_raw = result
        if not text.strip():
            return
        self.query_one("#detail-body", Markdown).update(
            "# Manual verification\n\n_Running verification — the first run loads the "
            "NLI model, which can take a while…_",
        )
        self._verify_worker(text, context_raw)

    @work(thread=True, exclusive=True, group="verify")
    def _verify_worker(self, text: str, context_raw: str) -> None:
        markdown = _verification_markdown(text, context_raw)
        self.call_from_thread(self._show_detail, markdown)

    def _show_detail(self, markdown: str) -> None:
        self.last_detail_markdown = markdown
        self.query_one("#detail-body", Markdown).update(markdown)


def run_tui(db_path: str, limit: int = 200, refresh: float = 5.0) -> int:
    """Entry point used by ``verialign tui``."""
    VeriAlignTUI(db_path, limit=limit, refresh=refresh).run()
    return 0


__all__ = ["VeriAlignTUI", "VerifyScreen", "run_tui"]
