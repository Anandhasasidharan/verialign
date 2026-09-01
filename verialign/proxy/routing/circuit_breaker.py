import logging
import time
from enum import Enum

from verialign.proxy.routing.provider_router import (
    BaseProvider,
    ProviderError,
    ProviderResponse,
)

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        provider: BaseProvider,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self.provider = provider
        self._failure_threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0

    @property
    def name(self) -> str:
        return self.provider.get_provider_name()

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self._cooldown:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def is_available(self) -> bool:
        return self.state != CircuitState.OPEN

    def _on_success(self) -> None:
        self._failure_count = 0
        self._state = CircuitState.CLOSED

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "circuit_opened",
                extra={"provider": self.provider.get_provider_name()},
            )

    async def chat_completions(self, payload: dict) -> ProviderResponse:
        current = self.state
        if current == CircuitState.OPEN:
            msg = "Circuit breaker open"
            raise ProviderError(
                msg,
                status_code=503,
                provider=self.provider.get_provider_name(),
            )

        try:
            response = await self.provider.chat_completions(payload)
            self._on_success()
            if current == CircuitState.HALF_OPEN:
                logger.info(
                    "circuit_half_open_success",
                    extra={"provider": self.provider.get_provider_name()},
                )
            return response
        except ProviderError:
            if current == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(
                    "circuit_half_open_failed",
                    extra={"provider": self.provider.get_provider_name()},
                )
            else:
                self._on_failure()
            raise

    def get_status(self) -> dict:
        return {
            "provider": self.provider.get_provider_name(),
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self._failure_threshold,
            "cooldown_seconds": self._cooldown,
        }
