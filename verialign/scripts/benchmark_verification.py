"""Benchmark end-to-end verification quality: supported/unsupported classification accuracy."""

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
            }
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
            {"id": "doc-1", "text": "Python was created in 1991 by Guido van Rossum."}
        ],
        expected_status="supported",
    ),
    VerificationBenchmarkCase(
        text="Python was created by Linus Torvalds.",
        context=[
            {"id": "doc-1", "text": "Python was created in 1991 by Guido van Rossum."}
        ],
        expected_status="unsupported",
    ),
    VerificationBenchmarkCase(
        text="The system handles authentication.",
        context=[
            {
                "id": "doc-1",
                "text": "The system uses JWT for authentication and RBAC for authorization.",
            }
        ],
        expected_status="supported",
    ),
    VerificationBenchmarkCase(
        text="The system uses bcrypt for password hashing.",
        context=[
            {
                "id": "doc-1",
                "text": "Passwords are stored as bcrypt hashes with a cost factor of 12.",
            }
        ],
        expected_status="supported",
    ),
    VerificationBenchmarkCase(
        text="Mount Everest is 29,029 feet tall.",
        context=[
            {
                "id": "doc-1",
                "text": "Mount Everest's height was officially recognized as 8,848 meters (29,029 ft) in 2020.",
            }
        ],
        expected_status="supported",
    ),
    VerificationBenchmarkCase(
        text="Tokyo has a population of 9 million.",
        context=[
            {
                "id": "doc-1",
                "text": "The Tokyo prefecture has a population of approximately 14 million people.",
            }
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


async def run_benchmark() -> BenchmarkResult:
    engine = VerificationEngine()
    correct = 0
    incorrect = 0
    by_status: dict[str, dict[str, int]] = {}

    for case in BENCHMARK_CASES:
        result = await engine.verify(case.text, case.context)
        status_counts: dict[str, int] = {}
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

        if case.expected_status not in by_status:
            by_status[case.expected_status] = {"total": 0, "correct": 0, "incorrect": 0}
        by_status[case.expected_status]["total"] += 1
        if is_correct:
            by_status[case.expected_status]["correct"] += 1
        else:
            by_status[case.expected_status]["incorrect"] += 1

    accuracy = correct / len(BENCHMARK_CASES) if BENCHMARK_CASES else 0.0
    return BenchmarkResult(
        total=len(BENCHMARK_CASES),
        correct=correct,
        incorrect=incorrect,
        by_status=by_status,
        accuracy=round(accuracy, 3),
    )


def print_results(result: BenchmarkResult) -> None:
    print("=" * 60)
    print("VERIFICATION QUALITY BENCHMARK")
    print("=" * 60)
    print(f"Total cases:  {result.total}")
    print(f"Correct:      {result.correct}")
    print(f"Incorrect:    {result.incorrect}")
    print(f"Accuracy:     {result.accuracy:.3f}")
    print("-" * 60)
    print("Per-status breakdown:")
    for status, stats in sorted(result.by_status.items()):
        acc = stats["correct"] / stats["total"] if stats["total"] > 0 else 0
        print(
            f"  {status:20s}: {stats['correct']}/{stats['total']} correct ({acc:.1%})"
        )
    print("=" * 60)


async def main() -> None:
    result = await run_benchmark()
    print_results(result)


if __name__ == "__main__":
    asyncio.run(main())
