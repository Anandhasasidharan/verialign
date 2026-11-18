"""Settings parsing and wiring of v2 toggles (use_rescoring, response policy)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from verialign.proxy import main as main_module
from verialign.proxy.config import Settings, get_settings
from verialign.proxy.main import app


class _FakeResult:
    def to_dict(self) -> dict:
        return {"claims": [], "summary": {"total_claims": 0}}


class _RecordingEngine:
    """Captures constructor kwargs and returns a minimal verification result."""

    captured: list[dict] = []

    def __init__(self, **kwargs) -> None:
        _RecordingEngine.captured.append(kwargs)

    async def verify(self, text, context, **kwargs) -> _FakeResult:
        return _FakeResult()


# Defaults are asserted from the model fields so a local .env file cannot skew them.
def test_use_rescoring_defaults_off() -> None:
    assert Settings.model_fields["use_rescoring"].default is False


def test_response_policy_defaults() -> None:
    assert Settings.model_fields["response_policy"].default == "pass-through"
    assert Settings.model_fields["block_threshold"].default == 0.5


def test_cors_default_is_empty() -> None:
    factory = Settings.model_fields["cors_allowed_origins"].default_factory
    assert factory() == []


def test_use_rescoring_env_override(monkeypatch) -> None:
    monkeypatch.setenv("VERIALIGN_USE_RESCORING", "true")
    get_settings.cache_clear()
    assert get_settings().use_rescoring is True


def test_verify_endpoint_wires_use_rescoring(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VERIALIGN_DB_PATH", str(tmp_path / "traces.sqlite3"))
    monkeypatch.setenv("VERIALIGN_USE_RESCORING", "true")
    monkeypatch.delenv("VERIALIGN_PROXY_API_KEY", raising=False)
    monkeypatch.delenv("VERIALIGN_REQUIRE_PROXY_AUTH", raising=False)
    get_settings.cache_clear()

    _RecordingEngine.captured = []
    monkeypatch.setattr(main_module, "VerificationEngine", _RecordingEngine)

    client = TestClient(app)
    response = client.post("/v1/verify", json={"text": "Hello world."})

    assert response.status_code == 200
    assert _RecordingEngine.captured, "engine was not constructed"
    assert _RecordingEngine.captured[0]["use_rescoring"] is True


@pytest.mark.parametrize(
    ("enabled", "override", "expected_model"),
    [(False, "extractor", None), (True, "extractor", "extractor"), (True, None, "request")],
)
def test_verify_endpoint_opts_in_to_model_extraction(
    monkeypatch, enabled, override, expected_model
) -> None:
    settings = Settings(
        _env_file=None,
        use_llm_extractor=enabled,
        llm_extractor_model=override,
        proxy_api_key="extractor-test",
        use_nli=False,
        require_proxy_auth=False,
    )
    model = AsyncMock(
        return_value=SimpleNamespace(
            data={"choices": [{"message": {"content": '{"claim_indices":[0]}'}}]}
        )
    )
    router = SimpleNamespace(get_configured_providers=lambda: [object()], chat_completions=model)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "ProviderRouter", lambda _: router)

    response = TestClient(app, headers={"Authorization": "Bearer extractor-test"}).post(
        "/v1/verify", json={"text": "Ana speaks three languages.", "model": "request"}
    )
    assert response.status_code == 200
    claims = response.json()["verification"]["claims"]
    if expected_model is None:
        model.assert_not_called()
        assert claims == []
    else:
        assert model.await_args.args[0]["model"] == expected_model
        assert claims[0]["text"] == "Ana speaks three languages."
