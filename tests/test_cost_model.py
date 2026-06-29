import pytest
from verialign.proxy.routing.cost_model import (
    calculate_cost,
    estimate_cost,
    list_model_prices,
    _find_pricing,
)
from verialign.proxy.routing.provider_router import (
    ProviderRouter,
    OpenAIProvider,
    AnthropicProvider,
    LocalProvider,
)
from verialign.proxy.config import Settings


class TestCostModel:
    def test_calculate_cost_known_model(self):
        cost = calculate_cost("gpt-4o", 1000, 500)
        assert cost is not None
        assert cost > 0
        assert cost < 1

    def test_calculate_cost_unknown_model(self):
        cost = calculate_cost("nonexistent-model", 1000, 500)
        assert cost is None

    def test_calculate_cost_exact_values(self):
        cost = calculate_cost("gpt-4o", 1_000_000, 0)
        assert cost == pytest.approx(2.50, rel=1e-3)

    def test_calculate_cost_output_only(self):
        cost = calculate_cost("gpt-4o", 0, 1_000_000)
        assert cost == pytest.approx(10.00, rel=1e-3)

    def test_calculate_cost_zero_tokens(self):
        cost = calculate_cost("gpt-4o", 0, 0)
        assert cost == pytest.approx(0.0, rel=1e-3)

    def test_estimate_cost(self):
        cost = estimate_cost("gpt-4o-mini", 1000)
        assert cost is not None
        assert cost > 0

    def test_estimate_cost_unknown_model(self):
        cost = estimate_cost("unknown-model", 1000)
        assert cost is None

    def test_list_model_prices(self):
        prices = list_model_prices()
        assert "gpt-4o" in prices
        assert len(prices) > 5

    def test_find_pricing_exact(self):
        pricing = _find_pricing("gpt-4o")
        assert pricing is not None
        assert pricing["input"] == 2.50

    def test_find_pricing_case_insensitive(self):
        pricing = _find_pricing("GPT-4O")
        assert pricing is not None

    def test_find_pricing_substring(self):
        pricing = _find_pricing("gpt-4o-2024-08-06")
        assert pricing is not None

    def test_find_pricing_unknown(self):
        pricing = _find_pricing("totally-made-up")
        assert pricing is None


class TestCostWeightedRouting:
    def setup_method(self):
        self.settings = Settings(
            upstream_base_url="https://api.openai.com/v1",
            upstream_api_key="test-key",
        )

    def test_select_provider_returns_configured_provider(self):
        router = ProviderRouter(self.settings)
        payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
        provider = router.select_provider(payload)
        assert provider is not None
        assert provider.get_provider_name() == "openai"

    def test_select_provider_preferred_overrides_cost(self):
        router = ProviderRouter(self.settings)
        payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
        provider = router.select_provider(payload, preferred_provider="openai")
        assert provider is not None
        assert provider.get_provider_name() == "openai"

    def test_select_provider_no_providers_raises(self):
        settings = Settings(upstream_base_url=None, upstream_api_key=None)
        router = ProviderRouter(settings)
        payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
        with pytest.raises(Exception):
            router.select_provider(payload)

    def test_select_provider_single_provider(self):
        router = ProviderRouter(self.settings)
        payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
        provider = router.select_provider(payload)
        assert provider.get_provider_name() == "openai"

    @pytest.mark.asyncio
    async def test_chat_completions_demo_mode_no_providers(self):
        settings = Settings(upstream_base_url=None, upstream_api_key=None)
        router = ProviderRouter(settings)
        response = await router.chat_completions({"model": "demo", "messages": []})
        assert response.provider_name == "demo"
