"""Classification, calibration, and latency metrics for the offline evaluation."""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class Prediction:
    expected: str
    predicted: str
    trust_score: float | None


def classification(
    predictions: Sequence[Prediction],
    expected_label: str,
    accepted_predictions: set[str],
) -> dict:
    tp = fp = fn = 0
    for row in predictions:
        expected = row.expected == expected_label
        predicted = row.predicted in accepted_predictions
        tp += expected and predicted
        fp += not expected and predicted
        fn += expected and not predicted
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "support": tp + fn,
        "precision": round(tp / (tp + fp), 6) if tp + fp else 0.0,
        "recall": round(tp / (tp + fn), 6) if tp + fn else 0.0,
        "f1": round(2 * tp / (2 * tp + fp + fn), 6) if tp + fp + fn else 0.0,
    }


def calibration(predictions: Sequence[Prediction]) -> dict:
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(5)]
    unknown_truth = missing_score = 0
    for row in predictions:
        if row.expected == "unverifiable":
            unknown_truth += 1
            continue
        score = row.trust_score
        if score is None:
            missing_score += 1
            continue
        index = min(int(score * len(bins)), len(bins) - 1)
        bins[index].append((score, row.expected == "verified"))

    total = sum(map(len, bins))
    ece = 0.0
    result = []
    for index, bucket in enumerate(bins):
        count = len(bucket)
        mean = sum(score for score, _ in bucket) / count if count else None
        accuracy = sum(correct for _, correct in bucket) / count if count else None
        if mean is not None and accuracy is not None:
            ece += count * abs(mean - accuracy) / total
        result.append(
            {
                "lower": index / len(bins),
                "upper": (index + 1) / len(bins),
                "count": count,
                "mean_trust": round(mean, 6) if mean is not None else None,
                "actual_correctness": round(accuracy, 6) if accuracy is not None else None,
            },
        )
    return {
        "ece": round(ece, 6) if total else None,
        "scored": total,
        "excluded_unknown_truth": unknown_truth,
        "excluded_missing_score": missing_score,
        "bins": result,
    }


def summarize(predictions: Sequence[Prediction]) -> dict:
    label_scores = {
        label: classification(predictions, label, {label})
        for label in ("verified", "contradicted", "unverifiable")
    }
    label_scores["abstention"] = classification(
        predictions, "unverifiable", {"unverifiable", "no_source"}
    )
    confusion = {
        label: dict(
            sorted(Counter(row.predicted for row in predictions if row.expected == label).items())
        )
        for label in ("verified", "contradicted", "unverifiable")
    }
    return {
        "items": len(predictions),
        "labels": label_scores,
        "confusion": confusion,
        "trust_calibration": calibration(predictions),
    }


def latency_quantiles(samples_ms: Iterable[float]) -> dict:
    ordered = sorted(samples_ms)
    return {
        f"p{percentile}_ms": round(ordered[ceil(percentile / 100 * len(ordered)) - 1], 6)
        for percentile in (50, 95)
    }
