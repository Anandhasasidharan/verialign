"""Web search grounding for verification — searches the web for source documents."""

from __future__ import annotations

import hashlib
import logging
import time

import httpx

from verialign.verification.models import SourceMatch

logger = logging.getLogger(__name__)


class WebGrounder:
    def __init__(self, api_key: str | None, provider: str = "tavily") -> None:
        self.api_key = api_key
        self.provider = provider
        self._cache: dict[str, tuple[float, list[SourceMatch]]] = {}
        self._cache_ttl = 300  # 5 minutes

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def ground(self, claim: str, max_results: int = 3) -> list[SourceMatch]:
        if not self.api_key:
            return []

        cache_key = hashlib.md5(claim.encode()).hexdigest()
        cached = self._cache.get(cache_key)
        if cached:
            ts, results = cached
            if time.monotonic() - ts < self._cache_ttl:
                return results

        try:
            results = await self._search(claim, max_results)
            self._cache[cache_key] = (time.monotonic(), results)
            return results
        except Exception:
            logger.exception("web_search_failed", extra={"claim": claim[:80]})
            return []

    async def _search(self, claim: str, max_results: int) -> list[SourceMatch]:
        if self.provider == "tavily":
            return await self._search_tavily(claim, max_results)
        if self.provider in ("google", "serpapi"):
            return await self._search_serpapi(claim, max_results)
        logger.warning("unknown_web_search_provider", extra={"provider": self.provider})
        return []

    async def _search_tavily(self, claim: str, max_results: int) -> list[SourceMatch]:
        url = "https://api.tavily.com/search"
        headers = {"content-type": "application/json"}
        payload = {
            "api_key": self.api_key,
            "query": claim,
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()

        results: list[SourceMatch] = []
        for i, item in enumerate(data.get("results", [])):
            results.append(
                SourceMatch(
                    source_id=item.get("url", f"web-{i}"),
                    score=round(item.get("score", 0.5) if "score" in item else 0.5, 3),
                    excerpt=(item.get("content") or item.get("title") or "")[:240],
                )
            )
        return results

    async def _search_serpapi(self, claim: str, max_results: int) -> list[SourceMatch]:
        params = {
            "engine": "google",
            "q": claim,
            "api_key": self.api_key,
            "num": max_results,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://serpapi.com/search", params=params, timeout=15.0
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[SourceMatch] = []
        for i, item in enumerate(data.get("organic_results", [])[:max_results]):
            results.append(
                SourceMatch(
                    source_id=item.get("link", f"web-{i}"),
                    score=0.5,
                    excerpt=(item.get("snippet") or item.get("title") or "")[:240],
                )
            )
        return results
