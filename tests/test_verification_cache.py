from verialign.verification.verification_cache import VerificationCache
from verialign.verification.models import VerificationResult, VerifiedClaim


def _make_result(text: str = "test") -> VerificationResult:
    return VerificationResult(
        claims=[
            VerifiedClaim(
                text=text,
                status="supported",
                confidence=0.9,
                sources=[],
                claim_id="c-0",
            )
        ],
        contradictions=[],
        checklist=[],
    )


class TestVerificationCache:
    def test_get_miss_returns_none(self):
        cache = VerificationCache()
        assert cache.get("missing text") is None

    def test_set_and_get(self):
        cache = VerificationCache()
        result = _make_result("hello world")
        cache.set("hello world", None, result)
        cached = cache.get("hello world")
        assert cached is not None
        assert cached.claims[0].text == "hello world"

    def test_different_text_different_cache(self):
        cache = VerificationCache()
        cache.set("text a", None, _make_result("a"))
        assert cache.get("text b") is None

    def test_context_affects_key(self):
        cache = VerificationCache()
        result = _make_result("claim")
        cache.set("claim", {"id": "doc-1"}, result)
        assert cache.get("claim", {"id": "doc-2"}) is None
        assert cache.get("claim", {"id": "doc-1"}) is not None

    def test_evict_when_full(self):
        cache = VerificationCache(ttl_seconds=3600, max_size=3)
        for i in range(4):
            cache.set(f"text-{i}", None, _make_result(f"text-{i}"))
        assert cache.size <= 3

    def test_ttl_expires(self):
        cache = VerificationCache(ttl_seconds=0)
        cache.set("stale", None, _make_result("stale"))
        assert cache.get("stale") is None

    def test_clear_empties_cache(self):
        cache = VerificationCache()
        cache.set("a", None, _make_result("a"))
        cache.set("b", None, _make_result("b"))
        cache.clear()
        assert cache.size == 0

    def test_cache_hit_returns_same_object(self):
        cache = VerificationCache()
        result = _make_result("same")
        cache.set("same", None, result)
        cached = cache.get("same")
        assert cached is result
