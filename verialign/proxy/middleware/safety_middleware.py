"""PII redaction, jailbreak detection, and toxicity guardrail middleware."""

from __future__ import annotations

import json
import re
import logging
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

logger = logging.getLogger(__name__)

PII_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "phone": re.compile(r"\b\+?1?\d{10,15}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
}

JAILBREAK_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?(prior|previous|above)\s+instructions", re.I),
    re.compile(r"you\s+are\s+(now|free|not\s+bound)", re.I),
    re.compile(r"system\s+prompt", re.I),
    re.compile(r"act\s+as\s+(dan|jailbroken|unfiltered)", re.I),
    re.compile(
        r"do\s+(not\s+)?have\s+(any\s+)?(restrictions|limitations|guidelines)", re.I
    ),
    re.compile(r"output\s+raw\s+(text|data|json)", re.I),
    re.compile(r"bypass\s+(safety|filter|guardrail)", re.I),
]

TOXIC_KEYWORDS: list[str] = [
    "hate",
    "kill",
    "die",
    "murder",
    "torture",
    "abuse",
    "attack",
]


class SafetyMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        pii_redact: bool = True,
        jailbreak_block: bool = True,
        toxicity_block: bool = True,
        toxicity_score: float = 0.0,
    ) -> None:
        super().__init__(app)
        self.pii_redact = pii_redact
        self.jailbreak_block = jailbreak_block
        self.toxicity_block = toxicity_block
        self.toxicity_score = toxicity_score

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if self.jailbreak_block:
            body = await request.body()
            if body:
                text = body.decode("utf-8", errors="replace").lower()
                for pattern in JAILBREAK_PATTERNS:
                    if pattern.search(text):
                        logger.warning(
                            "jailbreak_detected", extra={"path": str(request.url)}
                        )
                        return JSONResponse(
                            status_code=403,
                            content={
                                "error": {
                                    "message": "Prompt blocked: jailbreak detected",
                                    "type": "safety",
                                    "status_code": 403,
                                }
                            },
                        )
                if self.toxicity_block:
                    toxicity_hits = sum(kw in text for kw in TOXIC_KEYWORDS)
                    if toxicity_hits > self.toxicity_score:
                        logger.warning(
                            "toxicity_detected",
                            extra={"path": str(request.url), "hits": toxicity_hits},
                        )
                        return JSONResponse(
                            status_code=403,
                            content={
                                "error": {
                                    "message": "Prompt blocked: toxic content detected",
                                    "type": "safety",
                                    "status_code": 403,
                                }
                            },
                        )

        response = await call_next(request)

        if (
            self.pii_redact
            and response.status_code == 200
            and hasattr(response, "body")
            and callable(response.body)
        ):
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                body = await response.body()
                if body:
                    text = body.decode("utf-8", errors="replace")
                    redacted = text
                    for name, pattern in PII_PATTERNS.items():
                        redacted = pattern.sub(f"[REDACTED_{name.upper()}]", redacted)
                    if redacted != text:
                        logger.info("pii_redacted", extra={"path": str(request.url)})
                        return JSONResponse(
                            status_code=200,
                            content=json.loads(redacted),
                            headers=dict(response.headers),
                        )
        return response
