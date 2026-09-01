# Verification Calibration — Reliability Diagram

**Source:** `scripts/benchmark_verification.py` (10 cases, keyword + NLI pipeline, `use_rescoring=False` default)
**Date:** 2026-06-29
**Commit:** re-run in CI on every `verialign/verification/*` change (`test` job runs `benchmark_verification` and `benchmark_claims`)

## Summary

| Metric | Value |
|--------|-------|
| Total cases | 10 |
| Accuracy (majority-claim status) | 0.100 |
| Expected Calibration Error (ECE) | 0.6968 |
| Precision/Recall/F1 (claim extraction) | 0.714 / 0.833 / 0.769 (7 cases) |

## Reliability Diagram (predicted confidence vs observed correctness)

Answers: *if VeriAlign says 0.8, is it right 80% of the time?*

| Bucket | Count | Avg Confidence | Accuracy | |Gap| |
|--------|-------|----------------|----------|-------|
| 0.0-0.2 | 2 | 0.0 | 0.0 | 0.000 |
| 0.2-0.4 | 0 | 0.0 | 0.0 | 0.000 |
| 0.4-0.6 | 0 | 0.0 | 0.0 | 0.000 |
| 0.6-0.8 | 0 | 0.0 | 0.0 | 0.000 |
| 0.8-1.0 | 8 | 0.996 | 0.125 | 0.871 |

Bucket is the mean `claim.confidence` for claims driving the prediction. `Accuracy` is fraction where the predicted status matched `expected_status`.

**Interpretation:** The current pipeline is over-confident and under-accurate on this small synthetic set — the 0.8–1.0 bucket is calibrated at only 12.5% accuracy (gap 0.87) and dominates 8/10 cases. This reflects the known NLI warrant gap: without claim-conditioned re-scoring (`use_rescoring=True`, SIFT), entailment scores do not license the claim. With `use_rescoring=True` the gap should shrink (trades recall for precision). Procurement should use this artifact contractually: a well-calibrated system would have ECE <0.1 with avg_confidence ≈ accuracy per bucket.

## How to re-run

```bash
python -m verialign.scripts.benchmark_verification
python -m verialign.scripts.benchmark_claims
```

CI runs both on every push/PR (`test` job — `Benchmark claim extraction` + `Benchmark verification quality`). Any change to `verialign/verification/*` must include an updated run of this doc.

## Next steps

- Add more cases (compound claims, numeric contradictions, tool-call grounding) to widen coverage.
- Re-run with `use_rescoring=True` and with real NLI (`cross-encoder/nli-deberta-v3-base`) to measure calibration delta.
- Track ECE trend in CI artifact history (fail if ECE regresses >0.05).

## Relation to Phase 1

This report satisfies Phase 1 calibration acceptance: a documented precision/recall/F1 *and* calibration number for the verification engine as a whole (not just claim extraction), committed to `docs/`, regenerated in CI.
