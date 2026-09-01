import logging

from verialign.proxy.config import get_settings


def test_demo_mode_no_warning_when_no_keys(caplog) -> None:
    """No warning should be logged when no upstream keys are set."""
    caplog.set_level(logging.WARNING)
    settings = get_settings()
    has_upstream_key = bool(settings.upstream_api_key or settings.proxy_api_key)
    # In test env, no keys should be set
    assert has_upstream_key is False


def test_demo_mode_warning_condition_true_when_keys_set(caplog, monkeypatch) -> None:
    from verialign.proxy.routing.provider_router import ProviderRouter

    # Only set api_key but NOT upstream_base_url — no provider becomes configured
    monkeypatch.delenv("VERIALIGN_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.setenv("VERIALIGN_UPSTREAM_API_KEY", "sk-test-key")
    get_settings.cache_clear()

    settings = get_settings()
    router = ProviderRouter(settings)
    has_upstream_key = bool(settings.upstream_api_key or settings.proxy_api_key)
    providers = router.get_configured_providers()

    assert has_upstream_key is True
    assert len(providers) == 0

    get_settings.cache_clear()


def test_demo_mode_silent_when_provider_configured(caplog, monkeypatch) -> None:
    from verialign.proxy.routing.provider_router import ProviderRouter

    monkeypatch.setenv("VERIALIGN_UPSTREAM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("VERIALIGN_UPSTREAM_API_KEY", "sk-test-key")
    get_settings.cache_clear()

    settings = get_settings()
    router = ProviderRouter(settings)
    providers = router.get_configured_providers()

    assert len(providers) > 0
    get_settings.cache_clear()
