import contextvars
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from verialign.privacy import redact_text

RESERVED_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id",
    default="",
)
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def get_request_id() -> str:
    return request_id_var.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        rid = get_request_id()
        if rid:
            log_entry["request_id"] = rid
        for key, value in record.__dict__.items():
            if key not in RESERVED_ATTRS and not key.startswith("_"):
                log_entry[key] = value
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = record.exc_info[0].__name__
        return json.dumps(log_entry, default=str)


class _ServerExceptionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info:
            record.exc_info = None
            record.exc_text = None
        return True


_server_exception_filter = _ServerExceptionFilter()


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.root.handlers.clear()
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # The server access format includes the raw URL, including query parameters.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("uvicorn.error").addFilter(_server_exception_filter)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        provided = request.headers.get("X-Request-ID", "")
        request_id = (
            provided
            if _REQUEST_ID.fullmatch(provided) and redact_text(provided) == provided
            else uuid.uuid4().hex[:12]
        )
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.reset(token)
