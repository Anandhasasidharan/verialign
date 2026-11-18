import json
import shlex
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.datastructures import State

from verialign.proxy.config import get_settings
from verialign.proxy.main import app
from verialign.proxy.middleware import rate_limiter
from verialign.verification.engine import VerificationEngine
from verialign.verification.overlay import ClaimResult, Overlay


@pytest.fixture
def demo_client(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "state", State())
    monkeypatch.setattr(rate_limiter, "_global_limiter", None)
    for name in ("UPSTREAM_BASE_URL", "ANTHROPIC_API_KEY", "LOCAL_BASE_URL", "VALKEY_URL"):
        monkeypatch.delenv(f"VERIALIGN_{name}", raising=False)
    monkeypatch.setenv("VERIALIGN_DATABASE_URL", "sqlite:///./verialign.sqlite3")
    monkeypatch.setenv("VERIALIGN_DB_PATH", str(tmp_path / "traces.sqlite3"))
    monkeypatch.setenv("VERIALIGN_USE_NLI", "false")
    monkeypatch.setenv("VERIALIGN_REQUIRE_PROXY_AUTH", "false")
    monkeypatch.setenv("VERIALIGN_RESPONSE_POLICY", "pass-through")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        get_settings.cache_clear()


@pytest.fixture
def readme_request():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    quickstart = readme.split("Demo request without an upstream provider:", 1)[1]
    curl = quickstart.split("```bash", 1)[1].split("```", 1)[0]
    args = shlex.split(curl.replace("\\\n", ""))
    return args[args.index("-d") + 1]


@pytest.mark.parametrize(
    ("action", "status_code", "overlay_key"),
    [("pass-through", 200, "verification"), ("warn", 200, "verification"), ("block", 422, "data")],
)
def test_readme_curl_returns_valid_overlay(
    demo_client, readme_request, action, status_code, overlay_key
):
    body = json.loads(readme_request)
    if overlay_key == "data":
        body["response_format"] = {"type": "json_object"}
    headers = (
        {"X-VeriAlign-Policy": action, "X-VeriAlign-Block-Threshold": "1"}
        if action != "pass-through"
        else None
    )
    response = demo_client.post(
        "/v1/chat/completions",
        json=body,
        headers=headers,
    )

    assert response.status_code == status_code
    result = response.json()
    payload = result[overlay_key]
    overlay = Overlay.model_validate(payload)
    assert overlay.policy_action == action
    assert overlay.status == "complete"
    assert overlay.trust_score == payload["summary"]["trust_score"]
    assert {claim.label for claim in overlay.claims} == {"verified", "no_source"}
    assert overlay.claims[0].evidence[0].source_id == "doc-1"
    assert payload["claims"][0]["status"] == "supported"
    assert payload["claims"][0]["sources"] == payload["claims"][0]["evidence"]
    if action == "pass-through":
        assert result["choices"][0]["message"]["content"].startswith(overlay.claims[0].text)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_claim_confidence_must_be_in_range(confidence):
    with pytest.raises(ValidationError, match="confidence"):
        ClaimResult(text="A claim.", label="unverifiable", confidence=confidence, evidence=[])


@pytest.mark.parametrize("error", [RuntimeError, TimeoutError])
def test_verification_error_preserves_readme_completion(
    demo_client, readme_request, monkeypatch, error
):
    original = demo_client.post("/v1/chat/completions", json=json.loads(readme_request))
    monkeypatch.setattr(VerificationEngine, "verify", AsyncMock(side_effect=error))
    response = demo_client.post(
        "/v1/chat/completions",
        json=json.loads(readme_request),
        headers={"X-VeriAlign-Policy": "block", "X-VeriAlign-Block-Threshold": "1"},
    )

    assert response.status_code == 200
    assert response.json()["choices"] == original.json()["choices"]
    overlay = Overlay.model_validate(response.json()["verification"])
    assert overlay.status == "unverifiable"
    assert overlay.policy_action == "pass-through"
    assert overlay.trust_score is None
    assert overlay.claims == []

    response = demo_client.post("/v1/verify", json={"text": "A claim."})
    assert response.status_code == 200
    assert Overlay.model_validate(response.json()["verification"]).status == "unverifiable"


def test_direct_verification_labels_both_claims_in_a_detected_conflict(demo_client):
    response = demo_client.post(
        "/v1/verify",
        json={"text": "The system is secure. The system is not secure."},
    )
    assert response.status_code == 200
    overlay = Overlay.model_validate(response.json()["verification"])
    assert len(overlay.claims) == 2
    assert all(claim.label == "contradicted" for claim in overlay.claims)


def test_trace_write_error_preserves_completion(demo_client, readme_request, monkeypatch):
    monkeypatch.setattr("verialign.proxy.main._write_trace", AsyncMock(side_effect=RuntimeError))
    response = demo_client.post("/v1/chat/completions", json=json.loads(readme_request))
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["role"] == "assistant"
    assert Overlay.model_validate(response.json()["verification"]).status == "complete"
