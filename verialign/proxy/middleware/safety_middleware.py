"""Request guardrails and JSON response redaction."""

import json
import logging
import re
from collections.abc import Iterator

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from verialign.privacy import _luhn_valid as _luhn_valid
from verialign.privacy import _redact_credit_cards as _redact_credit_cards
from verialign.privacy import redact_pii

logger = logging.getLogger(__name__)

_JAILBREAK_RE = re.compile(
    r"\b(?:ignore\s+(?:all\s+)?(?:prior|previous|above)\s+instructions"
    r"|(?:reveal|show|print|repeat|disclose)\s+(?:me\s+)?(?:your|the)\s+"
    r"(?:hidden\s+)?system\s+prompt"
    r"|act\s+as\s+(?:dan|jailbroken|unfiltered)"
    r"|bypass\s+(?:the\s+)?(?:safety|filter|guardrail))\b",
    re.IGNORECASE,
)
_TOXIC_WORD_RE = re.compile(r"\b(?:hate|murder|torture|abuse)\b", re.IGNORECASE)
_TOXIC_DIRECTED_RE = re.compile(
    r"\b(?:(?:i|we)\s+(?:hate|(?:will|want\s+to)\s+(?:murder|torture|abuse))\s+you"
    r"|you\s+deserve\s+(?:abuse|torture))\b",
    re.IGNORECASE,
)
_GUARDED_PATHS = {"/v1/chat/completions", "/v1/verify"}


def _user_text(payload: dict, path: str) -> Iterator[str]:
    if path == "/v1/verify":
        if isinstance(payload.get("text"), str):
            yield payload["text"]
        return
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            yield content
        elif isinstance(content, list):
            yield " ".join(
                part["text"]
                for part in content
                if isinstance(part, dict)
                and part.get("type") in {"text", "input_text"}
                and isinstance(part.get("text"), str)
            )


class SafetyMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        pii_redact: bool = True,
        jailbreak_block: bool = True,
        toxicity_block: bool = True,
        toxicity_score: float = 0.0,
        max_body_size: int = 10 * 1024 * 1024,
    ) -> None:
        self.app = app
        self.pii_redact = pii_redact
        self.jailbreak_block = jailbreak_block
        self.toxicity_block = toxicity_block
        self.toxicity_score = toxicity_score
        self.max_body_size = max_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"].rstrip("/")
        guarded = scope["method"] == "POST" and path in _GUARDED_PATHS
        if guarded:
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > self.max_body_size:
                    response = JSONResponse(
                        {
                            "error": {
                                "message": "Request body exceeds the configured limit",
                                "type": "request_too_large",
                                "status_code": 413,
                            }
                        },
                        status_code=413,
                    )
                    await response(scope, receive, send)
                    return
                if not message.get("more_body"):
                    break
            raw = bytes(body)
            rejection = self._blocked(raw, path)
            if rejection:
                await rejection(scope, receive, send)
                return

            consumed = False

            async def replay() -> Message:
                nonlocal consumed
                if consumed:
                    return await receive()
                consumed = True
                return {"type": "http.request", "body": raw}

            body_receive = replay
        else:
            body_receive = receive

        if self.pii_redact:
            await self._with_json_redaction(scope, body_receive, send)
        else:
            await self.app(scope, body_receive, send)

    def _blocked(self, raw: bytes, path: str) -> JSONResponse | None:
        if not raw or not (self.jailbreak_block or self.toxicity_block):
            return None
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(payload, dict):
            return None

        for text in _user_text(payload, path):
            if self.jailbreak_block and _JAILBREAK_RE.search(text):
                return self._reject("jailbreak", path)
            if self.toxicity_block and len(_TOXIC_DIRECTED_RE.findall(text)) > self.toxicity_score:
                return self._reject("toxicity", path)
        return None

    @staticmethod
    def _reject(reason: str, path: str) -> JSONResponse:
        logger.warning("guardrail_triggered", extra={"path": path, "reason": reason})
        return JSONResponse(
            {
                "error": {
                    "message": f"Prompt blocked: {reason} detected",
                    "type": "safety",
                    "status_code": 403,
                }
            },
            status_code=403,
        )

    async def _with_json_redaction(self, scope: Scope, receive: Receive, send: Send) -> None:
        pending_start = None
        chunks: list[bytes] = []

        async def redact_send(message: Message) -> None:
            nonlocal pending_start
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                media_type = headers.get("content-type", "").split(";", 1)[0].lower().strip()
                if media_type == "application/json" or media_type.endswith("+json"):
                    pending_start = message
                    return
            elif message["type"] == "http.response.body" and pending_start is not None:
                chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                body = b"".join(chunks)
                output = body
                try:
                    payload = json.loads(body)
                    masked = redact_pii(payload)
                    if masked != payload:
                        output = JSONResponse(masked).body
                except (ValueError, UnicodeDecodeError):
                    pass
                if output != body:
                    headers = MutableHeaders(scope=pending_start)
                    headers["content-length"] = str(len(output))
                    if "etag" in headers:
                        del headers["etag"]
                await send(pending_start)
                pending_start = None
                message = {**message, "body": output}
            await send(message)

        await self.app(scope, receive, redact_send)
