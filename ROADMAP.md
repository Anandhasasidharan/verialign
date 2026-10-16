# VeriAlign Roadmap

## Status: shipped

VeriAlign is a working OpenAI-compatible verification proxy that augments every
response with an inline `verification` object, and it self-hosts in one container
(`docker compose -f verialign/deploy/docker-compose.yml up -d`). The v1 MVP,
production hardening, and the v2 "verification moat" work are all complete.

### Shipped

Proxy & routing

- `POST /v1/chat/completions` with inline verification
- `POST /v1/verify` — batch verification of `{text, context}` without proxying
- OpenAI-compatible forwarding (OpenAI, Anthropic, local Ollama, any compatible endpoint)
- Cost-weighted provider routing + per-request cost tracking
- Provider fallback on 429/5xx + per-provider circuit breakers
- Demo mode when no upstream provider is configured
- SSE streaming with post-stream verification + trace storage

Verification

- Claim extraction + compound-sentence decomposition
- Source grounding: NLI (`cross-encoder/nli-deberta-v3-base`) + keyword + web search (Tavily/SerpAPI)
- Claim-conditioned re-scoring (opt-in `VERIALIGN_USE_RESCORING`, closes the NLI warrant gap)
- Tool-call grounding (claims vs `metadata.tool_calls` / `role=tool` messages)
- Contradiction detection (negation, antonym, numeric)
- Confidence scoring (logprobs + heuristic fallback)
- Aggregate `trust_score` + verification checklist
- Reliability calibration report (`docs/verification-calibration.md`)

Production hardening

- API-key auth, per-IP + per-API-key rate limiting, body-size + timeout guards
- Response policy: `pass-through` / `warn` / `block`
- Safety middleware: PII redaction (Luhn-checked cards), jailbreak, toxicity (word-boundary)
- Trace persistence (SQLite / Postgres) with secret redaction
- Admin API, Prometheus `/metrics`, structured logging, Sentry, OpenTelemetry
- Docker Compose (demo + prod with Caddy TLS) + Alembic migrations
- GitHub Actions: tests (3.11/3.12), benchmarks, ruff, gitleaks secret scan, package build check

Packaging & tooling

- PyPI distribution (`pip install verialign`) with Trusted Publishing on tags
- `verialign` CLI: `serve`, `verify`, `traces`, `tui`, `migrate`, `seed`
- Textual terminal console (`verialign tui`) for browsing claim-level reports
- Alembic migrations shipped inside the package (`verialign migrate`, no ini needed)

### Next ideas (not committed)

- Let the TUI/CLI trace reader use `VERIALIGN_DATABASE_URL` (Postgres) instead of SQLite files only
- Widen the calibration benchmark (compound claims, numeric + tool contradictions)
  and fail CI when ECE regresses > 0.05
- Expose trust scores to a downstream SLO/agent-ops sink, reusing the tool-grounding primitive
- Add more tool-call schemas for agentic frameworks as real usage appears
