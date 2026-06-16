from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from verialign.proxy.middleware.body_size_limit import RequestBodySizeLimitMiddleware


def _build_app(max_size: int):
    async def ok_route(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/test", ok_route, methods=["POST"])])
    app.add_middleware(RequestBodySizeLimitMiddleware, max_size=max_size)
    return app


class TestRequestBodySizeLimitMiddleware:
    def test_allows_body_under_limit(self):
        app = _build_app(max_size=100)
        client = TestClient(app)
        resp = client.post("/test", json={"data": "x" * 10})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_rejects_body_over_limit(self):
        app = _build_app(max_size=20)
        client = TestClient(app)
        resp = client.post(
            "/test",
            content=b'{"data": "' + b"x" * 50 + b'"}',
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 413
        body = resp.json()
        assert body["error"]["type"] == "request_too_large"
        assert body["error"]["status_code"] == 413

    def test_default_size_is_10mb(self):
        middleware = RequestBodySizeLimitMiddleware(app=None)  # type: ignore
        assert middleware.max_size == 10 * 1024 * 1024

    def test_no_content_length_header_allowed(self):
        app = _build_app(max_size=10)
        client = TestClient(app)
        resp = client.post(
            "/test", content=b"", headers={"content-type": "application/json"}
        )
        assert resp.status_code == 200
