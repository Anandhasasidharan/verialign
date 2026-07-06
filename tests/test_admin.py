import pytest
from fastapi.testclient import TestClient

from verialign.proxy.config import get_settings
from verialign.proxy.routing.cost_model import MODEL_PRICING
from verialign.proxy.main import app


@pytest.fixture(autouse=True)
def clear_state():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _headers() -> dict:
    return {"X-Admin-Key": "test-admin-key"}


def test_admin_disabled_without_key(monkeypatch):
    monkeypatch.delenv("VERIALIGN_ADMIN_API_KEY", raising=False)
    get_settings.cache_clear()
    client = TestClient(app)
    response = client.get("/admin/pricing")
    assert response.status_code == 503


def test_admin_wrong_key_returns_403(monkeypatch):
    monkeypatch.setenv("VERIALIGN_ADMIN_API_KEY", "real-key")
    get_settings.cache_clear()
    client = TestClient(app)
    response = client.get("/admin/pricing", headers={"X-Admin-Key": "wrong-key"})
    assert response.status_code == 403


def test_admin_valid_key_succeeds(monkeypatch):
    monkeypatch.setenv("VERIALIGN_ADMIN_API_KEY", "real-key")
    get_settings.cache_clear()
    client = TestClient(app)
    response = client.get("/admin/pricing", headers={"X-Admin-Key": "real-key"})
    assert response.status_code == 200


def test_admin_pricing_put(monkeypatch):
    monkeypatch.setenv("VERIALIGN_ADMIN_API_KEY", "test-admin-key")
    get_settings.cache_clear()
    client = TestClient(app)
    response = client.put(
        "/admin/pricing",
        json={"model": "gpt-5", "input_price": 5.0, "output_price": 20.0},
        headers=_headers(),
    )
    assert response.status_code == 200
    assert MODEL_PRICING["gpt-5"] == {"input": 5.0, "output": 20.0}
    get_response = client.get("/admin/pricing", headers=_headers())
    assert get_response.json()["models"]["gpt-5"] == {"input": 5.0, "output": 20.0}


def test_admin_pricing_put_requires_auth(monkeypatch):
    monkeypatch.setenv("VERIALIGN_ADMIN_API_KEY", "test-admin-key")
    get_settings.cache_clear()
    client = TestClient(app)
    response = client.put(
        "/admin/pricing",
        json={"model": "gpt-5", "input_price": 5.0, "output_price": 20.0},
    )
    assert response.status_code == 403
