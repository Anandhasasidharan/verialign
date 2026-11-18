"""Redact PII that spans deltas in an OpenAI-compatible chat stream."""

from verialign.privacy import JsonStreamRedactor, StreamRedactor, redact_pii

_TEXT_FIELDS = ("content", "refusal", "reasoning_content")


def _fragments(delta: dict):
    for field in _TEXT_FIELDS:
        if isinstance(delta.get(field), str):
            yield (field,), delta[field]
    call = delta.get("function_call")
    if isinstance(call, dict) and isinstance(call.get("arguments"), str):
        yield ("function_call",), call["arguments"]
    for tool in delta.get("tool_calls") or []:
        function = tool.get("function") or {}
        if isinstance(function.get("arguments"), str):
            yield ("tool_calls", tool.get("index", 0)), function["arguments"]


def _write_fragment(delta: dict, path: tuple, text: str) -> None:
    field = path[0]
    if field in _TEXT_FIELDS:
        delta[field] = text
    elif field == "function_call":
        delta.setdefault(field, {})["arguments"] = text
    else:
        index = path[1]
        calls = delta.setdefault(field, [])
        call = next((item for item in calls if item.get("index", 0) == index), None)
        if call is None:
            call = {"index": index}
            calls.append(call)
        call.setdefault("function", {})["arguments"] = text


class ChatStreamRedactor:
    def __init__(self, *, structured: bool = False) -> None:
        self._pending: dict[int, dict[tuple, StreamRedactor | JsonStreamRedactor]] = {}
        self._metadata: dict = {}
        self._structured = structured

    def feed(self, chunk: dict):
        masked = redact_pii(chunk)
        self._metadata.update({key: value for key, value in masked.items() if key != "choices"})
        endings = []
        for original, choice in zip(chunk.get("choices", []), masked.get("choices", [])):
            index = choice.get("index", 0)
            streams = self._pending.setdefault(index, {})
            if isinstance(original.get("delta"), dict):
                delta = choice["delta"]
                for path, text in _fragments(original["delta"]):
                    stream = streams.get(path)
                    if stream is None:
                        is_json = path[0] not in _TEXT_FIELDS or (
                            path[0] == "content" and self._structured
                        )
                        stream = streams[path] = (
                            JsonStreamRedactor() if is_json else StreamRedactor()
                        )
                    _write_fragment(delta, path, stream.feed(text))
            if choice.get("finish_reason") is not None:
                ending = self._finish(index)
                if ending:
                    endings.append(ending)
        if endings:
            yield {**self._metadata, "choices": endings}
        yield masked

    def flush(self):
        choices = [choice for index in list(self._pending) if (choice := self._finish(index))]
        if choices:
            yield {**self._metadata, "choices": choices}

    def _finish(self, index: int) -> dict | None:
        delta = {}
        for path, stream in self._pending.pop(index, {}).items():
            text = stream.feed("", final=True)
            if text:
                _write_fragment(delta, path, text)
        return {"index": index, "delta": delta, "finish_reason": None} if delta else None
