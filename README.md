# VeriAlign — Verification Support Proxy for LLM Outputs

> **Domain:** Alignment  
> **Source Paper:** arXiv:2605.04454 — *Deployment-Relevant Alignment Cannot Be Inferred from Model-Level Evaluation Alone* (Vishwarupe, Shadbolt, Jirotka, Flechais — Oxford, May 2026)  
> **Stack:** Python 3.12, FastAPI, SQLite/Postgres, Ruff, Docker, optional: Valkey, Sentry, OpenTelemetry

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

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn verialign.proxy.main:app --reload
```

Optional features:

```bash
pip install -e ".[nli]"        # NLI hallucination detection (transformers + torch)
pip install -e ".[valkey]"     # Valkey distributed cache (shared across workers)
pip install -e ".[sentry]"     # Sentry error tracking
pip install -e ".[otel]"       # OpenTelemetry instrumentation
pip install -e ".[all]"        # Everything
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

Dashboard (in another terminal):

```bash
streamlit run verialign/dashboard/app.py
```

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
| **Admin API** | Read-only `/admin/*` endpoints: config, providers, traces, pricing |
| **Metrics** | Prometheus `/metrics` endpoint |
| **Valkey cache** | Distributed cache drop-in when `VERIALIGN_VALKEY_URL` is set |
| **Streaming** | SSE passthrough with post-stream verification and trace storage |
| **Structured output** | Detects `response_format: {type: "json_object"}` |
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
| `VERIALIGN_REDACT_TRACES` | No | true | Redact secrets from stored traces |
| `VERIALIGN_MAX_BODY_SIZE` | No | 10_485_760 | Request body size limit (bytes) |
| `VERIALIGN_REQUEST_TIMEOUT` | No | 30 | Request timeout (seconds) |
| `VERIALIGN_CORS_ORIGINS` | No | * | Allowed CORS origins |
| `VERIALIGN_VALKEY_URL` | No | — | Valkey connection string |
| `VERIALIGN_ADMIN_KEY` | No | — | Admin API key (`X-Admin-Key` header) |
| `VERIALIGN_SENTRY_DSN` | No | — | Sentry DSN for error tracking |
| `VERIALIGN_ENABLE_OTEL` | No | false | Enable OpenTelemetry instrumentation |
| `VERIALIGN_WEB_SEARCH_API_KEY` | No | — | Tavily API key for web search grounding |
| `VERIALIGN_WEB_SEARCH_PROVIDER` | No | tavily | Web search provider (tavily/serpapi) |
| `VERIALIGN_SAFETY_ENABLED` | No | true | Enable safety middleware |
| `VERIALIGN_SAFETY_PII_ENABLED` | No | true | Enable PII redaction |
| `VERIALIGN_SAFETY_JAILBREAK_ENABLED` | No | true | Enable jailbreak detection |
| `VERIALIGN_SAFETY_TOXICITY_ENABLED` | No | true | Enable toxicity filtering |

## Project Structure

```
verialign/
├── README.md
├── pyproject.toml
├── .env.example
├── verialign/
│   ├── proxy/
│   │   ├── main.py                       # FastAPI entry point
│   │   ├── admin.py                      # Admin API (/admin/*)
│   │   ├── config.py                     # Settings from env vars
│   │   ├── middleware/
│   │   │   ├── rate_limiter.py           # Token bucket rate limiter
│   │   │   ├── request_handler.py        # Validate incoming requests
│   │   │   ├── response_handler.py       # Augment responses with verification
│   │   │   ├── safety.py                 # PII redaction, jailbreak, toxicity
│   │   │   ├── metrics.py                # Prometheus /metrics
│   │   │   ├── logging_middleware.py     # Structured JSON logging
│   │   │   ├── body_size_limit.py        # Request body size guard
│   │   │   └── request_timeout.py        # Request timeout guard
│   │   └── routing/
│   │       ├── provider_router.py        # Route to OpenAI/Anthropic/local
│   │       ├── cost_model.py             # 16-model pricing table
│   │       └── fallback.py               # Provider fallback on failure
│   ├── verification/
│   │   ├── engine.py                     # Orchestrates verification pipeline
│   │   ├── claim_extractor.py            # Extract factual claims
│   │   ├── source_grounder.py            # NLI + keyword + web search grounding
│   │   ├── nli_grounder.py               # cross-encoder/nli-deberta-v3-base
│   │   ├── contradiction_detector.py     # Cross-check internal contradictions
│   │   ├── confidence_scorer.py          # Logprob + heuristic scoring
│   │   ├── checklist_generator.py        # Actionable verification checklists
│   │   ├── verification_cache.py         # Semantic cache (exact + near-match)
│   │   ├── web_grounder.py               # Tavily/SerpAPI web search
│   │   └── models.py                     # Dataclasses for verification data
│   ├── storage/
│   │   ├── models.py                     # SQLAlchemy ORM models
│   │   ├── trace_store.py                # SQLite + Postgres persistence
│   │   ├── valkey_cache.py               # Valkey distributed cache
│   │   └── metrics_store.py              # Aggregated metrics queries
│   └── dashboard/
│       └── app.py                        # Streamlit entry point
├── tests/
│   ├── test_api.py
│   ├── test_adversarial_benchmark.py
│   ├── test_benchmark_scripts.py
│   ├── test_claim_extractor.py
│   ├── test_source_grounder.py
│   ├── test_nli_grounder.py
│   ├── test_contradiction_detector.py
│   ├── test_confidence_scorer.py
│   ├── test_checklist_generator.py
│   ├── test_cost_model.py
│   ├── test_provider_router.py
│   ├── test_fallback.py
│   ├── test_rate_limiter.py
│   ├── test_request_handler.py
│   ├── test_response_handler.py
│   ├── test_trace_store.py
│   ├── test_store_switching.py
│   ├── test_verification_cache.py
│   ├── test_semantic_cache.py
│   ├── test_web_grounder.py
│   ├── test_integration.py
│   ├── test_demo_warning.py
│   ├── test_middleware_body_size_limit.py
│   ├── test_middleware_logging.py
│   ├── test_middleware_metrics.py
│   └── test_middleware_request_timeout.py
├── scripts/
│   ├── seed_data.py                      # Generate sample traces
│   └── benchmark.py                      # Latency benchmarking
├── deploy/
│   ├── Dockerfile
│   ├── Dockerfile.dashboard
│   ├── docker-compose.yml
│   └── .env.example
├── docs/
│   ├── architecture.md
│   ├── deployment.md
│   ├── paper-summary.md
│   └── interview-pitch.md
└── .github/workflows/
    └── test.yml
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/health/deep` | Deep health check (DB, config) |
| POST | `/v1/chat/completions` | Chat completion with verification |
| GET | `/traces?limit=25` | List recent traces |
| GET | `/metrics` | Prometheus metrics |
| GET | `/admin/config` | Runtime config (admin key required) |
| GET | `/admin/providers` | Configured providers (admin key required) |
| GET | `/admin/traces` | All traces (admin key required) |
| GET | `/admin/pricing` | Model pricing table (admin key required) |

## Deployment

```bash
# Demo (SQLite, one container)
docker compose -f verialign/deploy/docker-compose.yml up -d

# Production (Postgres+Valkey+Caddy TLS, 4 workers, healthchecks)
# 1) cp .env.example .env && set VERIALIGN_PROXY_API_KEY, ADMIN_API_KEY, POSTGRES_PASSWORD, DOMAIN
# 2) docker compose -f verialign/deploy/docker-compose.prod.yml up -d
#    -> Caddy auto-TLS to https://your.domain, proxy + dashboard behind it
#    -> alembic upgrade head runs on start, /health and /metrics behind allowlist

# Fly.io / Railway
flyctl launch && flyctl deploy  # or railway up
```

See `docs/deployment.md` for systemd, Caddyfile, and prod env checklist.

**Prod env checklist:** `VERIALIGN_DATABASE_URL` (or `POSTGRES_PASSWORD` for compose), `VERIALIGN_VALKEY_URL`, `VERIALIGN_REQUIRE_PROXY_AUTH=true`, `VERIALIGN_CORS_ALLOWED_ORIGINS=https://your.domain`, `VERIALIGN_RESPONSE_POLICY=warn|block`, `VERIALIGN_BLOCK_THRESHOLD=0.55`, `VERIALIGN_REDACT_TRACES=true`.

## API Notes

- Responses include a `cost` field when upstream `usage` data is available
- Admin endpoints require `X-Admin-Key` header matching `VERIALIGN_ADMIN_KEY`
- Admin is read-only (no mutation endpoints)
- `metadata.context` may be a list of strings or objects with `id` and `text`
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