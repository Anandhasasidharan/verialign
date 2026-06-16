import pytest
from unittest.mock import MagicMock
from verialign.proxy.routing.provider_router import (
    ProviderRouter,
    BaseProvider,
    ProviderResponse,
    ProviderError,
)
from verialign.proxy.routing.fallback import ProviderFallback, with_fallback


class MockProvider(BaseProvider):
    def __init__(self, name: str, should_fail: bool = False, fail_status: int = 500):
        self.name = name
        self.should_fail = should_fail
        self.fail_status = fail_status
        self.call_count = 0

    def is_configured(self) -> bool:
        return True

    def get_provider_name(self) -> str:
        return self.name

    async def chat_completions(self, payload: dict) -> ProviderResponse:
        self.call_count += 1
        if self.should_fail:
            raise ProviderError(
                f"{self.name} failed", status_code=self.fail_status, provider=self.name
            )
        return ProviderResponse(
            data={
                "id": f"resp-{self.name}",
                "choices": [{"message": {"content": f"Response from {self.name}"}}],
            },
            provider_name=self.name,
        )


class TestProviderFallback:
    @pytest.mark.asyncio
    async def test_success_first_provider(self):
        router = MagicMock(spec=ProviderRouter)
        router.get_configured_providers.return_value = [
            MockProvider("provider1"),
            MockProvider("provider2"),
        ]

        fallback = ProviderFallback(router, max_retries=1)
        result = await fallback.chat_completions_with_fallback({"model": "test"})

        assert result.response.provider_name == "provider1"
        assert result.attempts[0]["success"] is True
        assert result.attempts[0]["provider"] == "provider1"

    @pytest.mark.asyncio
    async def test_fallback_to_second_provider(self):
        router = MagicMock(spec=ProviderRouter)
        provider1 = MockProvider("provider1", should_fail=True, fail_status=503)
        provider2 = MockProvider("provider2")
        router.get_configured_providers.return_value = [provider1, provider2]

        fallback = ProviderFallback(router, max_retries=1)
        result = await fallback.chat_completions_with_fallback({"model": "test"})

        assert result.response.provider_name == "provider2"
        assert len(result.attempts) == 2
        assert result.attempts[0]["success"] is False
        assert result.attempts[1]["success"] is True

    @pytest.mark.asyncio
    async def test_non_retryable_error_raises_immediately(self):
        router = MagicMock(spec=ProviderRouter)
        provider = MockProvider("provider1", should_fail=True, fail_status=400)
        router.get_configured_providers.return_value = [provider]

        fallback = ProviderFallback(router, max_retries=2)

        with pytest.raises(ProviderError) as exc_info:
            await fallback.chat_completions_with_fallback({"model": "test"})

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises(self):
        router = MagicMock(spec=ProviderRouter)
        router.get_configured_providers.return_value = [
            MockProvider("provider1", should_fail=True, fail_status=503),
            MockProvider("provider2", should_fail=True, fail_status=503),
        ]

        fallback = ProviderFallback(router, max_retries=1)

        with pytest.raises(ProviderError) as exc_info:
            await fallback.chat_completions_with_fallback({"model": "test"})

        assert "All providers failed" in str(exc_info.value)


class TestWithFallback:
    @pytest.mark.asyncio
    async def test_with_fallback_returns_response(self):
        router = MagicMock(spec=ProviderRouter)
        router.get_configured_providers.return_value = [MockProvider("provider1")]

        response = await with_fallback(router, {"model": "test"})
        assert response.provider_name == "provider1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
