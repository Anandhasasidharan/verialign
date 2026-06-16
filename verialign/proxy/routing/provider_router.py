import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from verialign.proxy.config import Settings

_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        limits = httpx.Limits(
            max_keepalive_connections=20,
            max_connections=100,
            keepalive_expiry=30.0,
        )
        _http_client = httpx.AsyncClient(limits=limits)
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


@dataclass
class ProviderResponse:
    data: dict
    provider_name: str


class BaseProvider(ABC):
    @abstractmethod
    async def chat_completions(self, payload: dict) -> ProviderResponse:
        pass

    async def chat_completions_stream(self, payload: dict) -> ProviderResponse:
        raise NotImplementedError("streaming not supported by this provider")

    @abstractmethod
    def is_configured(self) -> bool:
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        pass


class OpenAIProvider(BaseProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_configured(self) -> bool:
        return bool(self.settings.upstream_base_url and self.settings.upstream_api_key)

    def get_provider_name(self) -> str:
        return "openai"

    async def chat_completions(self, payload: dict) -> ProviderResponse:
        url = self.settings.upstream_base_url.rstrip("/") + "/chat/completions"
        headers = {
            "authorization": f"Bearer {self.settings.upstream_api_key}",
            "content-type": "application/json",
        }

        client = get_http_client()
        response = await client.post(
            url,
            headers=headers,
            json=payload,
            timeout=self.settings.upstream_timeout_seconds,
        )

        if response.status_code >= 400:
            raise ProviderError(
                response.text,
                status_code=response.status_code,
                provider=self.get_provider_name(),
            )
        return ProviderResponse(
            data=response.json(), provider_name=self.get_provider_name()
        )

    async def chat_completions_stream(self, payload: dict) -> ProviderResponse:
        url = self.settings.upstream_base_url.rstrip("/") + "/chat/completions"
        headers = {
            "authorization": f"Bearer {self.settings.upstream_api_key}",
            "content-type": "application/json",
        }
        stream_payload = {**payload, "stream": True}
        client = get_http_client()
        response = await client.post(
            url,
            headers=headers,
            json=stream_payload,
            timeout=self.settings.upstream_timeout_seconds,
        )
        if response.status_code >= 400:
            raise ProviderError(
                response.text,
                status_code=response.status_code,
                provider=self.get_provider_name(),
            )
        return ProviderResponse(
            data={"raw_response": response, "is_stream": True},
            provider_name=self.get_provider_name(),
        )


class AnthropicProvider(BaseProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = os.getenv(
            "VERIALIGN_ANTHROPIC_BASE_URL", "https://api.anthropic.com"
        )
        self.api_key = os.getenv("VERIALIGN_ANTHROPIC_API_KEY")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def get_provider_name(self) -> str:
        return "anthropic"

    async def chat_completions(self, payload: dict) -> ProviderResponse:
        url = f"{self.base_url}/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        anthropic_payload = self._convert_to_anthropic(payload)

        client = get_http_client()
        response = await client.post(
            url,
            headers=headers,
            json=anthropic_payload,
            timeout=self.settings.upstream_timeout_seconds,
        )

        if response.status_code >= 400:
            raise ProviderError(
                response.text,
                status_code=response.status_code,
                provider=self.get_provider_name(),
            )

        anthropic_response = response.json()
        openai_response = self._convert_from_anthropic(
            anthropic_response, payload.get("model", "claude")
        )
        return ProviderResponse(
            data=openai_response, provider_name=self.get_provider_name()
        )

    def _convert_to_anthropic(self, payload: dict) -> dict:
        messages = payload.get("messages", [])
        system = None
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                user_messages.append(msg)

        return {
            "model": payload.get("model", "claude-3-haiku-20240307"),
            "max_tokens": payload.get("max_tokens", 4096),
            "system": system,
            "messages": user_messages,
            "temperature": payload.get("temperature"),
            "top_p": payload.get("top_p"),
        }

    def _convert_from_anthropic(self, response: dict, model: str) -> dict:
        content = response.get("content", [])
        text = ""
        if content and isinstance(content, list):
            text = content[0].get("text", "")

        created_at = response.get("created_at", 0)
        if isinstance(created_at, str):
            try:
                from datetime import datetime

                created_at = int(
                    datetime.fromisoformat(
                        created_at.replace("Z", "+00:00")
                    ).timestamp()
                )
            except Exception:
                created_at = 0
        elif not isinstance(created_at, int):
            created_at = 0

        return {
            "id": response.get("id", "msg-"),
            "object": "chat.completion",
            "created": created_at,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": response.get("stop_reason", "stop"),
                }
            ],
            "usage": {
                "prompt_tokens": response.get("usage", {}).get("input_tokens", 0),
                "completion_tokens": response.get("usage", {}).get("output_tokens", 0),
                "total_tokens": response.get("usage", {}).get("input_tokens", 0)
                + response.get("usage", {}).get("output_tokens", 0),
            },
        }


class LocalProvider(BaseProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = os.getenv("VERIALIGN_LOCAL_BASE_URL")
        self.api_key = os.getenv("VERIALIGN_LOCAL_API_KEY")

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def get_provider_name(self) -> str:
        return "local"

    async def chat_completions(self, payload: dict) -> ProviderResponse:
        if not self.base_url:
            raise ProviderError(
                "Local provider not configured",
                status_code=503,
                provider=self.get_provider_name(),
            )

        url = f"{self.base_url}/v1/chat/completions"
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"

        client = get_http_client()
        response = await client.post(
            url,
            headers=headers,
            json=payload,
            timeout=self.settings.upstream_timeout_seconds,
        )

        if response.status_code >= 400:
            raise ProviderError(
                response.text,
                status_code=response.status_code,
                provider=self.get_provider_name(),
            )
        return ProviderResponse(
            data=response.json(), provider_name=self.get_provider_name()
        )


class ProviderError(Exception):
    def __init__(
        self, message: str, status_code: int = 502, provider: str = "unknown"
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider


class ProviderRouter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.providers: list[BaseProvider] = [
            OpenAIProvider(settings),
            AnthropicProvider(settings),
            LocalProvider(settings),
        ]

    def get_configured_providers(self) -> list[BaseProvider]:
        return [p for p in self.providers if p.is_configured()]

    def get_provider(self, name: str) -> BaseProvider | None:
        for provider in self.providers:
            if provider.get_provider_name() == name:
                return provider
        return None

    async def chat_completions(
        self, payload: dict, preferred_provider: str | None = None
    ) -> ProviderResponse:
        providers = self.get_configured_providers()
        if not providers:
            return self._demo_response(payload)

        if preferred_provider:
            provider = self.get_provider(preferred_provider)
            if provider and provider.is_configured():
                return await provider.chat_completions(payload)

        return await providers[0].chat_completions(payload)

    async def chat_completions_stream(
        self, payload: dict, preferred_provider: str | None = None
    ):
        providers = self.get_configured_providers()
        if not providers:
            async for chunk in self._demo_stream(payload):
                yield chunk
            return

        if preferred_provider:
            provider = self.get_provider(preferred_provider)
            if provider and provider.is_configured():
                async for chunk in provider.chat_completions_stream(payload):
                    yield chunk
                return

        provider = providers[0]
        async for chunk in provider.chat_completions_stream(payload):
            yield chunk

    async def _demo_stream(self, payload: dict):
        import time
        import uuid

        model = payload.get("model", "demo")
        response_id = f"chatcmpl-demo-{uuid.uuid4().hex[:12]}"
        created = int(time.time())
        user_text = ""
        for message in reversed(payload.get("messages", [])):
            if message.get("role") == "user":
                user_text = str(message.get("content", ""))
                break

        content = (
            "VeriAlign is a verification support proxy for LLM outputs. "
            "It can extract factual claims and compare them with supplied context. "
            f"The latest user request was: {user_text[:160]}"
        )

        base_chunk = {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
        }
        yield {
            **base_chunk,
            "choices": [
                {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
            ],
        }
        yield {
            **base_chunk,
            "choices": [
                {"index": 0, "delta": {"content": content}, "finish_reason": None}
            ],
        }
        yield {
            **base_chunk,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }

    def _demo_response(self, payload: dict) -> ProviderResponse:
        import time
        import uuid

        model = payload.get("model", "demo")
        user_text = ""
        for message in reversed(payload.get("messages", [])):
            if message.get("role") == "user":
                user_text = str(message.get("content", ""))
                break

        content = (
            "VeriAlign is a verification support proxy for LLM outputs. "
            "It can extract factual claims and compare them with supplied context. "
            f"The latest user request was: {user_text[:160]}"
        )
        created = int(time.time())
        return ProviderResponse(
            data={
                "id": f"chatcmpl-demo-{uuid.uuid4().hex[:12]}",
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            },
            provider_name="demo",
        )
