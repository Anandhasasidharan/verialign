"""
Adversarial test mode — hallucination detection benchmark.

Feeds known factual errors through the verification pipeline and measures
how many are correctly flagged as unsupported or contradictory.

Usage:
    python -m verialign.scripts.adversarial_benchmark
"""

import asyncio
from dataclasses import dataclass, field

from verialign.verification.engine import VerificationEngine


@dataclass
class AdversarialCase:
    text: str
    context: list[dict] = field(default_factory=list)
    expected_unsupported: bool = True
    expected_contradictions: int = 0


BENCHMARK_CASES = [
    # Geography hallucinations
    AdversarialCase(
        text="Paris is the capital of Germany.",
        context=[
            {
                "id": "geo-1",
                "text": "The capital of France is Paris. The capital of Germany is Berlin.",
            }
        ],
        expected_unsupported=True,
        expected_contradictions=0,
    ),
    AdversarialCase(
        text="The Amazon River flows through Egypt.",
        context=[
            {
                "id": "geo-2",
                "text": "The Amazon River flows through Brazil. The Nile River flows through Egypt.",
            }
        ],
        expected_unsupported=True,
        expected_contradictions=0,
    ),
    AdversarialCase(
        text="Mount Everest is located in Africa.",
        context=[
            {
                "id": "geo-3",
                "text": "Mount Everest is located in Asia, in the Himalayas.",
            }
        ],
        expected_unsupported=True,
        expected_contradictions=0,
    ),
    # Science hallucinations
    AdversarialCase(
        text="Water boils at 50 degrees Celsius at sea level.",
        context=[
            {"id": "sci-1", "text": "Water boils at 100 degrees Celsius at sea level."}
        ],
        expected_unsupported=True,
        expected_contradictions=0,
    ),
    AdversarialCase(
        text="Humans have 48 chromosomes.",
        context=[
            {
                "id": "sci-2",
                "text": "Humans have 23 pairs of chromosomes, for a total of 46.",
            }
        ],
        expected_unsupported=True,
        expected_contradictions=0,
    ),
    AdversarialCase(
        text="The speed of light is approximately 300 meters per second.",
        context=[
            {
                "id": "sci-3",
                "text": "The speed of light is approximately 300,000 kilometers per second.",
            }
        ],
        expected_unsupported=True,
        expected_contradictions=0,
    ),
    # History hallucinations
    AdversarialCase(
        text="World War II ended in 1943.",
        context=[
            {
                "id": "hist-1",
                "text": "World War II ended in 1945 with the surrender of Japan.",
            }
        ],
        expected_unsupported=True,
        expected_contradictions=0,
    ),
    AdversarialCase(
        text="The Declaration of Independence was signed in 1789.",
        context=[
            {
                "id": "hist-2",
                "text": "The Declaration of Independence was signed in 1776. The US Constitution was signed in 1787.",
            }
        ],
        expected_unsupported=True,
        expected_contradictions=0,
    ),
    # Internal contradictions (claim contradicts itself or context)
    AdversarialCase(
        text="The system is completely secure. The system has known vulnerabilities.",
        context=[],
        expected_unsupported=False,
        expected_contradictions=1,
    ),
    AdversarialCase(
        text="The database uses encryption. The data is stored in plaintext.",
        context=[],
        expected_unsupported=False,
        expected_contradictions=1,
    ),
    # Truthful cases (should NOT be flagged)
    AdversarialCase(
        text="Paris is the capital of France.",
        context=[{"id": "geo-4", "text": "The capital of France is Paris."}],
        expected_unsupported=False,
        expected_contradictions=0,
    ),
    AdversarialCase(
        text="Water boils at 100 degrees Celsius.",
        context=[
            {"id": "sci-4", "text": "Water boils at 100 degrees Celsius at sea level."}
        ],
        expected_unsupported=False,
        expected_contradictions=0,
    ),
]


@dataclass
class AdversarialResult:
    total_cases: int
    hallucinations_correctly_flagged: int
    contradictions_correctly_detected: int
    false_positives: int
    false_negatives: int
    accuracy: float
    details: list[dict] = field(default_factory=list)


async def run_benchmark(engine: VerificationEngine | None = None) -> AdversarialResult:
    if engine is None:
        engine = VerificationEngine()

    flagged = 0
    contradictions_detected = 0
    false_positives = 0
    false_negatives = 0
    details: list[dict] = []

    for case in BENCHMARK_CASES:
        result = await engine.verify(case.text, case.context)
        is_unsupported = any(c.status == "unsupported" for c in result.claims)
        has_contradictions = len(result.contradictions) > 0

        if case.expected_unsupported:
            if is_unsupported:
                flagged += 1
            else:
                false_negatives += 1
        else:
            if is_unsupported:
                false_positives += 1

        if case.expected_contradictions > 0:
            if has_contradictions:
                contradictions_detected += 1

        details.append(
            {
                "text": case.text[:60],
                "expected_unsupported": case.expected_unsupported,
                "flagged_as_unsupported": is_unsupported,
                "contradictions_found": len(result.contradictions),
                "claim_statuses": [c.status for c in result.claims],
            }
        )

    total = len(BENCHMARK_CASES)
    hallucination_cases = sum(1 for c in BENCHMARK_CASES if c.expected_unsupported)
    accuracy = (
        (flagged + (total - hallucination_cases - false_positives)) / total
        if total > 0
        else 0
    )

    return AdversarialResult(
        total_cases=total,
        hallucinations_correctly_flagged=flagged,
        contradictions_correctly_detected=contradictions_detected,
        false_positives=false_positives,
        false_negatives=false_negatives,
        accuracy=round(accuracy, 3),
        details=details,
    )


def print_results(result: AdversarialResult) -> None:
    print("=" * 60)
    print("ADVERSARIAL HALLUCINATION BENCHMARK")
    print("=" * 60)
    print(f"Total cases:               {result.total_cases}")
    print(f"Hallucinations flagged:    {result.hallucinations_correctly_flagged}")
    print(f"Contradictions detected:   {result.contradictions_correctly_detected}")
    print(f"False positives:           {result.false_positives}")
    print(f"False negatives:           {result.false_negatives}")
    print(f"Accuracy:                  {result.accuracy:.3f}")
    print("-" * 60)
    print("Per-case breakdown:")
    for d in result.details:
        status = (
            "✓" if d["flagged_as_unsupported"] == d["expected_unsupported"] else "✗"
        )
        print(
            f"  {status} {d['text']:<55} {'flagged' if d['flagged_as_unsupported'] else 'ok'}"
        )
        if d["contradictions_found"] > 0:
            print(f"      contradictions: {d['contradictions_found']}")
    print("=" * 60)


async def main() -> None:
    result = await run_benchmark()
    print_results(result)


if __name__ == "__main__":
    asyncio.run(main())
