import pytest
from verialign.proxy.middleware.request_handler import (
    validate_request,
    build_upstream_payload,
    ValidatedRequest,
)


class TestRequestHandler:
    def test_validate_request_valid(self):
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.7,
            "max_tokens": 100,
        }
        validated = validate_request(payload)
        assert validated.model == "gpt-4"
        assert validated.messages == [{"role": "user", "content": "Hello"}]
        assert validated.temperature == 0.7
        assert validated.max_tokens == 100
        assert validated.stream is False

    def test_validate_request_missing_model(self):
        payload = {"messages": [{"role": "user", "content": "Hello"}]}
        with pytest.raises(ValueError, match="model is required"):
            validate_request(payload)

    def test_validate_request_empty_messages(self):
        payload = {"model": "gpt-4", "messages": []}
        with pytest.raises(ValueError, match="messages must be a non-empty list"):
            validate_request(payload)

    def test_validate_request_invalid_message_format(self):
        payload = {"model": "gpt-4", "messages": [{"role": "user"}]}
        with pytest.raises(ValueError, match="each message must have role and content"):
            validate_request(payload)

    def test_validate_request_stream_true_accepted(self):
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }
        validated = validate_request(payload)
        assert validated.stream is True

    def test_validate_request_temperature_out_of_range(self):
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 3.0,
        }
        with pytest.raises(
            ValueError, match="temperature must be a number between 0 and 2"
        ):
            validate_request(payload)

    def test_validate_request_max_tokens_invalid(self):
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": -1,
        }
        with pytest.raises(ValueError, match="max_tokens must be a positive integer"):
            validate_request(payload)

    def test_validate_request_top_p_out_of_range(self):
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "top_p": 1.5,
        }
        with pytest.raises(ValueError, match="top_p must be a number between 0 and 1"):
            validate_request(payload)

    def test_validate_request_tools_not_list(self):
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "tools": "not-a-list",
        }
        with pytest.raises(ValueError, match="tools must be a list"):
            validate_request(payload)

    def test_validate_request_tool_choice_invalid(self):
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "tool_choice": 123,
        }
        with pytest.raises(
            ValueError, match="tool_choice must be a string, object, or null"
        ):
            validate_request(payload)

    def test_validate_request_response_format_not_dict(self):
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "response_format": "json",
        }
        with pytest.raises(ValueError, match="response_format must be an object"):
            validate_request(payload)

    def test_validate_request_metadata_not_dict(self):
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "metadata": "not-a-dict",
        }
        with pytest.raises(ValueError, match="metadata must be an object"):
            validate_request(payload)

    def test_validate_request_extra_fields_preserved(self):
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "custom_field": "custom_value",
        }
        validated = validate_request(payload)
        assert validated.extra_fields == {"custom_field": "custom_value"}

    def test_build_upstream_payload_includes_optional(self):
        validated = ValidatedRequest(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hello"}],
            temperature=0.7,
            max_tokens=100,
            top_p=0.9,
            tools=[{"type": "function"}],
            tool_choice="auto",
            response_format={"type": "json_object"},
            stream=False,
            metadata={"context": []},
            extra_fields={"custom": "value"},
        )
        payload = build_upstream_payload(validated)
        assert payload["model"] == "gpt-4"
        assert payload["temperature"] == 0.7
        assert payload["max_tokens"] == 100
        assert payload["top_p"] == 0.9
        assert payload["tools"] == [{"type": "function"}]
        assert payload["tool_choice"] == "auto"
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["custom"] == "value"

    def test_build_upstream_payload_excludes_none(self):
        validated = ValidatedRequest(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hello"}],
            temperature=None,
            max_tokens=None,
            top_p=None,
            tools=None,
            tool_choice=None,
            response_format=None,
            stream=False,
            metadata=None,
            extra_fields={},
        )
        payload = build_upstream_payload(validated)
        assert "temperature" not in payload
        assert "max_tokens" not in payload
        assert "top_p" not in payload
        assert "tools" not in payload
        assert "tool_choice" not in payload
        assert "response_format" not in payload


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
