import asyncio
import json
from unittest.mock import AsyncMock

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


@pytest.mark.asyncio
async def test_rule_filter_keeps_active_facts_and_approximate_measurements() -> None:
    claims = await ClaimExtractor().extract(
        "Is this a factual statement? The API might be ready. I wrote the API. "
        "Perhaps the database is ready. Dr. Rivera wrote a book. "
        "The U.S. Navy built the ship. Its length is about 150 meters."
    )
    assert claims == [
        "Dr. Rivera wrote a book.",
        "The U.S. Navy built the ship.",
        "Its length is about 150 meters.",
    ]


@pytest.mark.asyncio
async def test_shared_subject_and_keeps_whole_claim() -> None:
    text = "The tool can check a claim and compare it with supplied sources."
    assert await ClaimExtractor().extract(text) == [text]


def completion(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


@pytest.mark.asyncio
async def test_strict_llm_selects_only_unresolved_spans_in_source_order() -> None:
    model = AsyncMock(return_value=completion('{"claim_indices":[0]}'))
    extractor = ClaimExtractor(llm_client=model)
    claims = await extractor.extract(
        "Ana speaks three languages. The service is online. I think the service is fast."
    )
    assert claims == ["Ana speaks three languages.", "The service is online."]
    request = model.await_args.args[0]
    assert json.loads(request["messages"][-1]["content"]) == ["Ana speaks three languages."]
    assert request["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"claim_indices":[0]}\n```',
        '{"claim_indices":["0"]}',
        '{"claim_indices":[true]}',
        '{"claim_indices":[0,2]}',
        '{"claim_indices":[0],"invented":"Not a source sentence"}',
    ],
)
async def test_rejects_invalid_llm_output_and_preserves_rule_claims(content) -> None:
    model = AsyncMock(return_value=completion(content))
    extractor = ClaimExtractor(llm_client=model)
    assert await extractor.extract("Ana speaks three languages. The service is online.") == [
        "The service is online."
    ]


@pytest.mark.asyncio
async def test_timed_out_llm_preserves_rule_claims() -> None:
    async def stalled_model(request):
        await asyncio.Event().wait()

    extractor = ClaimExtractor(llm_client=stalled_model, llm_timeout_seconds=0.01)
    assert await extractor.extract("Ana speaks three languages. The service is online.") == [
        "The service is online."
    ]
