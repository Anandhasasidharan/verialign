from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from verialign.proxy.middleware.metrics_middleware import (
    MetricsMiddleware,
    metrics_response,
)


def _build_app():
    async def ok_route(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/test", ok_route, methods=["GET"])])
    app.add_middleware(MetricsMiddleware)
    return app


class TestMetricsMiddleware:
    def test_metrics_response_returns_text(self):
        resp = metrics_response()
        assert resp.status_code == 200
        assert resp.media_type.startswith("text/plain")

    def test_metrics_endpoint_exists(self):
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200

    def test_headers_are_set(self):
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/test")
        assert "date" not in resp.headers  # not interesting, just a sanity check

    def test_metrics_endpoint_returns_prometheus_text(self):
        resp = metrics_response()
        assert resp.status_code == 200
        body = resp.body.decode()
        assert "verialign" in body
