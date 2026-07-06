# VeriAlign Agent Guide

## Commands
- `python3 -m pytest -x --no-header -q` — run all tests
- `python3 -m pytest tests/ -x --no-header -q -k <keyword>` — run specific test
- `python3 -m verialign.proxy.main` — start proxy
- `git log --oneline -10` — recent commits

## Architecture
- FastAPI proxy at `verialign/proxy/main.py`
- Two deployments: proxy-only (NLI optional) and full (all features)
- Safety: PII redaction (Luhn-checked CC), jailbreak detection, toxicity guard (word-boundary)
- CORS defaults to empty origins (opt-in). Credentials only for non-wildcard origins.
- Rate limiting per IP + per API key (Valkey-backed optional)

## Gotchas
- `check_limit()` return value **must** be checked — returns `(allowed, info)` tuple
- Use `build_headers(info, allowed)` to avoid double-consuming the bucket
- Admin API returns 503 (fail-closed), not 403, when no key configured
- `_runtime_config` dict was removed — `PUT /admin/config` was dead code
- `STATUS_AND_NEXT_STEPS.md` was deleted (stale)
- Toxicity uses `\bword\b` regex — no substring matching
- Credit card redaction requires valid Luhn checksum
- Circuit breakers use lazy imports in `provider_router.py` to avoid circular deps
- `send_alert()` is fire-and-forget (`asyncio.create_task()`)
