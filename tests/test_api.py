import pytest
from fastapi.testclient import TestClient

from verialign.proxy.config import get_settings
from verialign.proxy.main import app


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_health():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_chat_completion_adds_verification(tmp_path, monkeypatch):
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
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert "verification" in body
    assert body["verification"]["summary"]["total_claims"] >= 1

    trace_response = client.get("/traces?limit=10")
    assert trace_response.status_code == 200
    traces_data = trace_response.json()
    assert len(traces_data["traces"]) == 1
    assert traces_data["traces"][0]["model"] == "demo"
    assert traces_data["traces"][0]["summary"]["total_claims"] >= 1


def test_chat_completion_streaming_returns_events(tmp_path, monkeypatch):
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
    assert "chatcmpl-demo-" in body


def test_chat_completion_uses_demo_mode_without_provider_env(tmp_path, monkeypatch):
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
            "messages": [{"role": "user", "content": "Use demo mode."}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"].startswith("chatcmpl-demo-")
    assert body["model"] == "demo"


def test_chat_completion_requires_auth_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIALIGN_DB_PATH", str(tmp_path / "traces.sqlite3"))
    monkeypatch.setenv("VERIALIGN_PROXY_API_KEY", "test-secret-key")
    monkeypatch.setenv("VERIALIGN_REQUIRE_PROXY_AUTH", "true")
    get_settings.cache_clear()

    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "demo",
            "messages": [{"role": "user", "content": "Test"}],
        },
    )

    assert response.status_code == 401


def test_chat_completion_works_with_valid_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIALIGN_DB_PATH", str(tmp_path / "traces.sqlite3"))
    monkeypatch.setenv("VERIALIGN_PROXY_API_KEY", "test-secret-key")
    monkeypatch.setenv("VERIALIGN_REQUIRE_PROXY_AUTH", "true")
    monkeypatch.delenv("VERIALIGN_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("VERIALIGN_UPSTREAM_API_KEY", raising=False)
    get_settings.cache_clear()

    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-secret-key"},
        json={
            "model": "demo",
            "messages": [{"role": "user", "content": "Test"}],
        },
    )

    assert response.status_code == 200
