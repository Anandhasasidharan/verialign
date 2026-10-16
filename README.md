# VeriAlign — Verification Support Proxy for LLM Outputs

> **Domain:** Alignment  
> **Source Paper:** arXiv:2605.04454 — *Deployment-Relevant Alignment Cannot Be Inferred from Model-Level Evaluation Alone* (Vishwarupe, Shadbolt, Jirotka, Flechais — Oxford, May 2026)  
> **Stack:** Python 3.11+, FastAPI, Textual (TUI), SQLite/Postgres, Ruff, Docker, optional: Valkey, Sentry, OpenTelemetry

**One-command self-host:** `docker compose -f verialign/deploy/docker-compose.yml up -d` — a small, self-hostable **inline-verification** layer you can read end-to-end in an afternoon and run in one container. No sales call, no separate eval platform to cross-reference.

A **reverse proxy** that sits between any application and any LLM API. It intercepts every request, forwards it to the model, then returns the original response **with an inline `verification` object** (claims, grounding, contradictions, confidence, trust score, checklist) — the headline feature every competitor buries in a side dashboard.

Oxford's May 2026 audit (arXiv:2605.04454) found 11 alignment benchmarks provided no user-facing verification support. VeriAlign fills that deployment-relevant gap at the **infrastructure level**.

### NLI Hallucination Detection

Uses `cross-encoder/nli-deberta-v3-base` to score each claim against context for entailment/neutral/contradiction. Lazy-loaded, no GPU required. Integrates into `SourceGrounder.ground()` — if contradiction > threshold, returns immediately with high confidence.

### Semantic Cache

In-memory cache with SHA-256 exact-match + cosine similarity near-match (using `all-MiniLM-L6-v2` embeddings). Configurable threshold (default 0.92), TTL, and LRU eviction. Automatically falls back to exact-match when embedder unavailable.

### Cost-Weighted Provider Routing

`ProviderRouter.select_provider()` picks the cheapest provider for a given model using a built-in pricing table (16 models: GPT-4o, Claude, Gemini, DeepSeek, Llama, Mistral). Falls back to first-configured when model is unknown.

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Client    │────▶│    VeriAlign     │────▶│  LLM Provider   │
│  (App/API)  │     │   (FastAPI)      │     │  (OpenAI, etc.) │
└─────────────┘     └────────┬─────────┘     └─────────────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ Verification     │
                    │ Engine           │
                    ├──────────────────┤
                     │ • Claim Extract  │
                     │ • Source Ground  │
                     │   ├─ NLI Detector│
                     │   ├─ Web Search  │
                     │   └─ Keyword     │
                     │ • Contradictions │
                     │ • Confidence     │
                     │ • Checklist      │
                     │ • Cost Tracking  │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  SQLite Storage  │
                    │  (Traces)        │
                    └──────────────────┘
```

## Install

```bash
pip install verialign          # proxy + the `verialign` CLI
pip install "verialign[tui]"   # + interactive terminal console
pipx install verialign         # if you only want the command
```

Extras: `nli` (hallucination model), `semantic` (embedding cache + re-scoring),
`valkey`, `sentry`, `otel`, `tui`, `dashboard`, `migrate`, `all`.

## Quick Start

```bash
pip install "verialign[tui]"
cp .env.example .env        # optional: set an upstream provider (demo mode works without one)
verialign seed --count 50   # optional: sample traces so the TUI has something to show
verialign serve             # http://127.0.0.1:8000
```

Verification is available through the proxy, the console, or the CLI:

| Command | What it does |
|---------|--------------|
| `verialign serve` | Run the proxy (`--host`, `--port`, `--workers`, `--reload`) |
| `verialign tui` | Interactive verification console over stored traces |
| `verialign verify --text "..."` | Verify one piece of text and print the report |
| `verialign traces --min-trust 0.5` | Trace list for scripts (`--json`) |
| `verialign migrate` | Apply database migrations (Postgres) |
| `verialign seed --count 50` | Generate demo traces |

From a source checkout:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
verialign serve --reload
```

### TUI

`verialign tui` opens a [Textual](https://textual.textualize.io/) console over the
SQLite trace store: pick a run on the left, read its claim-level verification report —
claims with status/confidence, contradictions, checklist and trust score — on the
right.

| Key | Action |
|-----|--------|
| `↑` / `↓` | Move through traces |
| `r` | Refresh the list |
| `v` | Verify your own text against context |
| `q` | Quit |

```bash
verialign tui --db ./verialign.sqlite3 --refresh 5
```

Demo request without an upstream provider:

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H "content-type: application/json" \
  -d '{
    "model": "demo",
    "messages": [{"role": "user", "content": "Summarize the project."}],
    "metadata": {
      "context": [
        {"id": "doc-1", "text": "VeriAlign is a verification support proxy for LLM outputs."}
      ]
    }
  }'
```

Dashboard (in another terminal — reads the SQLite trace store, so demo/self-host only):

```bash
pip install "verialign[dashboard]"
streamlit run verialign/dashboard/app.py
```

For a Postgres trace store, note that the TUI reads a SQLite file: point `--db` at a
SQLite export of your traces.

## Verification Response Shape

Every response includes a `verification` object:

```json
{
  "verification": {
    "claims": [
      {
        "claim_id": "claim-0",
        "text": "VeriAlign is a verification support proxy for LLM outputs.",
        "status": "supported",
        "confidence": 0.85,
        "sources": [{"source_id": "doc-1", "score": 0.8, "excerpt": "..."}]
      }
    ],
    "contradictions": [
      {"claim_a": "...", "claim_b": "...", "type": "negation", "confidence": 0.8}
    ],
    "checklist": [
      {"description": "...", "category": "security", "priority": "high"}
    ],
    "summary": {
      "total_claims": 1,
      "supported": 1,
      "unsupported": 0,
      "unclear": 0,
      "contradictions_found": 0,
      "checklist_items": 1
    }
  }
}
```

## Features

| Feature | Description |
|---------|-------------|
| **PyPI package + CLI** | `pip install verialign` → `verialign serve` / `verify` / `traces` / `tui` / `migrate` / `seed` |
| **Terminal UI** | `verialign tui` — a Textual console for browsing claim-level verification reports |
| **Provider routing** | OpenAI, Anthropic, local Ollama, any OpenAI-compatible endpoint |
| **Cost-weighted routing** | Picks cheapest provider by model (16 model pricings) with preferred override |
| **Cost tracking** | Per-request cost from upstream `usage` + model pricing table |
| **Request validation** | Full OpenAI field support: temperature, max_tokens, tools, tool_choice, response_format |
| **Claim extraction** | Regex-based factual claim extraction with meta-sentence filtering |
| **Source grounding** | NLI (entailment/neutral/contradiction) + keyword overlap + web search (Tavily/SerpAPI) |
| **NLI hallucination detection** | `cross-encoder/nli-deberta-v3-base` — lazy-loaded, ~80ms per batch |
| **Web search grounding** | Tavily API with SerpAPI fallback, 5-min in-memory cache |
| **Semantic cache** | SHA-256 exact + cosine similarity near-match (all-MiniLM-L6-v2), TTL + LRU |
| **Contradiction detection** | Negation, antonym, and numeric conflict detection |
| **Confidence scoring** | Logprob-based (when available) + heuristic fallback |
| **Checklist generation** | Action-oriented verification checklist by category |
| **Rate limiting** | Token bucket algorithm per client IP |
| **Provider fallback** | Automatic retry on 429/5xx with alternate providers |
| **Proxy auth** | Optional API-key authentication |
| **Safety middleware** | PII redaction (email/phone/SSN/credit card), jailbreak detection, toxicity filtering |
| **Trace persistence** | SQLite (sync) or Postgres (async) storage with sensitive data redaction |
| **Admin API** | `/admin/*` read endpoints (providers, traces, pricing, circuits) + `PUT /admin/pricing` to mutate pricing at runtime |
| **Response policy** | `pass-through` / `warn` / `block` driven by `trust_score` (per-request override via `X-VeriAlign-Policy` header) |
| **Verification batch API** | `POST /v1/verify` — verify arbitrary text + context without proxying an LLM call |
| **Tool-call grounding** | Grounds claims against `metadata.tool_calls` / `role=tool` messages (catches "refund was $50" after `process_refund(amount=45)`) |
| **Metrics** | Prometheus `/metrics` endpoint |
| **Valkey cache** | Distributed cache drop-in when `VERIALIGN_VALKEY_URL` is set |
| **Streaming** | SSE passthrough with post-stream verification and trace storage |
| **Structured output** | Nests the verification report under `data` for `response_format: {type: "json_object"}` requests |
| **Sentry** | Error tracking when `VERIALIGN_SENTRY_DSN` is set |
| **OpenTelemetry** | FastAPI instrumentation when `VERIALIGN_ENABLE_OTEL=true` |
| **Seed data** | Generate sample traces for demo |
| **Benchmark** | Latency + adversarial benchmark suite |

## Configuration

All via environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VERIALIGN_UPSTREAM_BASE_URL` | No | — | OpenAI-compatible API endpoint |
| `VERIALIGN_UPSTREAM_API_KEY` | No | — | API key for upstream provider |
| `VERIALIGN_ANTHROPIC_API_KEY` | No | — | Anthropic API key |
| `VERIALIGN_LOCAL_BASE_URL` | No | — | Local Ollama endpoint |
| `VERIALIGN_UPSTREAM_TIMEOUT_SECONDS` | No | 60 | Request timeout |
| `VERIALIGN_DB_PATH` | No | ./verialign.sqlite3 | SQLite database path |
| `VERIALIGN_DATABASE_URL` | No | — | Postgres DSN (async) overrides DB_PATH |
| `VERIALIGN_PROXY_API_KEY` | No | — | VeriAlign's own API key |
| `VERIALIGN_REQUIRE_PROXY_AUTH` | No | false | Enable proxy authentication |
| `VERIALIGN_RATE_LIMIT_RPM` | No | 60 | Requests per minute per client |
| `VERIALIGN_RATE_LIMIT_TPM` | No | 100000 | Tokens per minute per client |
| `VERIALIGN_RATE_LIMIT_KEY_RPM` | No | 300 | Requests/min per API key |
| `VERIALIGN_RATE_LIMIT_KEY_TPM` | No | 500000 | Tokens/min per API key |
| `VERIALIGN_REDACT_TRACES` | No | true | Redact secrets from stored traces |
| `VERIALIGN_MAX_REQUEST_BODY_SIZE` | No | 10485760 | Request body size limit (bytes) |
| `VERIALIGN_PROXY_TIMEOUT_SECONDS` | No | 120 | End-to-end proxy timeout (seconds) |
| `VERIALIGN_CORS_ALLOWED_ORIGINS` | No | `[]` | Allowed CORS origins (opt-in JSON list) |
| `VERIALIGN_RESPONSE_POLICY` | No | pass-through | `pass-through` \| `warn` \| `block` |
| `VERIALIGN_BLOCK_THRESHOLD` | No | 0.5 | trust_score below which warn/block applies |
| `VERIALIGN_USE_RESCORING` | No | false | Claim-conditioned re-scoring (needs `semantic` extra) |
| `VERIALIGN_VALKEY_URL` | No | — | Valkey connection string |
| `VERIALIGN_ADMIN_API_KEY` | No | — | Admin API key (`X-Admin-Key` header) |
| `VERIALIGN_SENTRY_DSN` | No | — | Sentry DSN for error tracking |
| `VERIALIGN_ENABLE_OTEL` | No | false | Enable OpenTelemetry instrumentation |
| `VERIALIGN_ALERT_WEBHOOK_URL` | No | — | Webhook for unsupported/contradiction alerts |
| `VERIALIGN_ALERT_SLACK_WEBHOOK_URL` | No | — | Slack webhook for alerts |
| `VERIALIGN_WEB_SEARCH_API_KEY` | No | — | Tavily API key for web search grounding |
| `VERIALIGN_WEB_SEARCH_PROVIDER` | No | tavily | Web search provider (tavily/serpapi) |
| `VERIALIGN_SAFETY_PII_REDACT_ENABLED` | No | true | Enable PII redaction |
| `VERIALIGN_SAFETY_JAILBREAK_ENABLED` | No | true | Enable jailbreak detection |
| `VERIALIGN_SAFETY_TOXICITY_ENABLED` | No | true | Enable toxicity filtering |

## Project Structure

```
VeriAlign/
├── README.md
├── ROADMAP.md
├── AGENTS.md
├── LICENSE
├── pyproject.toml
├── MANIFEST.in
├── .env.example
├── alembic.ini                           # dev convenience (migrations ship in the package)
├── verialign/
│   ├── cli.py                            # `verialign` console entry point
│   ├── __main__.py                       # `python -m verialign`
│   ├── migrations/                       # Alembic migrations (packaged)
│   ├── tui/
│   │   ├── app.py                        # Textual console (`verialign tui`)
│   │   └── data.py                       # Trace reading + Markdown rendering
│   ├── proxy/
│   │   ├── main.py                       # FastAPI entry point
│   │   ├── admin.py                      # Admin API (/admin/*)
│   │   ├── config.py                     # Settings from env vars
│   │   ├── otel_genai.py                 # GenAI semantic-convention spans
│   │   ├── middleware/
│   │   │   ├── rate_limiter.py           # Token bucket (per IP + per API key)
│   │   │   ├── request_handler.py        # Validate incoming requests
│   │   │   ├── response_handler.py       # Augment + response policy (warn/block)
│   │   │   ├── safety_middleware.py      # PII redaction, jailbreak, toxicity
│   │   │   ├── metrics_middleware.py     # Prometheus /metrics
│   │   │   ├── logging_middleware.py     # Structured JSON logging + request IDs
│   │   │   ├── body_size_limit.py        # Request body size guard
│   │   │   └── request_timeout.py        # Request timeout guard
│   │   └── routing/
│   │       ├── provider_router.py        # Route to OpenAI/Anthropic/local
│   │       ├── cost_model.py             # Model pricing table
│   │       ├── circuit_breaker.py        # Per-provider circuit breaker
│   │       └── fallback.py               # Provider fallback on failure
│   ├── verification/
│   │   ├── engine.py                     # Orchestrates verification pipeline
│   │   ├── claim_extractor.py            # Claim extraction + decomposition
│   │   ├── source_grounder.py            # NLI + keyword + web + re-scoring
│   │   ├── nli_grounder.py               # cross-encoder/nli-deberta-v3-base
│   │   ├── tool_grounder.py              # Ground claims vs tool-call records
│   │   ├── trust_scorer.py               # Aggregate trust_score
│   │   ├── contradiction_detector.py     # Cross-check internal contradictions
│   │   ├── confidence_scorer.py          # Logprob + heuristic scoring
│   │   ├── checklist_generator.py        # Actionable verification checklists
│   │   ├── alerting.py                   # Webhook/Slack alerts
│   │   ├── verification_cache.py         # Cache (exact + semantic near-match)
│   │   ├── valkey_cache.py               # Valkey-backed cache
│   │   ├── web_grounder.py               # Tavily/SerpAPI web search
│   │   └── models.py                     # Dataclasses for verification data
│   ├── storage/
│   │   ├── models.py                     # SQLAlchemy ORM models
│   │   ├── trace_store.py                # SQLite persistence
│   │   ├── async_trace_store.py          # Postgres (async) persistence
│   │   ├── store_factory.py              # Choose sync/async store
│   │   └── metrics_store.py              # Aggregated metrics queries
│   ├── scripts/
│   │   ├── benchmark_claims.py           # Claim-extraction benchmark (CI)
│   │   ├── benchmark_verification.py     # Verification + calibration (CI)
│   │   ├── audit_saboteur.py             # Overt-saboteur catch-rate audit (CI)
│   │   ├── adversarial_benchmark.py      # Adversarial claim suite
│   │   ├── benchmark.py                  # Latency benchmarking
│   │   └── seed_data.py                  # Generate sample traces
│   ├── deploy/
│   │   ├── Dockerfile
│   │   ├── Dockerfile.dashboard
│   │   ├── docker-compose.yml
│   │   ├── docker-compose.prod.yml
│   │   └── Caddyfile
│   └── dashboard/
│       └── app.py                        # Streamlit entry point
├── tests/                                # one test_<module>.py per module
├── docs/
│   ├── architecture.md
│   ├── deployment.md
│   ├── paper-summary.md
│   ├── interview-pitch.md
│   ├── VeriAlign.md                       # Product/positioning overview
│   ├── distilgpt2.md                      # LLM-as-judge experiment notes
│   ├── verification-calibration.md       # Reliability diagram + ECE
│   └── distilgpt2-test-results.md        # Ad-hoc LLM-as-judge validation
├── scripts/
│   └── audit_saboteur.py                 # Top-level audit runner (CI)
└── .github/workflows/
    ├── test.yml                          # pytest (3.11/3.12) + benchmarks + ruff + gitleaks + build
    ├── publish.yml                       # Trusted Publishing to TestPyPI + PyPI on tags
    └── deploy.yml
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/health/deep` | Deep health check (DB, config) |
| POST | `/v1/chat/completions` | Chat completion with inline verification |
| POST | `/v1/verify` | Verify arbitrary `{text, context}` without proxying |
| GET | `/traces?limit=25` | List recent traces |
| GET | `/metrics` | Prometheus metrics |
| GET | `/admin/health` | Admin health/version (admin key required) |
| GET | `/admin/providers` | Configured providers (admin key required) |
| GET | `/admin/traces` | All traces (admin key required) |
| GET | `/admin/pricing` | Model pricing table (admin key required) |
| PUT | `/admin/pricing` | Add/update a model's pricing at runtime (admin key required) |
| GET | `/admin/circuits` | Provider circuit-breaker status (admin key required) |

## Deployment

```bash
# Demo (SQLite, one container)
docker compose -f verialign/deploy/docker-compose.yml up -d

# Production (Postgres+Valkey+Caddy TLS, 4 workers, healthchecks)
# 1) cp .env.example .env && set VERIALIGN_PROXY_API_KEY, VERIALIGN_ADMIN_API_KEY, POSTGRES_PASSWORD, VERIALIGN_DOMAIN
# 2) docker compose -f verialign/deploy/docker-compose.prod.yml up -d
#    -> Caddy auto-TLS to https://your.domain, proxy + dashboard behind it
#    -> verialign migrate runs on start, /health and /metrics behind allowlist

# Fly.io / Railway
flyctl launch && flyctl deploy  # or railway up
```

See `docs/deployment.md` for systemd, Caddyfile, and prod env checklist.

**Prod env checklist:** `VERIALIGN_DATABASE_URL` (or `POSTGRES_PASSWORD` for compose), `VERIALIGN_VALKEY_URL`, `VERIALIGN_REQUIRE_PROXY_AUTH=true`, `VERIALIGN_CORS_ALLOWED_ORIGINS='["https://your.domain"]'` (JSON list — an empty list allows no cross-origin requests), `VERIALIGN_RESPONSE_POLICY=warn|block`, `VERIALIGN_BLOCK_THRESHOLD=0.55`, `VERIALIGN_REDACT_TRACES=true`.

## API Notes

- Responses include a `cost` field when upstream `usage` data is available
- Admin endpoints require `X-Admin-Key` header matching `VERIALIGN_ADMIN_API_KEY`
- Admin is read-only except `PUT /admin/pricing`. When no admin key is set, all
  `/admin/*` endpoints return `503` (disabled), not `200`
- `metadata.context` may be a list of strings or objects with `id` and `text`
- `metadata.tool_calls` (or `role: "tool"` messages) are grounded against the response
- Per-request policy override: send `X-VeriAlign-Policy` (`pass-through`/`warn`/`block`)
  and optional `X-VeriAlign-Block-Threshold`
- If no upstream provider is configured, VeriAlign uses demo mode
- Streaming (`stream=true`) is supported via SSE — post-stream verification is stored after the stream ends

## Tests

```bash
# Run all tests
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ --cov=verialign

# Run lint & format check
python -m ruff check verialign/ tests/
python -m ruff format --check verialign/ tests/
```

## Acknowledgements

- **arXiv:2605.04454 — Vishwarupe et al., Oxford, May 2026** — *Deployment-Relevant Alignment Cannot Be Inferred from Model-Level Evaluation Alone* — the paper that identified the verification gap
- **Anthropic Engineering Blog** — Proxy/containment architecture patterns
- **Bifrost AI Gateway** — Reference for production AI gateway architecture