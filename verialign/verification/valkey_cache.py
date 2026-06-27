"""Valkey-backed verification cache — falls back to in-memory when not configured."""

from __future__ import annotations

import json
import os

from verialign.verification.models import VerificationResult
from verialign.verification.verification_cache import VerificationCache


class ValkeyCache(VerificationCache):
    def __init__(self, ttl_seconds: int = 300, max_size: int = 1000) -> None:
        super().__init__(ttl_seconds, max_size)
        self._client: object | None = None
        self._enabled = False
        self._connect()

    def _connect(self) -> None:
        url = os.environ.get("VERIALIGN_VALKEY_URL", "")
        if not url:
            return
        try:
            import valkey as _valkey

            self._client = _valkey.from_url(url, decode_responses=True)
            self._client.ping()
            self._enabled = True
        except Exception:
            self._client = None
            self._enabled = False

    def get(
        self, text: str, context: object | None = None
    ) -> VerificationResult | None:
        if self._enabled and self._client is not None:
            try:
                key = self._make_key(text, context)
                import valkey as _valkey

                raw = _valkey.Valkey(self._client.connection_pool).get(key)
                if raw:
                    data = json.loads(raw)
                    return VerificationResult(**data)
            except Exception:
                pass
        return super().get(text, context)

    def set(
        self, text: str, context: object | None, result: VerificationResult
    ) -> None:
        if self._enabled and self._client is not None:
            try:
                key = self._make_key(text, context)
                data = json.dumps(
                    {
                        "claims": [c.__dict__ for c in result.claims],
                        "contradictions": [c.__dict__ for c in result.contradictions],
                        "checklist": [c.__dict__ for c in result.checklist],
                        "summary": result.summary,
                    }
                )
                self._client.setex(key, self._ttl, data)
                return
            except Exception:
                pass
        super().set(text, context, result)

    def clear(self) -> None:
        if self._enabled and self._client is not None:
            try:
                self._client.flushdb()
            except Exception:
                pass
        super().clear()
