"""VeriAlign command-line interface.

Installed as the ``verialign`` console script (see ``[project.scripts]``) and
usable as ``python -m verialign``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from verialign import __version__


def _settings():
    from verialign.proxy.config import get_settings

    return get_settings()


def _resolve_db_path(db_path: str | None) -> str:
    from verialign.tui.data import validate_db_path

    return validate_db_path(db_path or _settings().db_path)


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, default=str))


def _console():
    """Return a rich Console when available, else None."""
    try:
        from rich.console import Console
    except ImportError:  # pragma: no cover - rich is an optional nicety
        return None
    return Console()


# --------------------------------------------------------------------------- serve


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:  # pragma: no cover - uvicorn is a core dependency
        print("uvicorn is required to serve; pip install uvicorn", file=sys.stderr)
        return 1

    if args.workers > 1 and args.reload:
        print("--reload cannot be combined with --workers > 1", file=sys.stderr)
        return 2

    uvicorn.run(
        "verialign.proxy.main:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        reload=args.reload,
    )
    return 0


# -------------------------------------------------------------------------- verify


async def _run_verification(text: str, context: list) -> dict:
    from verialign.verification.engine import VerificationEngine

    engine = VerificationEngine()
    result = await engine.verify(text, context)
    return result.to_dict()


def _load_context(path: str | None) -> list:
    if not path:
        return []
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        msg = "context file must contain a JSON list of strings or {id, text} objects"
        raise ValueError(msg)
    return data


def cmd_verify(args: argparse.Namespace) -> int:
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    elif args.text is not None:
        text = args.text
    else:
        print("provide --text or --text-file", file=sys.stderr)
        return 2

    try:
        context = _load_context(args.context_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"could not read context: {exc}", file=sys.stderr)
        return 2

    payload = asyncio.run(_run_verification(text, context))
    _print_json(payload)
    return 0


# -------------------------------------------------------------------------- traces


def cmd_traces(args: argparse.Namespace) -> int:
    from verialign.tui.data import load_trace_rows

    try:
        db_path = _resolve_db_path(args.db)
        rows = load_trace_rows(db_path, limit=args.limit, min_trust=args.min_trust)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    console = _console()
    if console is None or args.json:
        _print_json([row.to_dict() for row in rows])
        return 0

    from rich.table import Table

    table = Table(title=f"VeriAlign traces · {db_path}")
    for column in ("ID", "When", "Model", "Trust", "Claims", "Unsupported", "Contradictions"):
        table.add_column(column)
    for row in rows:
        table.add_row(
            str(row.id),
            row.created_at,
            row.model,
            "-" if row.trust_score is None else f"{row.trust_score:.3f}",
            str(row.total_claims),
            str(row.unsupported),
            str(row.contradictions),
        )
    console.print(table)
    return 0


# ----------------------------------------------------------------------------- tui


def cmd_tui(args: argparse.Namespace) -> int:
    try:
        from verialign.tui.app import run_tui
    except ImportError as exc:
        print(
            f"the TUI requires Textual; install with: pip install 'verialign[tui]' ({exc})",
            file=sys.stderr,
        )
        return 1

    try:
        db_path = _resolve_db_path(args.db)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    return run_tui(db_path=db_path, limit=args.limit, refresh=args.refresh)


# ------------------------------------------------------------------------- migrate


def cmd_migrate(args: argparse.Namespace) -> int:
    from verialign.migrations import run_migrations

    database_url = args.database_url or _settings().database_url
    try:
        run_migrations(database_url or None, revision=args.revision)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"migrations applied to {database_url or 'sqlite:///' + _settings().db_path}")
    return 0


# ---------------------------------------------------------------------------- seed


def cmd_seed(args: argparse.Namespace) -> int:
    from verialign.scripts.seed_data import create_sample_traces

    try:
        db_path = _resolve_db_path(args.db)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    create_sample_traces(args.count, db_path=db_path)
    print(f"seeded {args.count} sample traces into {db_path}")
    return 0


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verialign",
        description="Inline verification proxy for LLM outputs.",
    )
    parser.add_argument("--version", action="version", version=f"verialign {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run the OpenAI-compatible proxy")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--workers", type=int, default=1)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    p_verify = sub.add_parser("verify", help="Verify text once and print the report")
    p_verify.add_argument("--text")
    p_verify.add_argument("--text-file")
    p_verify.add_argument(
        "--context-file",
        help="JSON file with a list of strings or {id, text} objects",
    )
    p_verify.set_defaults(func=cmd_verify)

    p_traces = sub.add_parser("traces", help="List recent verification traces")
    p_traces.add_argument("--db")
    p_traces.add_argument("--limit", type=int, default=25)
    p_traces.add_argument("--min-trust", type=float, default=None)
    p_traces.add_argument("--json", action="store_true")
    p_traces.set_defaults(func=cmd_traces)

    p_tui = sub.add_parser("tui", help="Open the interactive verification console")
    p_tui.add_argument("--db")
    p_tui.add_argument("--limit", type=int, default=200)
    p_tui.add_argument(
        "--refresh", type=float, default=5.0, help="Auto-refresh seconds (0 to disable)"
    )
    p_tui.set_defaults(func=cmd_tui)

    p_migrate = sub.add_parser("migrate", help="Apply database migrations")
    p_migrate.add_argument("--database-url")
    p_migrate.add_argument("--revision", default="head")
    p_migrate.set_defaults(func=cmd_migrate)

    p_seed = sub.add_parser("seed", help="Generate sample traces for a demo")
    p_seed.add_argument("--db")
    p_seed.add_argument("--count", type=int, default=100)
    p_seed.set_defaults(func=cmd_seed)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
