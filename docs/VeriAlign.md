# VeriAlign — Verification Support Proxy for LLM Outputs

> **Domain:** Alignment  
> **Source Paper:** arXiv:2605.04454 — *Deployment-Relevant Alignment Cannot Be Inferred from Model-Level Evaluation Alone* (Vishwarupe, Shadbolt, Jirotka, Flechais — Oxford, May 2026)  
> **Build Time:** 4 weeks  
> **GPU:** None required  
> **Stack:** Python, FastAPI, SQLite, Streamlit, Docker

---

## 1. What It Is

A **reverse proxy** that sits between any application and any LLM API. It intercepts every request, forwards it to the model, then augments the response with verification information before returning it to the user.

The paper **arXiv:2605.04454** (*Deployment-Relevant Alignment Cannot Be Inferred from Model-Level Evaluation Alone*, Vishwarupe et al., Oxford, May 2026) audited 11 alignment benchmarks and found user-facing verification support absent across the set. The authors argue the gap cannot be closed at the model level alone and requires infrastructure-level scaffolding.

> Short anchor (<15 words): *"verification support was absent"* — paraphrase of the audit finding.

This project fills that gap at the **infrastructure level** — a tool that works with any model, any provider.

---

## 2. Project Structure

```
verialign/
├── README.md                          # Project overview, problem, architecture, deploy
├── docs/
│   ├── architecture.md                # Full architecture diagram + component descriptions
│   ├── deployment.md                  # Docker, CI/CD, free tier hosting instructions
│   ├── paper-summary.md               # Summary of arXiv:2605.04454 with key quotes
│   └── interview-pitch.md             # The 30-second answer for hiring managers
├── proxy/
│   ├── __init__.py
│   ├── main.py                        # FastAPI app entry point
│   ├── config.py                      # Provider configs, rate limits, thresholds
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── rate_limiter.py            # Token bucket rate limiter
│   │   ├── request_handler.py         # Intercept + validate incoming request
│   │   └── response_handler.py        # Augment response with verification data
│   ├── routing/
│   │   ├── __init__.py
│   │   ├── provider_router.py         # Route to OpenAI / Anthropic / local
│   │   └── fallback.py                # Provider fallback on failure
│   └── verification/
│       ├── __init__.py
│       ├── claim_extractor.py         # Parse factual assertions from response text
│       ├── source_grounder.py         # Match claims to RAG context chunks
│       ├── confidence_scorer.py       # Logit-based confidence (no model access needed)
│       ├── contradiction_detector.py  # Cross-check statements for "X vs not X"
│       └── checklist_generator.py     # Generate actionable verification checklist
├── storage/
│   ├── __init__.py
│   ├── models.py                      # SQLAlchemy models for traces, scores, alerts
│   ├── trace_store.py                 # Per-request trace persistence
│   └── metrics_store.py               # Aggregated metrics (per model, per task)
├── dashboard/
│   ├── __init__.py
│   ├── app.py                         # Streamlit dashboard entry point
│   ├── pages/
│   │   ├── overview.py                # Overall system health + request volume
│   │   ├── per_model.py               # Verification scores broken down by model
│   │   ├── per_task.py                # Scores by task category
│   │   ├── drift.py                   # Score trends over time
│   │   └── contradictions.py          # Recent contradiction detections
│   └── components/
│       ├── charts.py                  # Chart helpers
│       └── filters.py                 # Date range, model, task filters
├── tests/
│   ├── test_rate_limiter.py
│   ├── test_claim_extractor.py
│   ├── test_contradiction_detector.py
│   ├── test_confidence_scorer.py
│   ├── test_provider_router.py
│   └── test_integration.py            # End-to-end: proxy → model → verification → response
├── scripts/
│   ├── seed_data.py                   # Generate sample traces for dashboard demo
│   └── benchmark.py                   # Latency benchmark: proxy adds X ms overhead
├── deploy/
│   ├── Dockerfile
│   ├── docker-compose.yml             # proxy + dashboard + db
│   └── .env.example
├── .github/
│   └── workflows/
│       ├── test.yml                   # Run pytest on every PR
│       └── deploy.yml                 # Deploy to fly.io / railway on push to main
├── pyproject.toml                     # Project metadata + dependencies
└── requirements.txt                   # pip freeze
```

---

## 3. Implementation Steps

### Week 1: Proxy Foundation

**Goal:** A working FastAPI server that intercepts requests, forwards to an LLM, and returns the response.

| Day | Task | Files |
|-----|------|-------|
| 1 | Scaffold project: pyproject.toml, FastAPI entry point, health endpoint | `main.py`, `pyproject.toml` |
| 2 | Provider router: OpenAI adapter, Anthropic adapter, local model adapter | `provider_router.py` |
| 3 | Request handler: intercept incoming request (OpenAI-compatible format), validate, forward | `request_handler.py` |
| 4 | Response handler: capture raw LLM response, return it unchanged (verification added later) | `response_handler.py` |
| 5 | Rate limiter: token bucket algorithm, configurable per provider | `rate_limiter.py` |
| 6 | Provider fallback: on 429/503, retry with alternate provider | `fallback.py` |
| 7 | Integration test: proxy → model → response round-trip | `test_integration.py` |

**Checkpoint:** `curl` a prompt through the proxy and get back a real LLM response.

---

### Week 2: Verification Engine

**Goal:** The core verification components — extract claims, detect contradictions, ground to sources.

| Day | Task | Files |
|-----|------|-------|
| 1 | Claim extractor: parse LLM response, extract factual assertions using regex + LLM-as-judge fallback | `claim_extractor.py` |
| 2 | Contradiction detector: cross-check statements within same response, flag conflicting claims | `contradiction_detector.py` |
| 3 | Source grounder: parse RAG context if present, match claims to source chunks | `source_grounder.py` |
| 4 | Unit tests for claim extraction on known test cases | `test_claim_extractor.py` |
| 5 | Unit tests for contradiction detection on known test cases | `test_contradiction_detector.py` |
| 6 | Wire verification engine into response handler: augment response with `verification` field | `response_handler.py` |
| 7 | Edge case handling: empty responses, non-factual responses, model refusals | `response_handler.py` |

**Checkpoint:** Proxy returns response with a `verification` field containing claims, contradictions, sources.

---

### Week 3: Confidence Scoring + Checklist + Persistence

**Goal:** Add confidence estimation, generate verification checklists, store everything in SQLite.

| Day | Task | Files |
|-----|------|-------|
| 1 | Confidence scorer: extract logprobs from API response, map to per-claim confidence | `confidence_scorer.py` |
| 2 | Handle API logprobs: OpenAI returns logprobs, Anthropic doesn't — build fallback using prompt-based confidence | `confidence_scorer.py` |
| 3 | Checklist generator: for action-oriented responses, auto-generate verification checklist | `checklist_generator.py` |
| 4 | SQLite models: Trace, VerificationScore, Contradiction tables | `models.py`, `trace_store.py` |
| 5 | Write traces to SQLite on every request | `trace_store.py`, `response_handler.py` |
| 6 | Metrics store: aggregate per-model, per-task, per-time-period | `metrics_store.py` |
| 7 | Test confidence scorer on known-certain vs known-uncertain responses | `test_confidence_scorer.py` |

**Checkpoint:** Every request is logged to SQLite with full verification data.

---

### Week 4: Dashboard + CI + Deploy

**Goal:** A live dashboard, CI tests, and Docker deployment.

| Day | Task | Files |
|-----|------|-------|
| 1 | Streamlit dashboard scaffold: connect to SQLite, show overview stats | `app.py`, `overview.py` |
| 2 | Per-model page: verification scores by model, trend lines | `per_model.py` |
| 3 | Contradictions page: recent contradictions, model comparison | `contradictions.py` |
| 4 | Drift page: verification score trends over days/weeks | `drift.py` |
| 5 | Seed script: generate 1000 realistic sample traces for demo | `seed_data.py` |
| 6 | Dockerfile + docker-compose: proxy + dashboard + db | `Dockerfile`, `docker-compose.yml` |
| 7 | CI pipeline: GitHub Actions for test + deploy to fly.io | `test.yml`, `deploy.yml` |

**Checkpoint:** `docker compose up` runs the full stack. Live dashboard at `localhost:8501`.

---

### Week 5 (Buffer): Documentation + Polish

| Day | Task | Files |
|-----|------|-------|
| 1 | README: problem, architecture diagram (ASCII), quick start | `README.md` |
| 2 | Architecture doc: detailed component explanation | `docs/architecture.md` |
| 3 | Deployment doc: Docker, fly.io, Railway, env vars | `docs/deployment.md` |
| 4 | Paper summary: arXiv:2605.04454 (*Deployment-Relevant Alignment...*) | `docs/paper-summary.md` |
| 5 | Interview pitch: write out the 30-second answer, practice it | `docs/interview-pitch.md` |
| 6 | Benchmark script: measure median + p99 latency overhead | `scripts/benchmark.py` |
| 7 | Final integration test + README screenshots of dashboard | — |

---

## 4. Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| **Proxy protocol** | OpenAI-compatible API | Most models/providers support it. User changes 1 line of code (base URL) |
| **Storage** | SQLite | Zero infrastructure. Scales to millions of traces. Swap to Postgres later |
| **Dashboard** | Streamlit | Free hosting on Streamlit Cloud. Simple Python. No frontend framework needed |
| **Confidence scoring** | Logit-based when available, prompt-based fallback | No model access required for the fallback |
| **Deploy** | Docker + fly.io | Free tier exists. Single binary. No Kubernetes needed |

---

## 5. What Proves "Deploy at Scale"

| Signal | How This Project Demonstrates It |
|--------|----------------------------------|
| **Middleware architecture** | Reverse proxy pattern — same as production AI gateways (Bifrost, MCP Proxy) |
| **Provider abstraction** | Works with OpenAI, Anthropic, any OpenAI-compatible endpoint |
| **Graceful degradation** | Fallback on provider failure. Rate limiting under load |
| **Observability** | Every request traced. Dashboard with per-model, per-task metrics |
| **CI/CD** | Tests run on every PR. Auto-deploy on push to main |
| **Documentation** | Architecture diagram. Deployment guide. Interview pitch |

---

## 6. Key External Sources

| Source | URL | What It Provides |
|--------|-----|------------------|
| arXiv:2605.04454 — Vishwarupe et al., Oxford | https://arxiv.org/abs/2605.04454 | The gap: deployment-relevant verification support absent; requires infrastructure scaffolding |
| Anthropic Engineering Blog | https://www.anthropic.com/engineering | Proxy/containment architecture patterns (inspiration) |
| Bifrost AI Gateway | https://github.com/maximhq/bifrost | Reference for production AI gateway architecture |
