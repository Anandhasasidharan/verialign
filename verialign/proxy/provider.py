import time
import uuid

import httpx

from verialign.proxy.config import Settings


class ProviderError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProviderClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def chat_completions(self, payload: dict) -> dict:
        if not self.settings.upstream_base_url or not self.settings.upstream_api_key:
            return self._demo_response(payload)

        url = self.settings.upstream_base_url.rstrip("/") + "/chat/completions"
        headers = {
            "authorization": f"Bearer {self.settings.upstream_api_key}",
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(
            timeout=self.settings.upstream_timeout_seconds
        ) as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                raise ProviderError(f"Upstream provider request failed: {exc}") from exc

        if response.status_code >= 400:
            raise ProviderError(response.text, status_code=response.status_code)
        return response.json()

    def _demo_response(self, payload: dict) -> dict:
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
        return {
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
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
