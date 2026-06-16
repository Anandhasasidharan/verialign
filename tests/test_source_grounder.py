import pytest
from verialign.verification.source_grounder import SourceGrounder


@pytest.mark.asyncio
async def test_supported_claim() -> None:
    status, confidence, sources = await SourceGrounder().ground(
        "VeriAlign is a verification support proxy for LLM outputs.",
        [
            {
                "id": "paper",
                "text": "VeriAlign is a verification support proxy for LLM outputs.",
            }
        ],
    )

    assert status == "supported"
    assert confidence >= 0.55
    assert sources[0].source_id == "paper"


@pytest.mark.asyncio
async def test_unsupported_claim() -> None:
    status, confidence, sources = await SourceGrounder().ground(
        "VeriAlign requires a GPU cluster.",
        [{"id": "plan", "text": "VeriAlign runs as a Python FastAPI service."}],
    )

    assert status == "unsupported"
    assert confidence <= 0.3
    assert sources[0].source_id == "plan"
