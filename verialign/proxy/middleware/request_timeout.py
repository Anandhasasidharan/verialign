import asyncio
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, timeout_seconds: float = 120.0) -> None:
        super().__init__(app)
        self.timeout_seconds = timeout_seconds

    async def dispatch(self, request: Request, call_next):
        try:
            response = await asyncio.wait_for(
                call_next(request), timeout=self.timeout_seconds
            )
            return response
        except asyncio.TimeoutError:
            logger.warning(
                "request_timeout",
                extra={"path": str(request.url.path), "timeout": self.timeout_seconds},
            )
            return JSONResponse(
                status_code=408,
                content={
                    "error": {
                        "message": f"Request timed out after {self.timeout_seconds}s",
                        "type": "timeout_error",
                        "status_code": 408,
                    }
                },
            )
