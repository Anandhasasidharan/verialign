from collections.abc import Callable

from verialign.verification.checklist_generator import ChecklistGenerator
from verialign.verification.claim_extractor import ClaimExtractor
from verialign.verification.confidence_scorer import ConfidenceScorer
from verialign.verification.contradiction_detector import ContradictionDetector
from verialign.verification.models import (
    ChecklistItem,
    Contradiction,
    VerificationResult,
    VerifiedClaim,
)
from verialign.verification.source_grounder import SourceGrounder
from verialign.verification.tool_grounder import ToolGrounder
from verialign.verification.trust_scorer import TrustScorer
from verialign.verification.verification_cache import VerificationCache


class VerificationEngine:
    def __init__(
        self,
        llm_client: Callable | None = None,
        web_api_key: str | None = None,
        web_provider: str = "tavily",
        cache_ttl: int = 300,
        cache: VerificationCache | None = None,
        use_rescoring: bool = False,
    ) -> None:
        self.claim_extractor = ClaimExtractor(llm_client=llm_client)
        self.source_grounder = SourceGrounder(
            use_nli=True,
            web_api_key=web_api_key,
            web_provider=web_provider,
            use_rescoring=use_rescoring,
        )
        self.contradiction_detector = ContradictionDetector()
        self.confidence_scorer = ConfidenceScorer()
        self.checklist_generator = ChecklistGenerator()
        self.trust_scorer = TrustScorer()
        self.tool_grounder = ToolGrounder()
        self._cache = cache or VerificationCache(ttl_seconds=cache_ttl)

    async def verify(
        self,
        text: str,
        context: object,
        response_data: dict | None = None,
        tool_calls: list[dict] | None = None,
    ) -> VerificationResult:
        # Bypass cache when tool_calls are present — cache key is text+context only
        if not tool_calls:
            cached = self._cache.get(text, context)
            if cached is not None:
                return cached
        claims = []
        claim_texts = await self.claim_extractor.extract(text)

        for idx, claim_text in enumerate(claim_texts):
            # Tool-call grounding: if a claim is about a tool result, check actual tool output first.
            # This is the shared primitive with AgentGuard/AgentOps.
            if tool_calls:
                t_status, t_conf, _reason = self.tool_grounder.ground(
                    claim_text,
                    tool_calls,
                )
                if t_status is not None:
                    # Build a source pointing at the tool record for auditability
                    from verialign.verification.models import SourceMatch as _SM

                    tool_sources = (
                        [
                            _SM(
                                source_id=f"tool:{tool_calls[0].get('name', 'unknown')}"
                                if tool_calls
                                else "tool",
                                score=t_conf,
                                excerpt=str(tool_calls[0].get("result", ""))[:240],
                            ),
                        ]
                        if t_status == "unsupported"
                        else []
                    )
                    claim_id = f"claim-{idx}"
                    claims.append(
                        VerifiedClaim(
                            text=claim_text,
                            status=t_status,
                            confidence=round(t_conf, 3),
                            sources=tool_sources,
                            claim_id=claim_id,
                            sentence_offset=idx,
                        ),
                    )
                    continue
            status, confidence, sources = await self.source_grounder.ground(
                claim_text,
                context,
            )

            if response_data:
                logprobs_info = self.confidence_scorer.score_response(response_data)
                if logprobs_info:
                    token_logprobs = [logprobs_info["avg_logprob"]] * len(
                        claim_text.split(),
                    )
                    confidence_score = self.confidence_scorer.score_claim(
                        claim_text,
                        confidence,
                        token_logprobs,
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
                ),
            )

        contradictions = [
            Contradiction(**c.to_dict()) for c in self.contradiction_detector.detect(claim_texts)
        ]
        checklist = [
            ChecklistItem(**item.to_dict())
            for item in self.checklist_generator.generate(
                text,
                claim_texts,
                [c.to_dict() for c in claims],
            )
        ]

        partial = VerificationResult(
            claims=claims,
            contradictions=contradictions,
            checklist=checklist,
        )
        trust_score = self.trust_scorer.score(partial)
        result = VerificationResult(
            claims=claims,
            contradictions=contradictions,
            checklist=checklist,
            trust_score=trust_score,
        )
        if not tool_calls:
            self._cache.set(text, context, result)
        return result
