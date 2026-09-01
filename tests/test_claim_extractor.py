import pytest

from verialign.verification.claim_extractor import ClaimExtractor


@pytest.mark.asyncio
async def test_extracts_factual_claims() -> None:
    claims = await ClaimExtractor().extract(
        "VeriAlign is a proxy. It stores traces in SQLite. Maybe try it?",
    )

    assert claims == ["VeriAlign is a proxy.", "It stores traces in SQLite."]


@pytest.mark.asyncio
async def test_empty_text_has_no_claims() -> None:
    assert await ClaimExtractor().extract("") == []


@pytest.mark.asyncio
async def test_skips_request_echo_meta_sentences() -> None:
    claims = await ClaimExtractor().extract(
        "VeriAlign is a proxy. The latest user request was: What is VeriAlign?",
    )

    assert claims == ["VeriAlign is a proxy."]
