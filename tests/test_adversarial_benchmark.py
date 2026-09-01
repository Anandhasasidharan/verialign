import pytest

from verialign.scripts.adversarial_benchmark import BENCHMARK_CASES, run_benchmark


class TestAdversarialBenchmark:
    def test_has_test_cases(self) -> None:
        assert len(BENCHMARK_CASES) > 0

    def test_cases_have_required_fields(self) -> None:
        for case in BENCHMARK_CASES:
            assert hasattr(case, "text")
            assert hasattr(case, "context")
            assert hasattr(case, "expected_unsupported")
            assert isinstance(case.text, str)
            assert isinstance(case.context, list)

    def test_some_cases_expect_unsupported(self) -> None:
        assert any(c.expected_unsupported for c in BENCHMARK_CASES)

    def test_some_cases_expect_supported(self) -> None:
        assert any(not c.expected_unsupported for c in BENCHMARK_CASES)

    def test_some_cases_expect_contradictions(self) -> None:
        assert any(c.expected_contradictions > 0 for c in BENCHMARK_CASES)

    @pytest.mark.asyncio
    async def test_benchmark_runs_without_error(self) -> None:
        result = await run_benchmark()
        assert result.total_cases == len(BENCHMARK_CASES)
        assert result.accuracy >= 0

    @pytest.mark.asyncio
    async def test_benchmark_details_have_all_cases(self) -> None:
        result = await run_benchmark()
        assert len(result.details) == len(BENCHMARK_CASES)

    @pytest.mark.asyncio
    async def test_false_positives_and_negatives_are_counts(self) -> None:
        result = await run_benchmark()
        assert result.false_positives >= 0
        assert result.false_negatives >= 0
