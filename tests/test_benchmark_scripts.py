import pytest


class TestBenchmarkClaims:
    def test_module_imports(self):
        from verialign.scripts import benchmark_claims

        assert hasattr(benchmark_claims, "run_benchmark")

    @pytest.mark.asyncio
    async def test_benchmark_runs_without_error(self):
        from verialign.scripts.benchmark_claims import run_benchmark

        result = await run_benchmark()
        assert result.total_cases > 0
        assert result.precision >= 0
        assert result.recall >= 0
        assert result.f1 >= 0


class TestBenchmarkVerification:
    def test_module_imports(self):
        from verialign.scripts import benchmark_verification

        assert hasattr(benchmark_verification, "run_benchmark")

    @pytest.mark.asyncio
    async def test_benchmark_runs_without_error(self):
        from verialign.scripts.benchmark_verification import (
            run_benchmark,
            BENCHMARK_CASES,
        )

        result = await run_benchmark()
        assert len(BENCHMARK_CASES) > 0
        assert result.accuracy >= 0

    @pytest.mark.asyncio
    async def test_benchmark_by_status_breakdown(self):
        from verialign.scripts.benchmark_verification import run_benchmark

        result = await run_benchmark()
        assert isinstance(result.by_status, dict)
        for status, counts in result.by_status.items():
            assert "correct" in counts
            assert "total" in counts
