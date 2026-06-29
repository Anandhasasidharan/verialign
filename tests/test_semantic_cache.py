import pytest

from verialign.verification.verification_cache import VerificationCache
from verialign.verification.models import VerificationResult, VerifiedClaim


_has_st = False
try:
    from sentence_transformers import SentenceTransformer  # noqa: F401

    _has_st = True
except ImportError:
    pass

semantic = pytest.mark.skipif(not _has_st, reason="sentence_transformers not installed")


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


class TestSemanticCache:
    @semantic
    def test_semantic_near_match_hits(self):
        cache = VerificationCache(similarity_threshold=0.5)
        result = _make_result("the capital of France is Paris")
        cache.set("the capital of France is Paris", None, result)
        cached = cache.get("Paris is the capital of France")
        assert cached is not None
        assert cached.claims[0].text == "the capital of France is Paris"

    def test_semantic_different_queries_miss(self):
        cache = VerificationCache(similarity_threshold=0.99)
        result = _make_result("the capital of France is Paris")
        cache.set("the capital of France is Paris", None, result)
        cached = cache.get("what is the weather today")
        assert cached is None

    def test_exact_match_still_works(self):
        cache = VerificationCache()
        result = _make_result("hello world")
        cache.set("hello world", None, result)
        cached = cache.get("hello world")
        assert cached is not None
        assert cached.claims[0].text == "hello world"

    def test_context_respected_in_exact_match(self):
        cache = VerificationCache(similarity_threshold=0.99)
        result = _make_result("the capital of France is Paris")
        cache.set("the capital of France is Paris", {"id": "doc-1"}, result)
        cached = cache.get("the capital of France is Paris", {"id": "doc-2"})
        assert cached is None
        cached = cache.get("the capital of France is Paris", {"id": "doc-1"})
        assert cached is not None

    def test_ttl_still_expires(self):
        cache = VerificationCache(ttl_seconds=0)
        cache.set("test", None, _make_result("test"))
        assert cache.get("test") is None

    def test_clear_empties_everything(self):
        cache = VerificationCache()
        result = _make_result("a")
        cache.set("a", None, result)
        cache.set("b", None, result)
        cache.clear()
        assert cache.size == 0

    def test_embedder_not_available_fallback(self):
        cache = VerificationCache()
        cache._embedder = False
        result = _make_result("test")
        cache.set("test", None, result)
        cached = cache.get("different text")
        assert cached is None

    @semantic
    def test_semantic_with_context(self):
        cache = VerificationCache(similarity_threshold=0.5)
        result = _make_result("summarize the document")
        cache.set("summarize the document", None, result)
        cached = cache.get("summarize this document")
        assert cached is not None

    def test_empty_string(self):
        cache = VerificationCache()
        assert cache.get("") is None
        cache.set("", None, _make_result(""))
        assert cache.get("") is not None
