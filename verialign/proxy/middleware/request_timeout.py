import asyncio
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class RequestTimeoutMiddleware:
    def __init__(self, app: ASGIApp, timeout_seconds: float = 120.0) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        timeout = asyncio.timeout(self.timeout_seconds)
        scope.setdefault("state", {})["proxy_timeout"] = timeout

        async def send_response(message: Message) -> None:
            if message["type"] == "http.response.start":
                timeout.reschedule(None)
            await send(message)

        try:
            async with timeout:
                await self.app(scope, receive, send_response)
        except asyncio.TimeoutError:
            if not timeout.expired():
                raise
            logger.warning(
                "request_timeout",
                extra={"path": scope["path"], "timeout": self.timeout_seconds},
            )
            response = JSONResponse(
                status_code=408,
                content={
                    "error": {
                        "message": f"Request timed out after {self.timeout_seconds}s",
                        "type": "timeout_error",
                        "status_code": 408,
                    },
                },
            )
            await response(scope, receive, send)


def verification_window(request: Request, max_ms: int) -> float:
    """Give the response path its own timeout after upstream work has succeeded."""
    seconds = max_ms / 1000
    timeout = getattr(request.state, "proxy_timeout", None)
    if timeout is None or timeout.when() is None:
        return seconds
    remaining = timeout.when() - asyncio.get_running_loop().time()
    timeout.reschedule(None)
    return max(0.0, min(seconds, remaining))
