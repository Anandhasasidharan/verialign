import asyncio
from collections.abc import Callable
from dataclasses import replace

from verialign.verification.checklist_generator import ChecklistGenerator
from verialign.verification.claim_extractor import ClaimExtractor
from verialign.verification.confidence_scorer import ConfidenceScorer
from verialign.verification.contradiction_detector import ContradictionDetector
from verialign.verification.models import (
    SCAFFOLD_VERSION,
    ChecklistItem,
    SourceMatch,
    VerificationResult,
    VerifiedClaim,
)
from verialign.verification.source_grounder import SourceGrounder
from verialign.verification.tool_grounder import ToolGrounder
from verialign.verification.trust_scorer import TrustScorer
from verialign.verification.verification_cache import VerificationCache
from verialign.verification.workers import verification_workers

DEFAULT_MAX_CLAIMS = 16
DEFAULT_MAX_MS = 2000
DEFAULT_CLAIM_TIMEOUT_MS = 1200
DEFAULT_CONCURRENCY = 4


class VerificationEngine:
    def __init__(
        self,
        llm_client: Callable | None = None,
        web_api_key: str | None = None,
        web_provider: str = "tavily",
        cache_ttl: int = 300,
        cache: VerificationCache | None = None,
        use_rescoring: bool = False,
        use_nli: bool = True,
        *,
        max_claims: int = DEFAULT_MAX_CLAIMS,
        max_ms: float = DEFAULT_MAX_MS,
        claim_timeout_ms: float = DEFAULT_CLAIM_TIMEOUT_MS,
        concurrency: int = DEFAULT_CONCURRENCY,
        request_scope: object | None = None,
        llm_extractor_model: str | None = None,
    ) -> None:
        self.claim_extractor = ClaimExtractor(
            llm_client=llm_client, llm_timeout_seconds=max_ms * 0.0004
        )
        self.source_grounder = SourceGrounder(
            use_nli=use_nli,
            web_api_key=web_api_key,
            web_provider=web_provider,
            use_rescoring=use_rescoring,
        )
        self.contradiction_detector = ContradictionDetector()
        self.confidence_scorer = ConfidenceScorer()
        self.checklist_generator = ChecklistGenerator()
        self.trust_scorer = TrustScorer()
        self.tool_grounder = ToolGrounder()
        self._cache = cache if cache is not None else VerificationCache(ttl_seconds=cache_ttl)
        self._scope = {
            "scaffold": SCAFFOLD_VERSION,
            "request": request_scope,
            "claim_extractor": 2,
            "source_grounding": 2,
            "llm_extraction": llm_client is not None,
            "llm_extractor_model": llm_extractor_model,
            "nli": use_nli,
            "rescoring": use_rescoring,
            "web": web_provider if web_api_key else None,
        }
        if min(max_claims, concurrency, claim_timeout_ms) <= 0 or max_ms < 0:
            raise ValueError("Invalid verification budget")
        self.max_claims = max_claims
        self.max_ms = max_ms
        self.claim_timeout_ms = claim_timeout_ms
        self.concurrency = concurrency

    async def verify(
        self,
        text: str,
        context: object,
        response_data: dict | None = None,
        tool_calls: list[dict] | None = None,
    ) -> VerificationResult:
        claim_texts = []
        completed: dict[int, VerifiedClaim] = {}
        skipped = 0
        result = None
        try:
            async with asyncio.timeout(self.max_ms / 1000):
                logprobs = (
                    await verification_workers.run(
                        self.confidence_scorer.score_response, response_data
                    )
                    if response_data
                    else None
                )
                cache_context = {
                    **self._scope,
                    "semantic": self.source_grounder.use_semantic,
                    "context": context,
                    "response_model": response_data.get("model") if response_data else None,
                    "logprobs": logprobs,
                }
                if not tool_calls:
                    try:
                        cached = await verification_workers.run(
                            self._cache.get, text, cache_context
                        )
                    except Exception:
                        cached = None
                    if cached is not None and len(cached.claims) <= self.max_claims:
                        return cached

                extracted = await self.claim_extractor.extract(text)
                claim_texts = extracted[: self.max_claims]
                skipped = len(extracted) - len(claim_texts)
                await self._verify_claims(claim_texts, context, tool_calls, logprobs, completed)
                claims = [completed[i] for i in range(len(claim_texts))]
                if skipped or any(claim.status == "unverifiable" for claim in claims):
                    return VerificationResult(
                        claims, [], [], incomplete=True, skipped_claims=skipped
                    )

                result = await verification_workers.run(self._summarize, text, claim_texts, claims)
                if not tool_calls:
                    try:
                        await verification_workers.run(self._cache.set, text, cache_context, result)
                    except Exception:
                        pass
                return result
        except TimeoutError:
            if result is not None:
                return result
            claims = [
                completed[i] if i in completed else self._unavailable(claim, i)
                for i, claim in enumerate(claim_texts)
            ]
            return VerificationResult(claims, [], [], incomplete=True, skipped_claims=skipped)

    async def _verify_claims(
        self,
        claim_texts: list[str],
        context: object,
        tool_calls: list[dict] | None,
        logprobs: dict | None,
        completed: dict[int, VerifiedClaim],
    ) -> None:
        semaphore = asyncio.Semaphore(self.concurrency)
        batch = None

        async def verify_one(index: int, text: str) -> None:
            nonlocal batch
            async with semaphore:
                try:
                    async with asyncio.timeout(self.claim_timeout_ms / 1000):
                        tool = (
                            await verification_workers.run(
                                self.tool_grounder.ground, text, tool_calls
                            )
                            if tool_calls
                            else None
                        )
                        if tool and tool[0] is not None:
                            status, confidence, _ = tool
                            sources = (
                                [
                                    SourceMatch(
                                        source_id=f"tool:{tool_calls[0].get('name', 'unknown')}",
                                        score=confidence,
                                        excerpt=str(tool_calls[0].get("result", ""))[:240],
                                    ),
                                ]
                                if status == "unsupported"
                                else []
                            )
                        else:
                            if self.source_grounder.uses_nli and context:
                                if batch is None:
                                    batch = asyncio.create_task(
                                        self.source_grounder.batch_nli(claim_texts, context)
                                    )
                                scores = (await asyncio.shield(batch))[index]
                                status, confidence, sources = await self.source_grounder.ground(
                                    text, context, nli_scores=scores
                                )
                            else:
                                status, confidence, sources = await self.source_grounder.ground(
                                    text, context
                                )
                            if logprobs:
                                confidence = self.confidence_scorer.score_claim(
                                    text, confidence, [logprobs["avg_logprob"]]
                                ).score
                        completed[index] = VerifiedClaim(
                            text,
                            status,
                            round(confidence, 3),
                            sources,
                            claim_id=f"claim-{index}",
                            sentence_offset=index,
                        )
                except Exception:
                    completed[index] = self._unavailable(text, index)

        try:
            await asyncio.gather(*(verify_one(i, claim) for i, claim in enumerate(claim_texts)))
        finally:
            if batch is not None:
                batch.cancel()
                await asyncio.gather(batch, return_exceptions=True)

    def _summarize(
        self, text: str, claim_texts: list[str], claims: list[VerifiedClaim]
    ) -> VerificationResult:
        contradictions = self.contradiction_detector.detect(claim_texts)
        checklist = [
            ChecklistItem(**item.to_dict())
            for item in self.checklist_generator.generate(
                text, claim_texts, [claim.to_dict() for claim in claims]
            )
        ]
        result = VerificationResult(claims, contradictions, checklist)
        return replace(result, trust_score=self.trust_scorer.score(result))

    @staticmethod
    def _unavailable(text: str, index: int) -> VerifiedClaim:
        return VerifiedClaim(
            text, "unverifiable", 0.0, [], claim_id=f"claim-{index}", sentence_offset=index
        )
