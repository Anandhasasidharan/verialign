import re
import math
from collections.abc import Iterable

from verialign.verification.models import SourceMatch
from verialign.verification.nli_grounder import NLIGrounder
from verialign.verification.web_grounder import WebGrounder

_WORD = re.compile(r"[a-z0-9]+")

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "but",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "with",
}


class EmbeddingMatcher:
    def __init__(self) -> None:
        self._encoder = None
        self._initialized = False

    def _lazy_init(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        try:
            from sentence_transformers import SentenceTransformer

            self._encoder = SentenceTransformer("all-MiniLM-L6-v2")
        except ImportError:
            self._encoder = None

    def encode(self, texts: list[str]) -> list[list[float]] | None:
        self._lazy_init()
        if self._encoder is None:
            return None

        try:
            embeddings = self._encoder.encode(texts, show_progress_bar=False)
            return embeddings.tolist()
        except Exception:
            return None

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


class TFIDFMatcher:
    def __init__(self) -> None:
        self._initialized = False
        self._vectorizer = None

    def _lazy_init(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer

            self._vectorizer = TfidfVectorizer(
                analyzer="char",
                ngram_range=(2, 4),
                max_features=5000,
                stop_words=list(STOPWORDS),
            )
        except ImportError:
            self._vectorizer = None

    def compute_similarity(self, claim: str, context_texts: list[str]) -> list[float]:
        self._lazy_init()
        if self._vectorizer is None:
            return [0.0] * len(context_texts)

        try:
            all_texts = [claim] + context_texts
            tfidf = self._vectorizer.fit_transform(all_texts)
            claim_vec = tfidf[0]
            similarities = []
            for i in range(1, len(all_texts)):
                context_vec = tfidf[i]
                dot = (claim_vec * context_vec.T).toarray()[0][0]
                norm_claim = math.sqrt(claim_vec.multiply(claim_vec).sum())
                norm_context = math.sqrt(context_vec.multiply(context_vec).sum())
                if norm_claim == 0 or norm_context == 0:
                    similarities.append(0.0)
                else:
                    similarities.append(float(dot / (norm_claim * norm_context)))
            return similarities
        except Exception:
            return [0.0] * len(context_texts)


class SourceGrounder:
    def __init__(
        self,
        use_semantic: bool = True,
        use_nli: bool = True,
        web_api_key: str | None = None,
        web_provider: str = "tavily",
    ) -> None:
        self.use_semantic = use_semantic
        self._embedding_matcher: EmbeddingMatcher | None = None
        self._tfidf_matcher: TFIDFMatcher | None = None
        self._web_grounder: WebGrounder | None = None
        self._nli_grounder: NLIGrounder | None = None
        if use_nli:
            self._nli_grounder = NLIGrounder()
        if web_api_key:
            self._web_grounder = WebGrounder(web_api_key, provider=web_provider)

    @property
    def embedding_matcher(self) -> EmbeddingMatcher:
        if self._embedding_matcher is None:
            self._embedding_matcher = EmbeddingMatcher()
        return self._embedding_matcher

    @property
    def tfidf_matcher(self) -> TFIDFMatcher:
        if self._tfidf_matcher is None:
            self._tfidf_matcher = TFIDFMatcher()
        return self._tfidf_matcher

    async def ground(
        self, claim: str, raw_context: object
    ) -> tuple[str, float, list[SourceMatch]]:
        context = self._normalize_context(raw_context)
        matches: list[SourceMatch] = []

        if context:
            claim_terms = self._terms(claim)
            if claim_terms:
                matches = self._match_against_context(claim, context, claim_terms)

        nli_status: str | None = None
        nli_score: float = 0.0
        if self._nli_grounder and self._nli_grounder.is_available() and context:
            context_texts = [c[1] for c in context]
            nli_result = await self._nli_grounder.ground(claim, context_texts)
            nli_status, nli_score, _ = nli_result
            if nli_status == "unsupported" and nli_score > 0.5:
                return "unsupported", nli_score, matches[:3] if matches else []
            if nli_status == "supported" and nli_score > 0.5:
                return "supported", nli_score, matches[:3] if matches else []

        if not matches and self._web_grounder and self._web_grounder.is_available():
            web_sources = await self._web_grounder.ground(claim)
            if web_sources:
                matches = web_sources

        if not matches:
            if nli_status:
                return nli_status, nli_score, []
            return "unclear", 0.0, []

        matches.sort(key=lambda m: m.score, reverse=True)
        top_score = matches[0].score

        if top_score >= 0.55:
            return "supported", top_score, matches[:3]
        if top_score <= 0.3:
            return "unsupported", top_score, matches[:3]
        return "unclear", top_score, matches[:3]

    def _match_against_context(
        self, claim: str, context: list[tuple[str, str]], claim_terms: set[str]
    ) -> list[SourceMatch]:
        matches: list[SourceMatch] = []
        context_texts = [c[1] for c in context]

        semantic_scores = []
        if self.use_semantic and len(context_texts) > 0:
            semantic_scores = self._compute_semantic_scores(claim, context_texts)
        else:
            semantic_scores = [0.0] * len(context_texts)

        for i, (source_id, text) in enumerate(context):
            source_terms = self._terms(text)
            overlap = claim_terms & source_terms
            keyword_score = len(overlap) / len(claim_terms) if claim_terms else 0.0
            sem_score = semantic_scores[i] if i < len(semantic_scores) else 0.0

            if self.use_semantic and sem_score > 0:
                combined = keyword_score * 0.4 + sem_score * 0.6
            else:
                combined = keyword_score

            if combined > 0:
                matches.append(
                    SourceMatch(
                        source_id=source_id,
                        score=round(combined, 3),
                        excerpt=text[:240],
                    )
                )
        return matches

    def _compute_semantic_scores(
        self, claim: str, context_texts: list[str]
    ) -> list[float]:
        embeddings = self.embedding_matcher.encode([claim] + context_texts)
        if embeddings is not None:
            claim_emb = embeddings[0]
            return [
                self.embedding_matcher.cosine_similarity(claim_emb, ctx_emb)
                for ctx_emb in embeddings[1:]
            ]

        tfidf_scores = self.tfidf_matcher.compute_similarity(claim, context_texts)
        if any(s > 0 for s in tfidf_scores):
            return tfidf_scores

        return [0.0] * len(context_texts)

    def _normalize_context(self, raw_context: object) -> list[tuple[str, str]]:
        if isinstance(raw_context, str):
            return [("context-1", raw_context)]
        if not isinstance(raw_context, Iterable):
            return []

        normalized: list[tuple[str, str]] = []
        for index, item in enumerate(raw_context, start=1):
            if isinstance(item, str):
                normalized.append((f"context-{index}", item))
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    normalized.append((str(item.get("id", f"context-{index}")), text))
        return normalized

    def _terms(self, text: str) -> set[str]:
        return {
            word
            for word in _WORD.findall(text.lower())
            if word not in STOPWORDS and len(word) > 2
        }
