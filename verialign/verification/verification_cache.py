"""In-memory cache for verification results — avoids re-verifying identical text."""

from __future__ import annotations

import hashlib
import json
import time

from verialign.verification.models import VerificationResult


class VerificationCache:
    def __init__(self, ttl_seconds: int = 300, max_size: int = 1000) -> None:
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._cache: dict[str, tuple[float, VerificationResult]] = {}

    def _make_key(self, text: str, context: object | None = None) -> str:
        raw = text
        if context:
            raw += json.dumps(context, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(
        self, text: str, context: object | None = None
    ) -> VerificationResult | None:
        key = self._make_key(text, context)
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, result = entry
        if time.monotonic() - ts > self._ttl:
            del self._cache[key]
            return None
        return result

    def set(
        self, text: str, context: object | None, result: VerificationResult
    ) -> None:
        if len(self._cache) >= self._max_size:
            self._evict()
        key = self._make_key(text, context)
        self._cache[key] = (time.monotonic(), result)

    def _evict(self) -> None:
        oldest = min(self._cache.keys(), key=lambda k: self._cache[k][0])
        del self._cache[oldest]

    def clear(self) -> None:
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)
