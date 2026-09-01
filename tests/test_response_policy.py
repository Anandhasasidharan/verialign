import pytest
from verialign.proxy.middleware.response_handler import ResponseHandler
from verialign.verification.models import VerificationResult, VerifiedClaim, SourceMatch


class LowTrustEngine:
    async def verify(self, text, context, response_data=None, tool_calls=None):
        # Return low trust_score to trigger warn/block
        return VerificationResult(
            claims=[VerifiedClaim(text=text or "claim", status="unsupported", confidence=0.2, sources=[])],
            contradictions=[],
            checklist=[],
            trust_score=0.2,
        )

class HighTrustEngine:
    async def verify(self, text, context, response_data=None, tool_calls=None):
        return VerificationResult(
            claims=[VerifiedClaim(text="supported claim", status="supported", confidence=0.95, sources=[SourceMatch(source_id="doc-1", score=0.9, excerpt="truth")])],
            contradictions=[],
            checklist=[],
            trust_score=0.9,
        )


@pytest.mark.asyncio
async def test_policy_pass_through_default():
    handler = ResponseHandler(LowTrustEngine(), policy="pass-through", block_threshold=0.5)
    upstream = {"id": "t", "choices": [{"message": {"role": "assistant", "content": "hello"}}]}
    result = await handler.augment(upstream, {})
    assert result.status_code == 200
    assert "X-VeriAlign-Warning" not in result.headers
    assert "X-VeriAlign-Blocked" not in result.headers
    assert "verification" in result.data

@pytest.mark.asyncio
async def test_policy_warn_sets_header_and_injects_caveat():
    handler = ResponseHandler(LowTrustEngine(), policy="warn", block_threshold=0.5)
    upstream = {"id": "t", "choices": [{"message": {"role": "assistant", "content": "hello world"}}]}
    result = await handler.augment(upstream, {})
    assert result.status_code == 200
    assert result.headers.get("X-VeriAlign-Warning") == "true"
    content = result.data["choices"][0]["message"]["content"]
    assert "VeriAlign warning" in content
    assert content.endswith("hello world") or "hello world" in content

@pytest.mark.asyncio
async def test_policy_warn_no_trigger_when_high_trust():
    handler = ResponseHandler(HighTrustEngine(), policy="warn", block_threshold=0.5)
    upstream = {"id": "t", "choices": [{"message": {"role": "assistant", "content": "hello"}}]}
    result = await handler.augment(upstream, {})
    assert result.headers == {}
    assert result.status_code == 200

@pytest.mark.asyncio
async def test_policy_block_returns_422():
    handler = ResponseHandler(LowTrustEngine(), policy="block", block_threshold=0.5)
    upstream = {"id": "t", "choices": [{"message": {"role": "assistant", "content": "hello"}}]}
    result = await handler.augment(upstream, {})
    assert result.status_code == 422
    assert result.headers.get("X-VeriAlign-Blocked") == "true"
    assert "error" in result.data
    assert result.data["error"]["type"] == "verification_blocked"
    assert "verification" in result.data

@pytest.mark.asyncio
async def test_policy_block_no_trigger_high_trust():
    handler = ResponseHandler(HighTrustEngine(), policy="block", block_threshold=0.5)
    upstream = {"id": "t", "choices": [{"message": {"role": "assistant", "content": "hello"}}]}
    result = await handler.augment(upstream, {})
    assert result.status_code == 200
    assert "verification" in result.data

@pytest.mark.asyncio
async def test_structured_output_nests_under_data():
    engine = HighTrustEngine()
    handler = ResponseHandler(engine, structured_output=True, policy="pass-through")
    upstream = {"id": "t", "choices": [{"message": {"role": "assistant", "content": "hello"}}]}
    result = await handler.augment(upstream, {})
    assert "data" in result.data
    assert "verification" not in result.data
    assert "claims" in result.data["data"]

@pytest.mark.asyncio
async def test_structured_output_block_nests():
    handler = ResponseHandler(LowTrustEngine(), structured_output=True, policy="block", block_threshold=0.5)
    upstream = {"id": "t", "choices": [{"message": {"role": "assistant", "content": "hello"}}]}
    result = await handler.augment(upstream, {})
    assert result.status_code == 422
    assert "data" in result.data
    assert "error" in result.data
