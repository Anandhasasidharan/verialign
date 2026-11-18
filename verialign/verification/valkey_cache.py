"""Valkey-backed verification cache — falls back to in-memory when not configured."""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import asdict

from verialign.verification.models import (
    ChecklistItem,
    Contradiction,
    SourceMatch,
    VerificationResult,
    VerifiedClaim,
)
from verialign.verification.verification_cache import VerificationCache


class ValkeyCache(VerificationCache):
    def __init__(
        self, ttl_seconds: int = 300, max_size: int = 1000, url: str | None = None
    ) -> None:
        super().__init__(ttl_seconds, max_size)
        self._client: object | None = None
        self._enabled = False
        self._connect(url or os.environ.get("VERIALIGN_VALKEY_URL", ""))

    def _connect(self, url: str) -> None:
        if not url:
            return
        try:
            import valkey as _valkey

            self._client = _valkey.from_url(
                url, decode_responses=True, socket_connect_timeout=0.25, socket_timeout=0.25
            )
            self._client.ping()
            self._enabled = True
        except Exception:  # noqa: BLE001
            self._client = None
            self._enabled = False

    def get(
        self,
        text: str,
        context: object | None = None,
    ) -> VerificationResult | None:
        if self._enabled and self._client is not None:
            try:
                key = self._make_key(text, context)
                raw = self._client.get(key)
                if raw:
                    data = json.loads(raw)
                    claims = data.pop("claims")
                    data["claims"] = [
                        VerifiedClaim(
                            **{**claim, "sources": [SourceMatch(**s) for s in claim["sources"]]}
                        )
                        for claim in claims
                    ]
                    data["contradictions"] = [Contradiction(**c) for c in data["contradictions"]]
                    data["checklist"] = [ChecklistItem(**item) for item in data["checklist"]]
                    return VerificationResult(**data)
            except Exception:  # noqa: BLE001, S110
                pass
        return super().get(text, context)

    def set(
        self,
        text: str,
        context: object | None,
        result: VerificationResult,
    ) -> None:
        if self._enabled and self._client is not None:
            try:
                key = self._make_key(text, context)
                data = json.dumps(asdict(result))
                self._client.setex(key, self._ttl, data)
                return
            except Exception:  # noqa: BLE001, S110
                pass
        super().set(text, context, result)

    def clear(self) -> None:
        if self._enabled and self._client is not None:
            with contextlib.suppress(Exception):
                self._client.flushdb()
        super().clear()
