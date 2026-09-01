import pytest
from verialign.scripts.benchmark_verification import run_benchmark


@pytest.mark.asyncio
async def test_benchmark_returns_calibration():
    result = await run_benchmark()
    assert hasattr(result, "calibration")
    assert hasattr(result, "ece")
    assert isinstance(result.calibration, list)
    assert len(result.calibration) == 5  # 5 buckets
    assert result.ece >= 0
    # Check bucket structure
    for b in result.calibration:
        assert "bucket" in b
        assert "count" in b
        assert "avg_confidence" in b
        assert "accuracy" in b


@pytest.mark.asyncio
async def test_benchmark_accuracy_and_ece_bounded():
    result = await run_benchmark()
    assert 0 <= result.accuracy <= 1
    assert 0 <= result.ece <= 1
