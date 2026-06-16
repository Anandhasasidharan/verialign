import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class RequestBodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_size: int = 10 * 1024 * 1024) -> None:
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_size:
            logger.warning(
                "request_body_too_large",
                extra={"size": int(content_length), "limit": self.max_size},
            )
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "message": f"Request too large: max {self.max_size} bytes",
                        "type": "request_too_large",
                        "status_code": 413,
                    }
                },
            )
        return await call_next(request)
