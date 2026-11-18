import math
import re
from collections.abc import Iterable
from threading import Lock

from verialign.verification.models import SourceMatch
from verialign.verification.nli_grounder import shared_nli_grounder
from verialign.verification.web_grounder import WebGrounder
from verialign.verification.workers import verification_workers

_WORD = re.compile(r"[a-z0-9]+")
_NEGATION = re.compile(
    r"\b(is|are|was|were|has|have|had|can|will|does|do|did) not\b"
    r"(?! (?:only|just|necessarily|always|unlike)\b)"
)
_BIRTH_YEAR = re.compile(r"(.+ was born in )([12]\d{3})$")


def _proposition(text: str) -> str:
    return " ".join(text.casefold().split()).rstrip(".")


def _explicit_refutation(claim: str, evidence: str) -> bool:
    claim_negations = list(_NEGATION.finditer(claim))
    evidence_negations = list(_NEGATION.finditer(evidence))
    if len(claim_negations) + len(evidence_negations) == 1:
        return _NEGATION.sub(r"\1", claim) == _NEGATION.sub(r"\1", evidence)
    if claim_negations or evidence_negations:
        return False
    claim_year, evidence_year = _BIRTH_YEAR.fullmatch(claim), _BIRTH_YEAR.fullmatch(evidence)
    return bool(
        claim_year
        and evidence_year
        and claim_year[1] == evidence_year[1]
        and claim_year[2] != evidence_year[2]
    )


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
        except Exception:  # noqa: BLE001
            return None

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=False))
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
            all_texts = [claim, *context_texts]
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
        except Exception:  # noqa: BLE001
            return [0.0] * len(context_texts)


class SourceGrounder:
    def __init__(
        self,
        use_semantic: bool = True,
        use_nli: bool = True,
        web_api_key: str | None = None,
        web_provider: str = "tavily",
        use_rescoring: bool = False,
    ) -> None:
        self.use_semantic = use_semantic
        self.use_rescoring = use_rescoring
        self._embedding_matcher: EmbeddingMatcher | None = None
        self._tfidf_matcher: TFIDFMatcher | None = None
        self._web_grounder: WebGrounder | None = None
        self._nli_grounder = shared_nli_grounder() if use_nli else None
        self._semantic_lock = Lock()
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
        self,
        claim: str,
        raw_context: object,
        *,
        nli_scores: list[dict] | None = None,
    ) -> tuple[str, float, list[SourceMatch]]:
        context = await verification_workers.run(self._normalize_context, raw_context)
        if self._nli_grounder is not None and context:
            if nli_scores is None:
                context_texts = [c[1] for c in context]
                nli_scores = await self._nli_grounder.score(claim, context_texts)
            if nli_scores:
                return await self._ground_nli(claim, context, nli_scores)

        claim_terms = self._terms(claim) if context else set()
        matches = (
            await verification_workers.run(self._match_against_context, claim, context, claim_terms)
            if claim_terms
            else []
        )
        refutations = [match for match in matches if match.refutes]
        if refutations:
            support = [
                SourceMatch(source_id, 1.0, text[:240])
                for source_id, text in context
                if _proposition(text) == _proposition(claim)
            ]
            if support:
                opposing = refutations[0]
                return (
                    "unclear",
                    0.0,
                    [
                        support[0],
                        SourceMatch(opposing.source_id, opposing.score, opposing.excerpt),
                    ],
                )
            return "unsupported", refutations[0].score, refutations[:3]

        if not matches and self._web_grounder and self._web_grounder.is_available():
            web_sources = await self._web_grounder.ground(claim, raise_on_error=True)
            if web_sources:
                matches = web_sources

        if not matches:
            return "unclear", 0.0, []

        matches.sort(key=lambda m: m.score, reverse=True)
        top_score = matches[0].score

        if top_score >= 0.55:
            return "supported", top_score, matches[:3]
        if top_score <= 0.3:
            return "unsupported", top_score, matches[:3]
        return "unclear", top_score, matches[:3]

    async def _ground_nli(
        self, claim: str, context: list[tuple[str, str]], scores: list[dict]
    ) -> tuple[str, float, list[SourceMatch]]:
        def citations(relation: str) -> list[SourceMatch]:
            ranked = sorted(scores, key=lambda score: score[relation], reverse=True)
            matches = []
            for score in ranked[:3]:
                source_id, text = context[score["chunk_index"]]
                matches.append(SourceMatch(source_id, score[relation], text[:240]))
            return matches

        status, confidence, _ = self._nli_grounder.interpret(scores)
        supports = citations("entailment")
        refutes = citations("contradiction")
        if supports[0].score > 0.5 and refutes[0].score > 0.5:
            return "unclear", 0.0, [supports[0], refutes[0]]
        if status == "unsupported":
            return (
                status,
                confidence,
                [
                    SourceMatch(match.source_id, match.score, match.excerpt, refutes=True)
                    for match in refutes
                    if match.score > 0.5
                ],
            )
        if status == "supported":
            sources = [match for match in supports if match.score > 0.5]
            if self.use_rescoring:
                # Re-score the actual passages that licensed the entailment.
                passages = [
                    context[score["chunk_index"]] for score in scores if score["entailment"] > 0.5
                ]
                warrant = await verification_workers.run(self._warrant_score, claim, passages)
                if warrant < 0.35:
                    return "unclear", confidence * warrant, sources
            return status, confidence, sources
        return status, confidence, supports[:1]

    @property
    def uses_nli(self) -> bool:
        return self._nli_grounder is not None

    async def batch_nli(self, claims: list[str], raw_context: object) -> list[list[dict]]:
        if self._nli_grounder is None:
            return [[] for _ in claims]
        context = await verification_workers.run(self._normalize_context, raw_context)
        return await self._nli_grounder.score_batch(claims, [text for _, text in context])

    def _match_against_context(
        self,
        claim: str,
        context: list[tuple[str, str]],
        claim_terms: set[str],
    ) -> list[SourceMatch]:
        matches: list[SourceMatch] = []
        context_texts = [c[1] for c in context]

        semantic_scores = []
        if self.use_semantic and len(context_texts) > 0:
            semantic_scores = self._compute_semantic_scores(claim, context_texts)
        else:
            semantic_scores = [0.0] * len(context_texts)

        proposition = _proposition(claim)
        for i, (source_id, text) in enumerate(context):
            if _explicit_refutation(proposition, _proposition(text)):
                matches.append(SourceMatch(source_id, 0.9, text[:240], refutes=True))
                continue
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
                    ),
                )
        return matches

    def _compute_semantic_scores(
        self,
        claim: str,
        context_texts: list[str],
    ) -> list[float]:
        with self._semantic_lock:
            embeddings = self.embedding_matcher.encode([claim, *context_texts])
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

    def _warrant_score(self, claim: str, context: list[tuple[str, str]]) -> float:
        """Claim-conditioned warrant score: max evidence-span overlap vs full claim."""
        claim_terms = self._terms(claim)
        if not claim_terms:
            return 0.0
        context_texts = [c[1] for c in context]
        sem_scores = (
            self._compute_semantic_scores(claim, context_texts)
            if self.use_semantic and context_texts
            else [0.0] * len(context_texts)
        )
        best = 0.0
        for i, (_, text) in enumerate(context):
            source_terms = self._terms(text)
            kw = len(claim_terms & source_terms) / len(claim_terms) if claim_terms else 0.0
            sem = sem_scores[i] if i < len(sem_scores) else 0.0
            combined = kw * 0.4 + sem * 0.6 if sem > 0 else kw
            best = max(best, combined)
        return best

    def _terms(self, text: str) -> set[str]:
        return {
            word for word in _WORD.findall(text.lower()) if word not in STOPWORDS and len(word) > 2
        }
