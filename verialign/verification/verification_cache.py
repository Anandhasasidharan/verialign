"""In-memory cache for verification results — avoids re-verifying identical text."""

from __future__ import annotations

import hashlib
import json
import math
import time

from verialign.verification.models import VerificationResult


class VerificationCache:
    def __init__(
        self,
        ttl_seconds: int = 300,
        max_size: int = 1000,
        similarity_threshold: float = 0.92,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._similarity_threshold = similarity_threshold
        self._cache: dict[str, tuple[float, str, VerificationResult]] = {}
        self._embeddings: dict[str, tuple[float, list[float]]] = {}
        self._embedder = None

    def _make_key(self, text: str, context: object | None = None) -> str:
        raw = text
        if context:
            raw += json.dumps(context, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _init_embedder(self) -> None:
        if self._embedder is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
        except ImportError:
            self._embedder = False
        except Exception:
            self._embedder = False

    def _ensure_embeddings(self) -> None:
        if not self._embedder or self._embedder is False:
            return
        for key, (ts, original_text, _) in list(self._cache.items()):
            if key not in self._embeddings:
                try:
                    emb = self._embedder.encode(original_text, convert_to_numpy=True)
                    self._embeddings[key] = (ts, emb.tolist())
                except Exception:
                    pass

    def _get_semantic_key(self, text: str) -> str | None:
        self._init_embedder()
        if self._embedder is False:
            return None
        self._ensure_embeddings()
        if not self._embeddings:
            return None
        try:
            emb = self._embedder.encode(text, convert_to_numpy=True)
            best_key: str | None = None
            best_sim = 0.0
            for key, (_, stored_emb) in self._embeddings.items():
                sim = sum(a * b for a, b in zip(emb.tolist(), stored_emb)) / (
                    math.sqrt(sum(a * a for a in emb.tolist()))
                    * math.sqrt(sum(b * b for b in stored_emb))
                    or 1
                )
                if sim > best_sim:
                    best_key, best_sim = key, sim
            if best_key and best_sim >= self._similarity_threshold:
                return best_key
        except Exception:
            pass
        return None

    def get(
        self, text: str, context: object | None = None
    ) -> VerificationResult | None:
        key = self._make_key(text, context)
        entry = self._cache.get(key)
        if entry is not None:
            ts, _, result = entry
            if time.monotonic() - ts <= self._ttl:
                return result
            del self._cache[key]

        if context is None:
            semantic_key = self._get_semantic_key(text)
            if semantic_key and semantic_key != key:
                entry = self._cache.get(semantic_key)
                if entry is not None:
                    ts, _, result = entry
                    if time.monotonic() - ts <= self._ttl:
                        self._cache[key] = (time.monotonic(), text, result)
                        return result
                    del self._cache[semantic_key]
        return None

    def set(
        self, text: str, context: object | None, result: VerificationResult
    ) -> None:
        if len(self._cache) >= self._max_size:
            self._evict()
        key = self._make_key(text, context)
        self._cache[key] = (time.monotonic(), text, result)
        if self._embedder:
            try:
                emb = self._embedder.encode(text, convert_to_numpy=True)
                self._embeddings[key] = (time.monotonic(), emb.tolist())
            except Exception:
                pass

    def _evict(self) -> None:
        oldest = min(self._cache.keys(), key=lambda k: self._cache[k][0])
        del self._cache[oldest]
        self._embeddings.pop(oldest, None)

    def clear(self) -> None:
        self._cache.clear()
        self._embeddings.clear()

    @property
    def size(self) -> int:
        return len(self._cache)
