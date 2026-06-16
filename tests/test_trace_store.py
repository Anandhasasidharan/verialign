import pytest
import tempfile
import os
from verialign.storage.trace_store import TraceStore, redact_sensitive_data
from verialign.verification.models import VerificationResult, VerifiedClaim, SourceMatch


class TestRedactSensitiveData:
    def test_redact_authorization_header(self):
        text = "Authorization: Bearer sk-1234567890abcdef"
        result = redact_sensitive_data(text)
        assert "Bearer [REDACTED]" in result
        assert "sk-1234567890abcdef" not in result

    def test_redact_api_key(self):
        text = 'api_key = "sk-abcdef1234567890"'
        result = redact_sensitive_data(text)
        assert "[REDACTED]" in result
        assert "sk-abcdef1234567890" not in result

    def test_redact_secret(self):
        text = "secret: my-secret-value"
        result = redact_sensitive_data(text)
        assert "[REDACTED]" in result
        assert "my-secret-value" not in result

    def test_redact_dict(self):
        data = {
            "headers": {"Authorization": "Bearer token123"},
            "api_key": "sk-1234567890abcdef1234567890abcdef",
            "normal": "value",
        }
        result = redact_sensitive_data(data)
        assert result["headers"]["Authorization"] == "Bearer [REDACTED]"
        assert result["api_key"] == "[REDACTED]"
        assert result["normal"] == "value"

    def test_redact_list(self):
        data = [
            "Bearer token123",
            "normal",
            {"key": "sk-1234567890abcdef1234567890abcdef"},
        ]
        result = redact_sensitive_data(data)
        assert result[0] == "Bearer [REDACTED]"
        assert result[1] == "normal"
        assert result[2]["key"] == "[REDACTED]"


class TestTraceStore:
    def setup_method(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite3")
        self.temp_db.close()
        self.store = TraceStore(self.temp_db.name, redact=True)

    def teardown_method(self):
        os.unlink(self.temp_db.name)

    def test_write_and_read_trace(self):
        verification = VerificationResult(
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

        request = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "metadata": {"context": [{"id": "doc-1", "text": "Test"}]},
        }
        response = {
            "id": "test-123",
            "choices": [{"message": {"role": "assistant", "content": "Hi there"}}],
        }

        self.store.write_trace(request, response, verification)
        traces = self.store.list_recent(10)

        assert len(traces) == 1
        assert traces[0]["model"] == "gpt-4"
        assert traces[0]["request"]["model"] == "gpt-4"
        assert traces[0]["verification"]["summary"]["total_claims"] == 1

    def test_redaction_on_write(self):
        verification = VerificationResult(claims=[], contradictions=[], checklist=[])

        request = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "headers": {"Authorization": "Bearer secret-token"},
        }
        response = {"id": "test", "choices": []}

        self.store.write_trace(request, response, verification)
        traces = self.store.list_recent(1)

        assert traces[0]["request"]["headers"]["Authorization"] == "Bearer [REDACTED]"

    def test_no_redaction_when_disabled(self):
        store_no_redact = TraceStore(self.temp_db.name, redact=False)

        verification = VerificationResult(claims=[], contradictions=[], checklist=[])

        request = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "headers": {"Authorization": "Bearer secret-token"},
        }
        response = {"id": "test", "choices": []}

        store_no_redact.write_trace(request, response, verification)
        traces = store_no_redact.list_recent(1)

        assert traces[0]["request"]["headers"]["Authorization"] == "Bearer secret-token"

    def test_list_recent_limit(self):
        verification = VerificationResult(claims=[], contradictions=[], checklist=[])

        for i in range(5):
            request = {"model": f"model-{i}", "messages": []}
            response = {"id": f"resp-{i}", "choices": []}
            self.store.write_trace(request, response, verification)

        traces = self.store.list_recent(3)
        assert len(traces) == 3

        traces = self.store.list_recent(100)
        assert len(traces) == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
