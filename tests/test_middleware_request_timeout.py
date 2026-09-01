import asyncio

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from verialign.proxy.middleware.request_timeout import RequestTimeoutMiddleware


async def _slow_route(request):
    await asyncio.sleep(10)
    return JSONResponse({"ok": True})


async def _fast_route(request):
    return JSONResponse({"ok": True})


class TestRequestTimeoutMiddleware:
    def test_allows_fast_request(self) -> None:
        app = Starlette(routes=[Route("/fast", _fast_route, methods=["GET"])])
        app.add_middleware(RequestTimeoutMiddleware, timeout_seconds=5.0)
        client = TestClient(app)
        resp = client.get("/fast")
        assert resp.status_code == 200

    def test_times_out_slow_request(self) -> None:
        app = Starlette(routes=[Route("/slow", _slow_route, methods=["GET"])])
        app.add_middleware(RequestTimeoutMiddleware, timeout_seconds=0.05)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/slow")
        assert resp.status_code == 408
        body = resp.json()
        assert body["error"]["type"] == "timeout_error"
        assert body["error"]["status_code"] == 408

    def test_default_timeout(self) -> None:
        middleware = RequestTimeoutMiddleware(app=None)  # type: ignore
        assert middleware.timeout_seconds == 120.0

    def test_custom_timeout(self) -> None:
        middleware = RequestTimeoutMiddleware(app=None, timeout_seconds=30.0)  # type: ignore
        assert middleware.timeout_seconds == 30.0
