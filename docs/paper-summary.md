# Paper Summary: arXiv:2605.04454

## Title
**"Deployment-Relevant Alignment Cannot Be Inferred from Model-Level Evaluation Alone"**
Vishwarupe, Shadbolt, Jirotka, Flechais — Oxford, May 2026

## Key Finding
The authors audited 11 major alignment benchmarks and found that mechanisms for
user-facing verification were absent across the set. In the authors' framing,
benchmarks evaluate models in isolation and do not measure whether a deployed
user can check the output.

Paraphrased: the gap is structural — model-level scores do not predict whether
a user can verify a response in a deployment context. The paper argues this
cannot be closed by model improvements alone and requires infrastructure-level
scaffolding.

Short verbatim anchor (under 15 words): *"verification support was absent"* across the benchmarks audited.

## The Core Problem

Current alignment benchmarks measure:
- Helpfulness
- Harmlessness
- Honesty (self-reported)
- Instruction following
- Reasoning capability

But they **don't measure** whether users can actually verify the model's outputs in deployment.

## Why This Matters

1. **Models hallucinate** — even aligned ones
2. **Users can't distinguish** confident hallucinations from truth without tooling
3. **Verification is an infrastructure problem**, not solely a model problem
4. **A proxy layer** can provide verification for any model

## VeriAlign's Approach

VeriAlign implements the paper's implied solution: **infrastructure-level verification scaffolding**

| Paper Gap | VeriAlign Solution |
|-----------|-------------------|
| No claim extraction | `ClaimExtractor` — regex + heuristic extraction |
| No source grounding | `SourceGrounder` — keyword overlap + semantic matching |
| No contradiction detection | `ContradictionDetector` — negation, antonyms, numeric |
| No confidence scoring | `ConfidenceScorer` — logprobs + heuristics |
| No actionable output | `ChecklistGenerator` — prioritized verification tasks |
| No observability | SQLite traces + Streamlit dashboard |

## Benchmarks Audited (11 total)

The paper lists 11 benchmarks (including TruthfulQA, HaluEval, FactScore, SelfCheckGPT, and RAG-focused suites). The common pattern identified is that all evaluate model outputs, but none provide user-facing verification support as defined above.

*For full methodology, see the PDF at https://arxiv.org/abs/2605.04454 — this summary is paraphrased; only the short anchor above is verbatim.*

## Implications

1. **Verification must be external** — can't rely on model self-assessment alone
2. **Works with any model** — proxy architecture is model-agnostic
3. **Infrastructure investment** — verification layer is reusable across models
4. **Measurable** — verification quality can be benchmarked independently with calibration

## VeriAlign's Contribution

VeriAlign demonstrates that the verification gap identified in the paper **can be addressed at the infrastructure level** with:
- OpenAI-compatible proxy (drop-in replacement)
- Real-time claim extraction and grounding
- Contradiction detection
- Confidence scoring with calibration reporting
- Persistent traces for audit/review
- Dashboard for human-in-the-loop verification
