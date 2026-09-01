"""Benchmark end-to-end verification quality: supported/unsupported classification accuracy + calibration (reliability diagram)."""

import asyncio
from dataclasses import dataclass

from verialign.verification.engine import VerificationEngine


@dataclass
class VerificationBenchmarkCase:
    text: str
    context: list[dict]
    expected_status: str  # "supported", "unsupported", or "unclear"


BENCHMARK_CASES = [
    VerificationBenchmarkCase(
        text="Paris is the capital of France.",
        context=[{"id": "doc-1", "text": "The capital of France is Paris."}],
        expected_status="supported",
    ),
    VerificationBenchmarkCase(
        text="Paris is the capital of Spain.",
        context=[{"id": "doc-1", "text": "The capital of France is Paris."}],
        expected_status="unsupported",
    ),
    VerificationBenchmarkCase(
        text="Water boils at 100 degrees Celsius.",
        context=[
            {
                "id": "doc-1",
                "text": "At standard pressure, water boils at 100 degrees Celsius.",
            },
        ],
        expected_status="supported",
    ),
    VerificationBenchmarkCase(
        text="The Earth is flat.",
        context=[{"id": "doc-1", "text": "The Earth is an oblate spheroid."}],
        expected_status="unsupported",
    ),
    VerificationBenchmarkCase(
        text="Python was created by Guido van Rossum.",
        context=[
            {"id": "doc-1", "text": "Python was created in 1991 by Guido van Rossum."},
        ],
        expected_status="supported",
    ),
    VerificationBenchmarkCase(
        text="Python was created by Linus Torvalds.",
        context=[
            {"id": "doc-1", "text": "Python was created in 1991 by Guido van Rossum."},
        ],
        expected_status="unsupported",
    ),
    VerificationBenchmarkCase(
        text="The system handles authentication.",
        context=[
            {
                "id": "doc-1",
                "text": "The system uses JWT for authentication and RBAC for authorization.",
            },
        ],
        expected_status="supported",
    ),
    VerificationBenchmarkCase(
        text="The system uses bcrypt for password hashing.",
        context=[
            {
                "id": "doc-1",
                "text": "Passwords are stored as bcrypt hashes with a cost factor of 12.",
            },
        ],
        expected_status="supported",
    ),
    VerificationBenchmarkCase(
        text="Mount Everest is 29,029 feet tall.",
        context=[
            {
                "id": "doc-1",
                "text": "Mount Everest's height was officially recognized as 8,848 meters (29,029 ft) in 2020.",
            },
        ],
        expected_status="supported",
    ),
    VerificationBenchmarkCase(
        text="Tokyo has a population of 9 million.",
        context=[
            {
                "id": "doc-1",
                "text": "The Tokyo prefecture has a population of approximately 14 million people.",
            },
        ],
        expected_status="unsupported",
    ),
]


@dataclass
class BenchmarkResult:
    total: int
    correct: int
    incorrect: int
    by_status: dict[str, dict[str, int]]
    accuracy: float
    calibration: list[dict]  # bucket -> {count, avg_confidence, accuracy, ece_contrib}
    ece: float  # expected calibration error


async def run_benchmark() -> BenchmarkResult:
    engine = VerificationEngine()
    correct = 0
    incorrect = 0
    by_status: dict[str, dict[str, int]] = {}
    # For calibration: collect (predicted_confidence, is_correct) per case (majority claim)
    calib_points: list[tuple[float, bool]] = []

    for case in BENCHMARK_CASES:
        result = await engine.verify(case.text, case.context)
        status_counts: dict[str, int] = {}
        # avg confidence of claims that determine status
        avg_conf = 0.0
        if result.claims:
            avg_conf = sum(c.confidence for c in result.claims) / len(result.claims)
        for claim in result.claims:
            status_counts[claim.status] = status_counts.get(claim.status, 0) + 1

        if not result.claims:
            predicted = "unclear"
        else:
            predicted = max(status_counts, key=status_counts.get)

        is_correct = predicted == case.expected_status
        if is_correct:
            correct += 1
        else:
            incorrect += 1

        calib_points.append((avg_conf, is_correct))

        if case.expected_status not in by_status:
            by_status[case.expected_status] = {"total": 0, "correct": 0, "incorrect": 0}
        by_status[case.expected_status]["total"] += 1
        if is_correct:
            by_status[case.expected_status]["correct"] += 1
        else:
            by_status[case.expected_status]["incorrect"] += 1

    accuracy = correct / len(BENCHMARK_CASES) if BENCHMARK_CASES else 0.0

    # Reliability diagram bucketed by confidence (5 buckets)
    buckets = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
    calibration = []
    ece = 0.0
    for lo, hi in buckets:
        bucket_points = [p for p in calib_points if lo <= p[0] < hi or (hi == 1.0 and p[0] == 1.0)]
        count = len(bucket_points)
        if count == 0:
            calibration.append(
                {
                    "bucket": f"{lo:.1f}-{hi:.1f}",
                    "count": 0,
                    "avg_confidence": 0.0,
                    "accuracy": 0.0,
                    "ece_contrib": 0.0,
                },
            )
            continue
        avg_conf_bucket = sum(p[0] for p in bucket_points) / count
        acc_bucket = sum(1 for p in bucket_points if p[1]) / count
        ece_contrib = (
            abs(avg_conf_bucket - acc_bucket) * (count / len(calib_points)) if calib_points else 0
        )
        ece += ece_contrib
        calibration.append(
            {
                "bucket": f"{lo:.1f}-{hi:.1f}",
                "count": count,
                "avg_confidence": round(avg_conf_bucket, 3),
                "accuracy": round(acc_bucket, 3),
                "ece_contrib": round(ece_contrib, 4),
            },
        )

    return BenchmarkResult(
        total=len(BENCHMARK_CASES),
        correct=correct,
        incorrect=incorrect,
        by_status=by_status,
        accuracy=round(accuracy, 3),
        calibration=calibration,
        ece=round(ece, 4),
    )


def print_results(result: BenchmarkResult) -> None:
    for _status, stats in sorted(result.by_status.items()):
        stats["correct"] / stats["total"] if stats["total"] > 0 else 0
    for b in result.calibration:
        abs(b["avg_confidence"] - b["accuracy"]) if b["count"] else 0


async def main() -> None:
    result = await run_benchmark()
    print_results(result)


if __name__ == "__main__":
    asyncio.run(main())
