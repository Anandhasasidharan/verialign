import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Histogram, generate_latest, REGISTRY

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


request_count = Counter(
    "verialign_requests_total",
    "Total requests",
    ["method", "endpoint", "status"],
)

request_latency = Histogram(
    "verialign_request_duration_seconds",
    "Request latency in seconds",
    ["method", "endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

upstream_latency = Histogram(
    "verialign_upstream_duration_seconds",
    "Upstream LLM provider latency in seconds",
    ["provider"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        except Exception:
            status = "500"
            raise
        finally:
            elapsed = time.monotonic() - start
            request_count.labels(
                method=request.method, endpoint=request.url.path, status=status
            ).inc()
            request_latency.labels(
                method=request.method, endpoint=request.url.path
            ).observe(elapsed)


def metrics_response() -> Response:
    if not PROMETHEUS_AVAILABLE:
        return Response(
            content='# HELP verialign_info Prometheus client not installed\n# TYPE verialign_info gauge\nverialign_info{status="disabled"} 1\n',
            media_type="text/plain",
        )
    return Response(
        content=generate_latest(REGISTRY), media_type="text/plain; charset=utf-8"
    )
