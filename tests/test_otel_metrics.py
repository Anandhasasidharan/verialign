import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import State

from verialign.proxy import main as proxy
from verialign.proxy.config import Settings
from verialign.proxy.middleware import rate_limiter
from verialign.proxy.otel_metrics import TRUST_BUCKETS, TRUST_METRIC
from verialign.verification.engine import VerificationEngine
from verialign.verification.models import VerificationResult

pytest.importorskip("opentelemetry.exporter.otlp.proto.http")

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (  # noqa: E402
    ExportMetricsServiceRequest,
)


@pytest.fixture
def receiver():
    requests = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append((self.path, self.headers.get("X-API-Key"), body))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Receiver) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", requests
        finally:
            server.shutdown()
            thread.join()


def test_exports_real_histogram_and_agentops_json_without_content(receiver, tmp_path, monkeypatch):
    endpoint, requests = receiver
    for name in ("VERIALIGN_LOCAL_BASE_URL", "VERIALIGN_ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", f"{endpoint}/v1/metrics")
    monkeypatch.setenv("OTEL_METRICS_EXPORTER", "otlp")
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "none")
    monkeypatch.setenv("OTEL_METRIC_EXPORT_INTERVAL", "60000")
    settings = Settings(
        _env_file=None,
        db_path=str(tmp_path / "traces.sqlite3"),
        upstream_base_url=None,
        upstream_api_key=None,
        web_search_api_key=None,
        proxy_api_key=None,
        require_proxy_auth=False,
        enable_otel=True,
        agentops_traces_endpoint=f"{endpoint}/v1/traces",
        agentops_api_key="tenant-key-for-test",
        use_nli=False,
    )
    monkeypatch.setattr(proxy, "get_settings", lambda: settings)
    monkeypatch.setattr(proxy.app, "state", State())
    monkeypatch.setattr(rate_limiter, "_global_limiter", None)

    prompt = "private-canary"
    chat = {"model": "private-model-canary", "messages": [{"role": "user", "content": prompt}]}
    with TestClient(proxy.app) as client:
        warned = client.post(
            "/v1/chat/completions", json=chat, headers={"X-VeriAlign-Policy": "warn"}
        )
        assert warned.status_code == 200
        blocked = client.post(
            "/v1/chat/completions", json=chat, headers={"X-VeriAlign-Policy": "block"}
        )
        assert blocked.status_code == 422
        direct = client.post(
            "/v1/verify", json={"text": "Paris is in France.", "context": ["Paris is in France."]}
        )
        assert direct.status_code == 200
        streamed = client.post("/v1/chat/completions", json={**chat, "stream": True})
        assert streamed.status_code == 200
        assert streamed.text.rstrip().endswith("data: [DONE]")

        async def incomplete(self, *args, **kwargs):
            return VerificationResult([], [], [], incomplete=True)

        monkeypatch.setattr(VerificationEngine, "verify", incomplete)
        partial = client.post("/v1/verify", json={"text": prompt})
        assert partial.json()["verification"]["trust_score"] is None

    metric_exports = [
        ExportMetricsServiceRequest.FromString(body)
        for path, _, body in requests
        if path == "/v1/metrics"
    ]
    metrics = [
        metric
        for export in metric_exports
        for resource in export.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == TRUST_METRIC
    ]
    assert len(metrics) == 1
    assert metrics[0].unit == "1"
    histogram = metrics[0].histogram.data_points
    assert sum(p.count for p in histogram) == 4
    assert all(tuple(p.explicit_bounds) == TRUST_BUCKETS for p in histogram)
    labels = {
        frozenset((attr.key, attr.value.string_value) for attr in p.attributes) for p in histogram
    }
    assert labels == {
        frozenset({("verialign.operation", operation), ("verialign.policy_action", action)})
        for operation, action in (
            ("chat", "warn"),
            ("chat", "block"),
            ("chat_stream", "pass-through"),
            ("verify", "pass-through"),
        )
    }

    traces = []
    for path, key, body in requests:
        if path != "/v1/traces":
            continue
        assert key == "tenant-key-for-test"
        assert prompt.encode() not in body and b"private-model-canary" not in body
        traces.extend(json.loads(body)["resourceSpans"][0]["scopeSpans"][0]["spans"])
    assert len(traces) == 4
    assert all(len(bytes.fromhex(span["traceId"])) == 16 for span in traces)
    assert sorted(
        next(
            attr["value"]["doubleValue"]
            for attr in span["attributes"]
            if attr["key"] == "gen_ai.eval.trust_score"
        )
        for span in traces
    ) == pytest.approx(sorted(p.sum for p in histogram))
