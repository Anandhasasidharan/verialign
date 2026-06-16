from dataclasses import dataclass

from verialign.proxy.routing.provider_router import (
    ProviderRouter,
    ProviderResponse,
    ProviderError,
)


@dataclass
class FallbackResult:
    response: ProviderResponse
    attempts: list[dict]


class ProviderFallback:
    def __init__(
        self,
        router: ProviderRouter,
        max_retries: int = 2,
        retryable_status_codes: set[int] | None = None,
    ) -> None:
        self.router = router
        self.max_retries = max_retries
        self.retryable_status_codes = retryable_status_codes or {
            429,
            500,
            502,
            503,
            504,
        }

    async def chat_completions_with_fallback(
        self,
        payload: dict,
        preferred_provider: str | None = None,
    ) -> FallbackResult:
        attempts: list[dict] = []
        last_error: ProviderError | None = None

        providers = self.router.get_configured_providers()
        if not providers:
            return FallbackResult(
                response=self.router._demo_response(payload), attempts=[]
            )

        if preferred_provider:
            provider = self.router.get_provider(preferred_provider)
            if provider and provider.is_configured():
                providers = [provider] + [p for p in providers if p != provider]

        for attempt in range(self.max_retries + 1):
            for provider in providers:
                attempt_info = {
                    "provider": provider.get_provider_name(),
                    "attempt": attempt + 1,
                    "success": False,
                }

                try:
                    response = await provider.chat_completions(payload)
                    attempt_info["success"] = True
                    attempts.append(attempt_info)
                    return FallbackResult(response=response, attempts=attempts)
                except ProviderError as exc:
                    attempt_info["error"] = str(exc)
                    attempt_info["status_code"] = exc.status_code
                    attempts.append(attempt_info)
                    last_error = exc

                    if exc.status_code not in self.retryable_status_codes:
                        raise

        raise ProviderError(
            f"All providers failed after {len(attempts)} attempts. Last error: {last_error}",
            status_code=last_error.status_code if last_error else 502,
        )


async def with_fallback(
    router: ProviderRouter,
    payload: dict,
    preferred_provider: str | None = None,
    max_retries: int = 2,
) -> ProviderResponse:
    fallback = ProviderFallback(router, max_retries=max_retries)
    result = await fallback.chat_completions_with_fallback(payload, preferred_provider)
    return result.response
