import pytest
from verialign.verification.models import (
    VerificationResult,
    VerifiedClaim,
    Contradiction,
    ChecklistItem,
    SourceMatch,
)
from verialign.verification.trust_scorer import TrustScorer


class TestTrustScorer:
    def setup_method(self):
        self.scorer = TrustScorer()

    def _make_claim(self, status: str, confidence: float = 0.9) -> VerifiedClaim:
        return VerifiedClaim(
            text="test claim",
            status=status,
            confidence=confidence,
            sources=[],
            claim_id="c1",
        )

    def test_all_supported_high_trust(self):
        claims = [self._make_claim("supported", 0.95) for _ in range(5)]
        result = VerificationResult(claims=claims, contradictions=[], checklist=[])
        score = self.scorer.score(result)
        assert 0.90 <= score <= 1.0

    def test_all_unsupported_low_trust(self):
        claims = [self._make_claim("unsupported", 0.3) for _ in range(5)]
        result = VerificationResult(claims=claims, contradictions=[], checklist=[])
        score = self.scorer.score(result)
        assert score < 0.30

    def test_contradictions_reduce_trust(self):
        claims = [self._make_claim("supported") for _ in range(3)]
        result_a = VerificationResult(claims=claims, contradictions=[], checklist=[])
        result_b = VerificationResult(
            claims=claims,
            contradictions=[Contradiction(claim_a="a", claim_b="b", type="negation", confidence=0.8)],
            checklist=[],
        )
        score_a = self.scorer.score(result_a)
        score_b = self.scorer.score(result_b)
        assert score_b < score_a

    def test_critical_checklist_reduces_trust(self):
        claims = [self._make_claim("supported") for _ in range(3)]
        result_a = VerificationResult(claims=claims, contradictions=[], checklist=[])
        result_b = VerificationResult(
            claims=claims,
            contradictions=[],
            checklist=[
                ChecklistItem(description="fix", category="security", priority="high", related_claims=[])
            ],
        )
        score_a = self.scorer.score(result_a)
        score_b = self.scorer.score(result_b)
        assert score_b < score_a

    def test_empty_claims_neutral(self):
        result = VerificationResult(claims=[], contradictions=[], checklist=[])
        assert self.scorer.score(result) == 0.5

    def test_score_clamped_zero(self):
        claims = [self._make_claim("unsupported", 0.0) for _ in range(5)]
        result = VerificationResult(claims=claims, contradictions=[], checklist=[])
        assert self.scorer.score(result) >= 0.0

    def test_trust_score_in_verification_result(self):
        claims = [self._make_claim("supported", 0.95) for _ in range(3)]
        result = VerificationResult(claims=claims, contradictions=[], checklist=[], trust_score=0.9)
        d = result.to_dict()
        assert d["trust_score"] == 0.9
        assert d["summary"]["trust_score"] == 0.9
