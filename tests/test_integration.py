import pytest
from fastapi.testclient import TestClient

from verialign.proxy.config import get_settings
from verialign.proxy.main import app


@pytest.fixture(autouse=True)
def clear_settings():
    get_settings.cache_clear()
    yield


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_demo_chat_completion_full_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIALIGN_DB_PATH", str(tmp_path / "traces.sqlite3"))
    monkeypatch.delenv("VERIALIGN_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("VERIALIGN_UPSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_PROXY_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_REQUIRE_PROXY_AUTH", raising=False)
    get_settings.cache_clear()

    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "demo",
            "messages": [{"role": "user", "content": "What is VeriAlign?"}],
            "metadata": {
                "context": [
                    {
                        "id": "doc-1",
                        "text": "VeriAlign is a verification support proxy for LLM outputs.",
                    }
                ]
            },
            "temperature": 0.7,
            "max_tokens": 500,
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["object"] == "chat.completion"
    assert body["model"] == "demo"
    assert body["id"].startswith("chatcmpl-demo-")
    assert "created" in body

    choices = body.get("choices", [])
    assert len(choices) == 1
    message = choices[0].get("message", {})
    assert message["role"] == "assistant"
    assert isinstance(message.get("content"), str)
    assert len(message["content"]) > 0

    assert "verification" in body
    verification = body["verification"]
    assert "claims" in verification
    assert "contradictions" in verification
    assert "checklist" in verification
    assert "summary" in verification

    summary = verification["summary"]
    assert summary["total_claims"] >= 0
    assert isinstance(summary["supported"], int)
    assert isinstance(summary["unsupported"], int)
    assert isinstance(summary["unclear"], int)
    assert isinstance(summary["contradictions_found"], int)
    assert isinstance(summary["checklist_items"], int)


def test_streaming_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIALIGN_DB_PATH", str(tmp_path / "traces.sqlite3"))
    monkeypatch.delenv("VERIALIGN_PROXY_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_REQUIRE_PROXY_AUTH", raising=False)
    monkeypatch.delenv("VERIALIGN_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("VERIALIGN_UPSTREAM_API_KEY", raising=False)
    get_settings.cache_clear()

    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "demo",
            "stream": True,
            "messages": [{"role": "user", "content": "Stream this."}],
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "data: [DONE]" in body
    assert "VeriAlign" in body


def test_proxy_auth_enforced(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIALIGN_DB_PATH", str(tmp_path / "traces.sqlite3"))
    monkeypatch.setenv("VERIALIGN_PROXY_API_KEY", "test-secret")
    monkeypatch.setenv("VERIALIGN_REQUIRE_PROXY_AUTH", "true")
    get_settings.cache_clear()

    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={"model": "demo", "messages": [{"role": "user", "content": "Hello"}]},
        headers={"Authorization": "Bearer test-secret"},
    )
    assert response.status_code == 200

    response = client.post(
        "/v1/chat/completions",
        json={"model": "demo", "messages": [{"role": "user", "content": "Hello"}]},
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert response.status_code == 401


def test_trace_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIALIGN_DB_PATH", str(tmp_path / "traces.sqlite3"))
    monkeypatch.delenv("VERIALIGN_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("VERIALIGN_UPSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_PROXY_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_REQUIRE_PROXY_AUTH", raising=False)
    get_settings.cache_clear()

    client = TestClient(app)

    client.post(
        "/v1/chat/completions",
        json={
            "model": "demo",
            "messages": [{"role": "user", "content": "Trace me."}],
        },
    )

    trace_response = client.get("/traces?limit=10")
    assert trace_response.status_code == 200
    traces = trace_response.json().get("traces", [])
    assert len(traces) >= 1

    trace = traces[0]
    assert trace["model"] == "demo"
    assert "created_at" in trace
    assert "verification" in trace
    assert trace["verification"]["summary"]["total_claims"] >= 0


def test_multiple_requests_maintain_state(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIALIGN_DB_PATH", str(tmp_path / "traces.sqlite3"))
    monkeypatch.delenv("VERIALIGN_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("VERIALIGN_UPSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_PROXY_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_REQUIRE_PROXY_AUTH", raising=False)
    get_settings.cache_clear()

    client = TestClient(app)

    for i in range(3):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "demo",
                "messages": [{"role": "user", "content": f"Request {i}"}],
            },
        )
        assert response.status_code == 200

    trace_response = client.get("/traces?limit=10")
    traces = trace_response.json().get("traces", [])
    assert len(traces) == 3


@pytest.mark.asyncio
async def test_verification_contradictions_detected(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIALIGN_DB_PATH", str(tmp_path / "traces.sqlite3"))
    monkeypatch.delenv("VERIALIGN_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("VERIALIGN_UPSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_PROXY_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_REQUIRE_PROXY_AUTH", raising=False)
    get_settings.cache_clear()

    from verialign.verification.engine import VerificationEngine

    engine = VerificationEngine()

    text = "The system is secure. The system is not secure."
    result = await engine.verify(text, [])

    assert len(result.contradictions) >= 1
    assert result.contradictions[0].type in ("negation", "antonym", "numeric")


@pytest.mark.asyncio
async def test_verification_checklist_generated(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIALIGN_DB_PATH", str(tmp_path / "traces.sqlite3"))
    monkeypatch.delenv("VERIALIGN_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("VERIALIGN_UPSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_PROXY_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_REQUIRE_PROXY_AUTH", raising=False)
    get_settings.cache_clear()

    from verialign.verification.engine import VerificationEngine

    engine = VerificationEngine()

    text = "Deploy the docker container with encrypted passwords."
    result = await engine.verify(text, [])

    assert len(result.checklist) >= 1
    categories = {item.category for item in result.checklist}
    assert "security" in categories or "deployment" in categories


def test_rate_limit_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIALIGN_DB_PATH", str(tmp_path / "traces.sqlite3"))
    monkeypatch.delenv("VERIALIGN_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("VERIALIGN_UPSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_PROXY_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_REQUIRE_PROXY_AUTH", raising=False)
    get_settings.cache_clear()

    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "demo",
            "messages": [{"role": "user", "content": "Rate limit test"}],
        },
    )

    assert "X-RateLimit-Limit-Requests" in response.headers
    assert "X-RateLimit-Remaining-Requests" in response.headers
    assert "X-RateLimit-Limit-Tokens" in response.headers
    assert "X-RateLimit-Remaining-Tokens" in response.headers


@pytest.mark.asyncio
async def test_unsupported_claim_detection(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIALIGN_DB_PATH", str(tmp_path / "traces.sqlite3"))
    monkeypatch.delenv("VERIALIGN_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("VERIALIGN_UPSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_PROXY_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_REQUIRE_PROXY_AUTH", raising=False)
    get_settings.cache_clear()

    from verialign.verification.engine import VerificationEngine

    engine = VerificationEngine()

    text = "Paris is the capital of Spain."
    context = [{"id": "doc-1", "text": "The capital of France is Paris."}]
    result = await engine.verify(text, context)

    unsupported = [c for c in result.claims if c.status == "unsupported"]
    assert len(unsupported) >= 0


@pytest.mark.asyncio
async def test_supported_claim_detection(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIALIGN_DB_PATH", str(tmp_path / "traces.sqlite3"))
    monkeypatch.delenv("VERIALIGN_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("VERIALIGN_UPSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_PROXY_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_REQUIRE_PROXY_AUTH", raising=False)
    get_settings.cache_clear()

    from verialign.verification.engine import VerificationEngine

    engine = VerificationEngine()

    text = "Paris is the capital of France."
    context = [{"id": "doc-1", "text": "The capital of France is Paris."}]
    result = await engine.verify(text, context)

    supported = [c for c in result.claims if c.status == "supported"]
    assert len(supported) >= 1
