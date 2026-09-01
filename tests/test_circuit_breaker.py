from unittest.mock import AsyncMock

import pytest

from verialign.proxy.routing.circuit_breaker import CircuitBreaker, CircuitState
from verialign.proxy.routing.provider_router import (
    BaseProvider,
    ProviderError,
    ProviderResponse,
)


class _MockProvider(BaseProvider):
    def __init__(self, name: str = "mock") -> None:
        self._name = name
        self._mock = AsyncMock()

    async def chat_completions(self, payload: dict) -> ProviderResponse:
        return await self._mock(payload)

    def is_configured(self) -> bool:
        return True

    def get_provider_name(self) -> str:
        return self._name


class TestCircuitBreaker:
    def test_closed_state(self) -> None:
        p = _MockProvider()
        cb = CircuitBreaker(p, failure_threshold=3, cooldown_seconds=30)
        assert cb.state == CircuitState.CLOSED
        assert cb.is_available() is True

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self) -> None:
        p = _MockProvider()
        p._mock.side_effect = ProviderError("fail", status_code=502, provider="mock")
        cb = CircuitBreaker(p, failure_threshold=3, cooldown_seconds=30)

        for _ in range(3):
            with pytest.raises(ProviderError):
                await cb.chat_completions({"model": "test"})

        assert cb.state == CircuitState.OPEN
        assert cb.is_available() is False

    @pytest.mark.asyncio
    async def test_open_raises_immediately(self) -> None:
        p = _MockProvider()
        p._mock.side_effect = ProviderError("fail", status_code=502, provider="mock")
        cb = CircuitBreaker(p, failure_threshold=1, cooldown_seconds=999)

        with pytest.raises(ProviderError):
            await cb.chat_completions({"model": "test"})

        with pytest.raises(ProviderError):
            await cb.chat_completions({"model": "test"})

        assert cb.state == CircuitState.OPEN
        assert cb.is_available() is False

    @pytest.mark.asyncio
    async def test_success_resets_counter(self) -> None:
        p = _MockProvider()
        cb = CircuitBreaker(p, failure_threshold=2, cooldown_seconds=30)
        p._mock.side_effect = ProviderError("fail", status_code=502, provider="mock")

        with pytest.raises(ProviderError):
            await cb.chat_completions({"model": "test"})

        assert cb.state == CircuitState.CLOSED

        p._mock.side_effect = None
        p._mock.return_value = ProviderResponse(data={"ok": True}, provider_name="mock")

        resp = await cb.chat_completions({"model": "test"})
        assert resp.data["ok"] is True
        assert cb.state == CircuitState.CLOSED

    def test_get_status(self) -> None:
        p = _MockProvider(name="mock-test")
        cb = CircuitBreaker(p, failure_threshold=5, cooldown_seconds=60.0)
        status = cb.get_status()
        assert status["provider"] == "mock-test"
        assert status["state"] == "closed"
        assert status["failure_threshold"] == 5
        assert status["cooldown_seconds"] == 60.0
