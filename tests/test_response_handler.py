import pytest
from verialign.proxy.middleware.response_handler import ResponseHandler
from verialign.verification.models import VerificationResult, VerifiedClaim, SourceMatch


class MockVerificationEngine:
    def __init__(self, result):
        self.result = result

    async def verify(self, text, context, response_data=None):
        return self.result


class TestResponseHandler:
    @pytest.mark.asyncio
    async def test_augment_adds_verification(self):
        mock_result = VerificationResult(
            claims=[
                VerifiedClaim(
                    text="Test claim",
                    status="supported",
                    confidence=0.9,
                    sources=[SourceMatch(source_id="doc-1", score=0.8, excerpt="Test")],
                )
            ],
            contradictions=[],
            checklist=[],
        )
        engine = MockVerificationEngine(mock_result)
        handler = ResponseHandler(engine)

        upstream = {
            "id": "test-123",
            "choices": [{"message": {"role": "assistant", "content": "Test response"}}],
        }
        request = {"metadata": {"context": [{"id": "doc-1", "text": "Test context"}]}}

        augmented = await handler.augment(upstream, request)

        assert "verification" in augmented.data
        assert augmented.data["verification"]["summary"]["total_claims"] == 1
        assert augmented.verification == mock_result

    def test_extract_assistant_text(self):
        engine = MockVerificationEngine(None)
        handler = ResponseHandler(engine)

        response = {
            "choices": [{"message": {"role": "assistant", "content": "Hello world"}}],
        }
        text = handler._extract_assistant_text(response)
        assert text == "Hello world"

    def test_extract_assistant_text_empty(self):
        engine = MockVerificationEngine(None)
        handler = ResponseHandler(engine)

        response = {"choices": []}
        text = handler._extract_assistant_text(response)
        assert text == ""

    def test_extract_assistant_text_no_content(self):
        engine = MockVerificationEngine(None)
        handler = ResponseHandler(engine)

        response = {"choices": [{"message": {}}]}
        text = handler._extract_assistant_text(response)
        assert text == ""

    def test_build_error_response(self):
        engine = MockVerificationEngine(None)
        handler = ResponseHandler(engine)

        error = ValueError("Test error")
        response = handler.build_error_response(error, 400)

        assert response["error"]["message"] == "Test error"
        assert response["error"]["type"] == "ValueError"
        assert response["error"]["status_code"] == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
