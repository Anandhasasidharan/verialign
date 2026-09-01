from unittest.mock import patch

from verialign.proxy.otel_genai import emit_genai_span


class TestOtelGenai:
    def test_emit_genai_span_sets_attributes(self) -> None:
        attrs = {}

        class FakeSpan:
            def set_attribute(self, key, value) -> None:
                attrs[key] = value

            def __exit__(self, *args):
                pass

            def __enter__(self):
                return self

        with patch("verialign.proxy.otel_genai._otel_available", True):
            with patch("verialign.proxy.otel_genai._tracer") as mock_tracer:
                mock_tracer.start_as_current_span.return_value = FakeSpan()
                emit_genai_span(
                    {"model": "gpt-4o"},
                    {
                        "id": "chatcmpl-123",
                        "model": "gpt-4o",
                        "usage": {"prompt_tokens": 50, "completion_tokens": 100},
                        "choices": [{"finish_reason": "stop"}],
                    },
                    provider="openai",
                )

        assert attrs.get("gen_ai.system") == "openai"
        assert attrs.get("gen_ai.request.model") == "gpt-4o"
        assert attrs.get("gen_ai.usage.prompt_tokens") == 50
        assert attrs.get("gen_ai.usage.completion_tokens") == 100
        assert attrs.get("gen_ai.usage.total_tokens") == 150
        assert attrs.get("gen_ai.response.id") == "chatcmpl-123"
        assert attrs.get("gen_ai.response.finish_reasons") == ["stop"]

    def test_no_op_when_otel_unavailable(self) -> None:
        with patch("verialign.proxy.otel_genai._otel_available", False):
            emit_genai_span(
                {"model": "gpt-4o"},
                {"id": "chatcmpl-123", "model": "gpt-4o", "usage": {}, "choices": []},
            )

    def test_handles_missing_usage(self) -> None:
        attrs = {}

        class FakeSpan:
            def set_attribute(self, key, value) -> None:
                attrs[key] = value

            def __exit__(self, *args):
                pass

            def __enter__(self):
                return self

        with patch("verialign.proxy.otel_genai._otel_available", True):
            with patch("verialign.proxy.otel_genai._tracer") as mock_tracer:
                mock_tracer.start_as_current_span.return_value = FakeSpan()
                emit_genai_span(
                    {"model": "gpt-4o"},
                    {"id": "chatcmpl-123", "model": "gpt-4o", "choices": []},
                    provider="openai",
                )

        assert attrs.get("gen_ai.system") == "openai"
        assert "gen_ai.usage.prompt_tokens" not in attrs

    def test_handles_empty_finish_reasons(self) -> None:
        attrs = {}

        class FakeSpan:
            def set_attribute(self, key, value) -> None:
                attrs[key] = value

            def __exit__(self, *args):
                pass

            def __enter__(self):
                return self

        with patch("verialign.proxy.otel_genai._otel_available", True):
            with patch("verialign.proxy.otel_genai._tracer") as mock_tracer:
                mock_tracer.start_as_current_span.return_value = FakeSpan()
                emit_genai_span(
                    {"model": "gpt-4o"},
                    {
                        "id": "chatcmpl-123",
                        "model": "gpt-4o",
                        "usage": {},
                        "choices": [{}],
                    },
                    provider="anthropic",
                )

        assert attrs.get("gen_ai.system") == "anthropic"
        assert "gen_ai.response.finish_reasons" not in attrs
