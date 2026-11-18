"""Fit score calibration on one FEVER slice and evaluate on a disjoint slice."""

import argparse
import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import cast

from eval.build_dataset import normalize_claim
from eval.metrics import Prediction, calibration, summarize
from eval.run_eval import DATASET, keyword_engine, predict
from verialign.verification.engine import VerificationEngine
from verialign.verification.nli_grounder import NLIGrounder


def read_slice(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def assert_disjoint(slices: list[list[dict]]) -> None:
    seen_ids = set()
    seen_claims = set()
    for rows in slices:
        ids = {row["id"] for row in rows}
        claims = {normalize_claim(row["claim"]) for row in rows}
        if len(ids) != len(rows) or seen_ids & ids or seen_claims & claims:
            raise ValueError("FEVER slices must have unique IDs and no shared claims")
        seen_ids.update(ids)
        seen_claims.update(claims)


def known_truth(predictions: list[Prediction]) -> list[tuple[float, bool]]:
    return [
        (row.trust_score, row.expected == "verified")
        for row in predictions
        if row.trust_score is not None and row.expected != "unverifiable"
    ]


def score_metrics(predictions: list[Prediction]) -> dict:
    rows = known_truth(predictions)
    return {
        **calibration(predictions),
        "brier": round(sum((score - supported) ** 2 for score, supported in rows) / len(rows), 6),
        "thresholds": {
            str(threshold): {
                "supported_at_or_above": sum(score >= threshold and truth for score, truth in rows),
                "refuted_at_or_above": sum(
                    score >= threshold and not truth for score, truth in rows
                ),
            }
            for threshold in (0.5, 0.8)
        },
    }


def calibrate(fit: list[Prediction], test: list[Prediction]) -> dict:
    from sklearn.isotonic import IsotonicRegression

    scores, supported = zip(*known_truth(fit), strict=True)
    model = IsotonicRegression(out_of_bounds="clip").fit(scores, supported)
    indices = [i for i, row in enumerate(test) if row.trust_score is not None]
    transformed = list(test)
    values = model.predict([cast(float, test[i].trust_score) for i in indices])
    for i, score in zip(indices, values, strict=True):
        transformed[i] = replace(test[i], trust_score=float(score))
    return {
        "method": "isotonic",
        "fit_known_truth": len(scores),
        "score_knots": model.X_thresholds_.tolist(),
        "calibrated_knots": model.y_thresholds_.tolist(),
        "held_out_raw": score_metrics(test),
        "held_out_calibrated": score_metrics(transformed),
    }


async def run(fit: Path, held_out: Path, nli_model: str | None) -> dict:
    paths = (DATASET, fit, held_out)
    frozen_rows, fit_rows, held_out_rows = slices = [read_slice(path) for path in paths]
    assert_disjoint(slices)
    if nli_model:
        engine = VerificationEngine(use_nli=True)
        model = NLIGrounder(nli_model)
        engine.source_grounder._nli_grounder = model
        engine.source_grounder.use_semantic = False
        if not await model.score("Paris is in France.", ["Paris is the capital of France."]):
            raise RuntimeError("NLI checkpoint did not score the warm-up")
    else:
        engine = keyword_engine()
    frozen = await predict(frozen_rows, engine)
    training = await predict(fit_rows, engine)
    test = await predict(held_out_rows, engine)
    return {
        "profile": "nli" if nli_model else "keyword",
        "nli_checkpoint": nli_model,
        "dataset_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
        },
        "frozen": summarize(frozen),
        "held_out": summarize(test),
        "calibration": calibrate(training, test),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fit", type=Path)
    parser.add_argument("held_out", type=Path)
    parser.add_argument("--nli-model", help="Local checkpoint or Hugging Face model ID")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run(args.fit, args.held_out, args.nli_model))
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    calibration = result["calibration"]
    for key in ("held_out_raw", "held_out_calibrated"):
        print(key, "ECE", calibration[key]["ece"], "Brier", calibration[key]["brier"])


if __name__ == "__main__":
    main()
