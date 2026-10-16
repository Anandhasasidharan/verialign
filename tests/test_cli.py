"""Tests for the ``verialign`` console entry point (`verialign.cli`)."""

import json
import sqlite3

import pytest

from verialign import __version__
from verialign.cli import build_parser, main


def test_version_flag(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_help_lists_every_command(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for command in ("serve", "verify", "traces", "tui", "migrate", "seed"):
        assert command in out


def test_parser_requires_a_command() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args([])
    assert exc.value.code == 2


def test_seed_then_traces(tmp_path, capsys) -> None:
    db = tmp_path / "traces.sqlite3"
    assert main(["seed", "--db", str(db), "--count", "3"]) == 0
    assert db.exists()
    capsys.readouterr()  # discard the seed progress message

    assert main(["traces", "--db", str(db), "--limit", "5", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 3
    assert {"id", "model", "trust_score", "verdict"} <= set(payload[0])
    assert payload[0]["trust_score"] is not None


def test_traces_on_missing_db_is_empty(tmp_path, capsys) -> None:
    assert main(["traces", "--db", str(tmp_path / "nope.sqlite3"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_verify_requires_text() -> None:
    assert main(["verify"]) == 2


def test_verify_rejects_non_list_context(tmp_path, capsys) -> None:
    bad = tmp_path / "context.json"
    bad.write_text('{"not": "a list"}', encoding="utf-8")
    assert main(["verify", "--text", "hello", "--context-file", str(bad)]) == 2
    assert "context" in capsys.readouterr().err


def test_migrate_creates_schema(tmp_path) -> None:
    db = tmp_path / "migrated.sqlite3"
    assert main(["migrate", "--database-url", f"sqlite:///{db}"]) == 0
    with sqlite3.connect(db) as conn:
        tables = {
            row[0] for row in conn.execute("select name from sqlite_master where type='table'")
        }
    assert {"traces", "claims", "contradictions", "checklist_items"} <= tables


def test_serve_rejects_workers_with_reload() -> None:
    assert main(["serve", "--workers", "2", "--reload"]) == 2


@pytest.mark.parametrize("command", ["traces", "seed"])
def test_db_url_is_rejected(command, capsys) -> None:
    assert main([command, "--db", "postgresql+asyncpg://u:p@host/verialign"]) == 2
    assert "SQLite" in capsys.readouterr().err


def test_cli_import_does_not_pull_fastapi() -> None:
    """`verialign --version` must stay cheap: no web stack at import time."""
    import subprocess
    import sys

    code = (
        "import sys; import verialign.cli; "
        "print('fastapi' in sys.modules or 'uvicorn' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == "False"
