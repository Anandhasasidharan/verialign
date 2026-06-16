import io
import json
import logging
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from verialign.proxy.middleware.logging_middleware import (
    JsonFormatter,
    configure_logging,
    CorrelationIdMiddleware,
    get_request_id,
    request_id_var,
)


class TestJsonFormatter:
    def setup_method(self):
        self.formatter = JsonFormatter()
        self.logger = logging.getLogger("test_json")
        self.logger.handlers.clear()
        self.logger.propagate = False
        self.buf = io.StringIO()
        handler = logging.StreamHandler(self.buf)
        handler.setFormatter(self.formatter)
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

    def test_basic_format(self):
        self.logger.info("hello world")
        output = self.buf.getvalue()
        entry = json.loads(output)
        assert entry["message"] == "hello world"
        assert entry["level"] == "INFO"
        assert "timestamp" in entry
        assert "logger" in entry
        assert "module" in entry

    def test_extra_fields_included(self):
        self.logger.info("test", extra={"user_id": "abc", "count": 42})
        output = self.buf.getvalue()
        entry = json.loads(output)
        assert entry["user_id"] == "abc"
        assert entry["count"] == 42

    def test_reserved_attrs_excluded(self):
        import logging as _logging

        record = _logging.LogRecord(
            name="test",
            level=_logging.INFO,
            pathname="",
            lineno=0,
            msg="test msg",
            args=(),
            exc_info=None,
        )
        record.asctime = "should_not_appear"
        record.funcName = "should_not_appear"
        output = self.formatter.format(record)
        entry = json.loads(output)
        assert "asctime" not in entry
        assert "funcName" not in entry

    def test_request_id_included_when_set(self):
        request_id_var.set("req-123")
        try:
            self.logger.info("with request id")
        finally:
            request_id_var.set("")
        output = self.buf.getvalue()
        entry = json.loads(output)
        assert entry["request_id"] == "req-123"

    def test_request_id_omitted_when_empty(self):
        request_id_var.set("")
        self.logger.info("no request id")
        output = self.buf.getvalue()
        entry = json.loads(output)
        assert "request_id" not in entry


def _build_app():
    async def ok_route(request):
        return JSONResponse({"ok": True, "request_id": get_request_id()})

    app = Starlette(routes=[Route("/test", ok_route, methods=["GET"])])
    app.add_middleware(CorrelationIdMiddleware)
    return app


class TestCorrelationIdMiddleware:
    def test_sets_request_id_header_on_response(self):
        client = TestClient(_build_app())
        resp = client.get("/test")
        assert "x-request-id" in resp.headers
        assert len(resp.headers["x-request-id"]) > 0

    def test_uses_client_request_id_when_provided(self):
        client = TestClient(_build_app())
        resp = client.get("/test", headers={"X-Request-ID": "my-trace-id"})
        assert resp.headers["x-request-id"] == "my-trace-id"

    def test_generates_id_when_not_provided(self):
        client = TestClient(_build_app())
        resp = client.get("/test")
        rid = resp.headers["x-request-id"]
        assert len(rid) == 12
        assert rid.isalnum()

    def test_request_id_accessible_via_contextvar(self):
        client = TestClient(_build_app())
        resp = client.get("/test")
        body = resp.json()
        assert body["request_id"] == resp.headers["x-request-id"]

    def test_different_requests_get_different_ids(self):
        client = TestClient(_build_app())
        resp1 = client.get("/test", headers={"X-Request-ID": "id-1"})
        resp2 = client.get("/test", headers={"X-Request-ID": "id-2"})
        assert resp1.headers["x-request-id"] == "id-1"
        assert resp2.headers["x-request-id"] == "id-2"

    def test_configure_logging_does_not_raise(self):
        configure_logging()
        logging.info("post-configure test")
