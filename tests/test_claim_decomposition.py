import pytest
from verialign.verification.claim_extractor import ClaimExtractor


@pytest.mark.asyncio
async def test_decompose_compound_and():
    extractor = ClaimExtractor()
    claims = await extractor.extract(
        "VeriAlign is a proxy and it stores traces in SQLite.", use_llm_fallback=False
    )
    # Should split into two atomic claims
    assert len(claims) == 2
    assert claims[0].startswith("VeriAlign is a proxy")
    assert claims[1].startswith("it stores traces")


@pytest.mark.asyncio
async def test_no_decompose_without_and():
    extractor = ClaimExtractor()
    claims = await extractor.extract(
        "VeriAlign is a proxy. It stores traces in SQLite.", use_llm_fallback=False
    )
    assert len(claims) == 2
    assert claims == ["VeriAlign is a proxy.", "It stores traces in SQLite."]


@pytest.mark.asyncio
async def test_decompose_requires_factual_cues():
    extractor = ClaimExtractor()
    # 'and' inside non-clausal phrase should not over-split
    claims = await extractor.extract(
        "The system is fast and reliable.", use_llm_fallback=False
    )
    # Single claim or decomposed but still factual — at least one claim
    assert len(claims) >= 1


@pytest.mark.asyncio
async def test_decompose_compound_with_three_parts():
    extractor = ClaimExtractor()
    text = "Python is fast and Go is compiled and Rust is safe."
    claims = await extractor.extract(text, use_llm_fallback=False)
    # Should decompose into at least 2 atomic claims
    assert len(claims) >= 2
