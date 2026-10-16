# VeriAlign Agent Guide

## Commands
- `python3 -m pytest -x --no-header -q` — run all tests
- `python3 -m pytest tests/ -x --no-header -q -k <keyword>` — run specific test
- `python3 -m verialign serve --reload` — start proxy (same as `verialign serve`)
- `python3 -m verialign seed --db /tmp/x.sqlite3 --count 20` — sample traces for the TUI
- `python3 -m verialign tui --db /tmp/x.sqlite3` — interactive verification console
- `python3 -m ruff check verialign/ tests/ && python3 -m ruff format --check verialign/ tests/` — lint
- `git log --oneline -10` — recent commits

## Architecture
- FastAPI proxy at `verialign/proxy/main.py`; console entry point at `verialign/cli.py`
- Two deployments: proxy-only (NLI optional) and full (all features)
- Safety: PII redaction (Luhn-checked CC), jailbreak detection, toxicity guard (word-boundary)
- CORS defaults to empty origins (opt-in). Credentials only for non-wildcard origins.
- Rate limiting per IP + per API key (Valkey-backed optional)

## Gotchas
- Three `VerificationEngine(...)` constructions in `main.py` (streaming, chat, `/v1/verify`) — keep settings wiring in sync (e.g. `use_rescoring=settings.use_rescoring`)
- Response policy: `VERIALIGN_RESPONSE_POLICY` (`pass-through`/`warn`/`block`) + `VERIALIGN_BLOCK_THRESHOLD`; per-request override via `X-VeriAlign-Policy` header
- `VERIALIGN_USE_RESCORING` (default false) enables the claim-conditioned warrant-gap re-scoring; needs the `semantic` extra
- `VERIALIGN_USE_NLI` (default true) toggles the NLI detector (`cross-encoder/nli-deberta-v3-base`); cached model load; needs the `nli` extra. Set false for keyword-only / offline runs (CLI: `verialign verify --no-nli`)
- README env-var names must match `config.py` aliases — they had drifted before
- `check_limit()` return value **must** be checked — returns `(allowed, info)` tuple
- Use `build_headers(info, allowed)` to avoid double-consuming the bucket
- Admin API returns 503 (fail-closed), not 403, when no key configured
- `_runtime_config` dict was removed — `PUT /admin/config` was dead code
- `STATUS_AND_NEXT_STEPS.md` was deleted (stale)
- Toxicity uses `\bword\b` regex — no substring matching
- Credit card redaction requires valid Luhn checksum
- Circuit breakers use lazy imports in `provider_router.py` to avoid circular deps
- `send_alert()` is fire-and-forget (`asyncio.create_task()`)
- Version is single-sourced: `verialign/__init__.py` `__version__` → `pyproject.toml` `dynamic = ["version"]`
- Migrations live in `verialign/migrations/` (packaged). `alembic.ini` is a dev convenience only; `verialign migrate` builds the Alembic config in code so installed users need no ini
- `verialign tui` needs the `tui` extra (`textual`); `verialign/cli.py` imports it lazily and `verialign/tui/data.py` must stay Textual-free
- `verialign/scripts/seed_data.py` is async-driven (`asyncio.run` wrapper) and deliberately disables NLI/embeddings so seeding stays fast and offline
- `.env`, `*.sqlite3`, `*.db` must never enter the sdist/wheel — enforced by `MANIFEST.in` and the `package` CI job
