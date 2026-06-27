from typing import Callable

from verialign.verification.claim_extractor import ClaimExtractor
from verialign.verification.confidence_scorer import ConfidenceScorer
from verialign.verification.contradiction_detector import ContradictionDetector
from verialign.verification.checklist_generator import ChecklistGenerator
from verialign.verification.models import (
    VerificationResult,
    VerifiedClaim,
    Contradiction,
    ChecklistItem,
)
from verialign.verification.source_grounder import SourceGrounder
from verialign.verification.verification_cache import VerificationCache


class VerificationEngine:
    def __init__(
        self,
        llm_client: Callable | None = None,
        web_api_key: str | None = None,
        web_provider: str = "tavily",
        cache_ttl: int = 300,
        cache: VerificationCache | None = None,
    ) -> None:
        self.claim_extractor = ClaimExtractor(llm_client=llm_client)
        self.source_grounder = SourceGrounder(
            web_api_key=web_api_key, web_provider=web_provider
        )
        self.contradiction_detector = ContradictionDetector()
        self.confidence_scorer = ConfidenceScorer()
        self.checklist_generator = ChecklistGenerator()
        self._cache = cache or VerificationCache(ttl_seconds=cache_ttl)

    async def verify(
        self, text: str, context: object, response_data: dict | None = None
    ) -> VerificationResult:
        cached = self._cache.get(text, context)
        if cached is not None:
            return cached
        claims = []
        claim_texts = await self.claim_extractor.extract(text)

        for idx, claim_text in enumerate(claim_texts):
            status, confidence, sources = await self.source_grounder.ground(
                claim_text, context
            )

            if response_data:
                logprobs_info = self.confidence_scorer.score_response(response_data)
                if logprobs_info:
                    token_logprobs = [logprobs_info["avg_logprob"]] * len(
                        claim_text.split()
                    )
                    confidence_score = self.confidence_scorer.score_claim(
                        claim_text, confidence, token_logprobs
                    )
                    confidence = confidence_score.score

            claim_id = f"claim-{idx}"
            claims.append(
                VerifiedClaim(
                    text=claim_text,
                    status=status,
                    confidence=round(confidence, 3),
                    sources=sources,
                    claim_id=claim_id,
                    sentence_offset=idx,
                )
            )

        contradictions = self.contradiction_detector.detect(claim_texts)

        checklist = self.checklist_generator.generate(
            text, claim_texts, [c.to_dict() for c in claims]
        )

        result = VerificationResult(
            claims=claims,
            contradictions=[Contradiction(**c.to_dict()) for c in contradictions],
            checklist=[ChecklistItem(**item.to_dict()) for item in checklist],
        )
        self._cache.set(text, context, result)
        return result
