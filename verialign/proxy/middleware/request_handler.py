from dataclasses import dataclass
from typing import Any


@dataclass
class ValidatedRequest:
    model: str
    messages: list[dict[str, Any]]
    temperature: float | None
    max_tokens: int | None
    top_p: float | None
    tools: list[dict] | None
    tool_choice: Any | None
    response_format: dict | None
    stream: bool
    metadata: dict | None
    extra_fields: dict


SUPPORTED_FIELDS = {
    "model",
    "messages",
    "temperature",
    "max_tokens",
    "top_p",
    "tools",
    "tool_choice",
    "response_format",
    "stream",
    "metadata",
    "user",
    "n",
    "presence_penalty",
    "frequency_penalty",
    "logit_bias",
    "logprobs",
    "top_logprobs",
    "stop",
    "seed",
}


def validate_request(payload: dict) -> ValidatedRequest:
    model = str(payload.get("model", "")).strip()
    if not model:
        msg = "model is required"
        raise ValueError(msg)

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        msg = "messages must be a non-empty list"
        raise ValueError(msg)

    for msg in messages:
        if not isinstance(msg, dict):
            msg_0 = "each message must be an object"
            raise ValueError(msg_0)  # noqa: TRY004
        if "role" not in msg or "content" not in msg:
            msg_0 = "each message must have role and content"
            raise ValueError(msg_0)

    stream = bool(payload.get("stream", False))

    temperature = payload.get("temperature")
    if temperature is not None:  # noqa: SIM102
        if not isinstance(temperature, (int, float)) or not (0 <= temperature <= 2):
            msg_0 = "temperature must be a number between 0 and 2"
            raise ValueError(msg_0)

    max_tokens = payload.get("max_tokens")
    if max_tokens is not None:  # noqa: SIM102
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            msg_0 = "max_tokens must be a positive integer"
            raise ValueError(msg_0)

    top_p = payload.get("top_p")
    if top_p is not None:  # noqa: SIM102
        if not isinstance(top_p, (int, float)) or not (0 <= top_p <= 1):
            msg_0 = "top_p must be a number between 0 and 1"
            raise ValueError(msg_0)

    tools = payload.get("tools")
    if tools is not None and not isinstance(tools, list):
        msg_0 = "tools must be a list"
        raise ValueError(msg_0)

    tool_choice = payload.get("tool_choice")
    if tool_choice is not None and not (
        isinstance(tool_choice, (str, dict)) or tool_choice is None
    ):
        msg_0 = "tool_choice must be a string, object, or null"
        raise ValueError(msg_0)

    response_format = payload.get("response_format")
    if response_format is not None and not isinstance(response_format, dict):
        msg_0 = "response_format must be an object"
        raise ValueError(msg_0)

    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        msg_0 = "metadata must be an object"
        raise ValueError(msg_0)

    extra_fields = {k: v for k, v in payload.items() if k not in SUPPORTED_FIELDS}

    return ValidatedRequest(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        tools=tools,
        tool_choice=tool_choice,
        response_format=response_format,
        stream=stream,
        metadata=metadata,
        extra_fields=extra_fields,
    )


def build_upstream_payload(validated: ValidatedRequest) -> dict:
    payload: dict = {
        "model": validated.model,
        "messages": validated.messages,
    }

    optional_fields = {
        "temperature": validated.temperature,
        "max_tokens": validated.max_tokens,
        "top_p": validated.top_p,
        "tools": validated.tools,
        "tool_choice": validated.tool_choice,
        "response_format": validated.response_format,
    }

    for key, value in optional_fields.items():
        if value is not None:
            payload[key] = value

    payload.update(validated.extra_fields)

    return payload
