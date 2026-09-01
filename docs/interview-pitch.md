# VeriAlign — 30-Second Interview Pitch

## The Hook

> "I built a verification proxy that sits between any application and any LLM. Every response gets automatically fact-checked against provided context, contradictions are flagged, and a verification checklist is generated — all without changing the model."

## The Problem (10 seconds)

"Current LLMs hallucinate confidently. Oxford's May 2026 audit (Vishwarupe et al., arXiv:2605.04454) — *Deployment-Relevant Alignment Cannot Be Inferred from Model-Level Evaluation Alone* — found 11 alignment benchmarks provided no user-facing verification support. The authors argue that gap can't be closed at the model level alone and requires infrastructure scaffolding."

## The Solution (10 seconds)

"VeriAlign is a reverse proxy — drop-in replacement for OpenAI's API. You change one line (base_url), and every response comes back with:
- Extracted factual claims with source grounding status (supported/unsupported/unclear)
- Detected contradictions within the response
- Confidence scores (using logprobs when available)
- A prioritized verification checklist for human reviewers
- Full trace persistence for audit"

## Technical Highlights (10 seconds)

"Built in 4 weeks: FastAPI proxy with multi-provider routing (OpenAI, Anthropic, local), token-bucket rate limiting, provider fallback on failures, SQLite trace storage with sensitive data redaction, and a Streamlit dashboard for drift monitoring. The verification engine uses keyword-overlap grounding with embedding upgrade path, regex-based contradiction detection (negation, antonyms, numeric), and heuristic confidence scoring when logprobs aren't available."

## Why It Matters

"This moves verification from 'model responsibility' to 'infrastructure responsibility' — works with any model, any provider, deployable today behind your internal API boundary."