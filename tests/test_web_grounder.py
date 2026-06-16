import pytest
from verialign.verification.web_grounder import WebGrounder


class TestWebGrounder:
    def test_not_available_without_key(self):
        g = WebGrounder(api_key=None)
        assert g.is_available() is False

    def test_available_with_key(self):
        g = WebGrounder(api_key="test-key")
        assert g.is_available() is True

    @pytest.mark.asyncio
    async def test_returns_empty_without_key(self):
        g = WebGrounder(api_key=None)
        results = await g.ground("test claim")
        assert results == []

    @pytest.mark.asyncio
    async def test_caches_results(self):
        g = WebGrounder(api_key="test-key")
        assert "fake_claim_hash" not in g._cache
        g._cache["fake_claim_hash"] = (0.0, [])
        # cache hit should return immediately
        results = await g.ground("fake claim")
        assert results == []

    def test_unknown_provider_logs_warning(self, caplog):
        import logging

        g = WebGrounder(api_key="key", provider="unknown")
        import asyncio

        with caplog.at_level(logging.WARNING):
            asyncio.run(g.ground("test"))
        assert any("unknown_web_search_provider" in rec.msg for rec in caplog.records)

    @pytest.mark.skip(reason="Requires live API key")
    @pytest.mark.asyncio
    async def test_integration_with_real_api(self):
        import os

        key = os.environ.get("VERIALIGN_WEB_SEARCH_API_KEY")
        if not key:
            pytest.skip("VERIALIGN_WEB_SEARCH_API_KEY not set")
        g = WebGrounder(api_key=key, provider="tavily")
        results = await g.ground("Paris is the capital of France")
        assert len(results) > 0
        assert results[0].source_id.startswith("http")
        assert len(results[0].excerpt) > 0
