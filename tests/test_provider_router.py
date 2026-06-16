import pytest
from verialign.proxy.routing.provider_router import (
    ProviderRouter,
    OpenAIProvider,
    AnthropicProvider,
    LocalProvider,
)
from verialign.proxy.config import Settings


class TestProviderRouter:
    def setup_method(self):
        self.settings = Settings(
            upstream_base_url="https://api.openai.com/v1",
            upstream_api_key="test-key",
        )

    def test_get_configured_providers_with_openai(self):
        router = ProviderRouter(self.settings)
        providers = router.get_configured_providers()
        assert len(providers) >= 1
        assert any(p.get_provider_name() == "openai" for p in providers)

    def test_get_provider_by_name(self):
        router = ProviderRouter(self.settings)
        provider = router.get_provider("openai")
        assert provider is not None
        assert provider.get_provider_name() == "openai"

    def test_get_provider_not_found(self):
        router = ProviderRouter(self.settings)
        provider = router.get_provider("nonexistent")
        assert provider is None

    @pytest.mark.asyncio
    async def test_demo_mode_when_no_providers(self):
        settings = Settings(upstream_base_url=None, upstream_api_key=None)
        router = ProviderRouter(settings)
        response = await router.chat_completions({"model": "demo", "messages": []})
        assert response.provider_name == "demo"
        assert "VeriAlign" in response.data["choices"][0]["message"]["content"]

    def test_openai_provider_configured(self):
        provider = OpenAIProvider(self.settings)
        assert provider.is_configured() is True
        assert provider.get_provider_name() == "openai"

    def test_openai_provider_not_configured(self):
        settings = Settings(upstream_base_url=None, upstream_api_key=None)
        provider = OpenAIProvider(settings)
        assert provider.is_configured() is False


class TestAnthropicProvider:
    def setup_method(self):
        self.settings = Settings(
            upstream_base_url="https://api.openai.com/v1",
            upstream_api_key="test-key",
        )

    def test_convert_to_anthropic(self):
        provider = AnthropicProvider(self.settings)
        payload = {
            "model": "claude-3",
            "messages": [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"},
            ],
            "temperature": 0.7,
        }
        result = provider._convert_to_anthropic(payload)
        assert result["model"] == "claude-3"
        assert result["system"] == "You are helpful"
        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"
        assert result["temperature"] == 0.7

    def test_convert_from_anthropic(self):
        provider = AnthropicProvider(self.settings)
        response = {
            "id": "msg-123",
            "created_at": "2024-01-01T00:00:00Z",
            "content": [{"text": "Hello there!"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 20},
        }
        result = provider._convert_from_anthropic(response, "claude-3")
        assert result["id"] == "msg-123"
        assert result["choices"][0]["message"]["content"] == "Hello there!"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 20


class TestLocalProvider:
    def test_local_provider_not_configured_without_env(self):
        settings = Settings(upstream_base_url=None, upstream_api_key=None)
        provider = LocalProvider(settings)
        assert provider.is_configured() is False
        assert provider.get_provider_name() == "local"

    def test_local_provider_configured_with_env(self, monkeypatch):
        monkeypatch.setenv("VERIALIGN_LOCAL_BASE_URL", "http://localhost:11434")
        settings = Settings(upstream_base_url=None, upstream_api_key=None)
        provider = LocalProvider(settings)
        assert provider.is_configured() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
