"""Benchmark claim extraction quality: precision, recall, F1 against ground truth."""

import asyncio
from dataclasses import dataclass
from verialign.verification.claim_extractor import ClaimExtractor


@dataclass
class ClaimBenchmarkCase:
    text: str
    expected_claims: list[str]
    min_expected: int = 0


BENCHMARK_CASES = [
    ClaimBenchmarkCase(
        text="Paris is the capital of France. It has a population of about 2.1 million.",
        expected_claims=[
            "Paris is the capital of France.",
        ],
        min_expected=1,
    ),
    ClaimBenchmarkCase(
        text="The Earth orbits the Sun. Water freezes at 0 degrees Celsius. Python is a programming language.",
        expected_claims=[
            "The Earth orbits the Sun.",
            "Water freezes at 0 degrees Celsius.",
            "Python is a programming language.",
        ],
        min_expected=3,
    ),
    ClaimBenchmarkCase(
        text="I think VeriAlign is a great tool. It was published in 2026. The paper is on arXiv.",
        expected_claims=[
            "It was published in 2026.",
            "The paper is on arXiv.",
        ],
        min_expected=2,
    ),
    ClaimBenchmarkCase(
        text="Hello! How can I help you today? What do you need help with?",
        expected_claims=[],
        min_expected=0,
    ),
    ClaimBenchmarkCase(
        text="The capital of Spain is Madrid. The population of Madrid is approximately 3.2 million. Spain is a member of the European Union.",
        expected_claims=[
            "The capital of Spain is Madrid.",
            "Spain is a member of the European Union.",
        ],
        min_expected=2,
    ),
    ClaimBenchmarkCase(
        text="""
        The Moon is Earth's only natural satellite. It orbits at an average distance of 384,400 km.
        The Moon's diameter is about 3,474 km. The first human landing was in 1969.
        The Moon has no significant atmosphere.
        """,
        expected_claims=[
            "The Moon is Earth's only natural satellite.",
            "The Moon's diameter is about 3,474 km.",
            "The first human landing was in 1969.",
            "The Moon has no significant atmosphere.",
        ],
        min_expected=4,
    ),
    ClaimBenchmarkCase(
        text="I can't say for sure. Maybe it works. It might be better to check the documentation.",
        expected_claims=[],
        min_expected=0,
    ),
]


@dataclass
class BenchmarkResult:
    total_cases: int
    total_expected: int
    extracted: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    cases_below_minimum: int


async def run_benchmark() -> BenchmarkResult:
    extractor = ClaimExtractor()
    total_expected = 0
    total_extracted = 0
    true_positives = 0
    false_positives = 0
    false_negatives = 0
    cases_below_min = 0

    for case in BENCHMARK_CASES:
        extracted = await extractor.extract(case.text, use_llm_fallback=False)
        expected_lower = {c.lower().rstrip(".") for c in case.expected_claims}
        extracted_lower = {c.lower().rstrip(".") for c in extracted}

        tp = len(expected_lower & extracted_lower)
        fp = len(extracted_lower - expected_lower)
        fn = len(expected_lower - extracted_lower)

        total_expected += len(case.expected_claims)
        total_extracted += len(extracted)
        true_positives += tp
        false_positives += fp
        false_negatives += fn

        if len(extracted) < case.min_expected:
            cases_below_min += 1

    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives) > 0
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives) > 0
        else 0.0
    )
    f1 = (
        2 * (precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return BenchmarkResult(
        total_cases=len(BENCHMARK_CASES),
        total_expected=total_expected,
        extracted=total_extracted,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=round(precision, 3),
        recall=round(recall, 3),
        f1=round(f1, 3),
        cases_below_minimum=cases_below_min,
    )


def print_results(result: BenchmarkResult) -> None:
    print("=" * 60)
    print("CLAIM EXTRACTION BENCHMARK")
    print("=" * 60)
    print(f"Total cases:            {result.total_cases}")
    print(f"Total expected claims:  {result.total_expected}")
    print(f"Total extracted:        {result.extracted}")
    print(f"True positives:         {result.true_positives}")
    print(f"False positives:        {result.false_positives}")
    print(f"False negatives:        {result.false_negatives}")
    print("-" * 60)
    print(f"Precision:              {result.precision:.3f}")
    print(f"Recall:                 {result.recall:.3f}")
    print(f"F1 Score:               {result.f1:.3f}")
    print(f"Cases below min:        {result.cases_below_minimum}")
    print("=" * 60)

    if result.f1 < 0.5:
        print("WARNING: Low F1 score. The regex-based extractor may need tuning.")
    elif result.f1 >= 0.8:
        print("F1 score is healthy.")


async def main() -> None:
    result = await run_benchmark()
    print_results(result)


if __name__ == "__main__":
    asyncio.run(main())
