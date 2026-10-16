"""Settings parsing and wiring of v2 toggles (use_rescoring, response policy)."""

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
