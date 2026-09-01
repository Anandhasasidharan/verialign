from dataclasses import dataclass


@dataclass(frozen=True)
class SourceMatch:
    source_id: str
    score: float
    excerpt: str

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "score": self.score,
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True)
class Contradiction:
    claim_a: str
    claim_b: str
    type: str
    confidence: float

    def to_dict(self) -> dict:
        return {
            "claim_a": self.claim_a,
            "claim_b": self.claim_b,
            "type": self.type,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ChecklistItem:
    description: str
    category: str
    priority: str
    related_claims: list[str]

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "category": self.category,
            "priority": self.priority,
            "related_claims": self.related_claims,
        }


@dataclass(frozen=True)
class VerifiedClaim:
    text: str
    status: str
    confidence: float
    sources: list[SourceMatch]
    claim_id: str = ""
    sentence_offset: int = 0

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "status": self.status,
            "confidence": self.confidence,
            "sources": [source.to_dict() for source in self.sources],
            "claim_id": self.claim_id,
            "sentence_offset": self.sentence_offset,
        }


SCAFFOLD_VERSION = "verialign@0.1.0+nli-deberta-v3-base+rescoring"


@dataclass(frozen=True)
class VerificationResult:
    claims: list[VerifiedClaim]
    contradictions: list[Contradiction]
    checklist: list[ChecklistItem]
    cost: float | None = None
    trust_score: float | None = None
    scaffold: str = SCAFFOLD_VERSION

    @property
    def summary(self) -> dict:
        d: dict = {
            "total_claims": len(self.claims),
            "supported": sum(1 for claim in self.claims if claim.status == "supported"),
            "unsupported": sum(1 for claim in self.claims if claim.status == "unsupported"),
            "unclear": sum(1 for claim in self.claims if claim.status == "unclear"),
            "partially_supported": sum(
                1 for claim in self.claims if claim.status == "partially_supported"
            ),
            "contradictions_found": len(self.contradictions),
            "checklist_items": len(self.checklist),
        }
        if self.cost is not None:
            d["cost"] = self.cost
        if self.trust_score is not None:
            d["trust_score"] = self.trust_score
        return d

    @property
    def profile(self) -> dict:
        """System-level alignment profile (2605.04454: profiles not single scores)."""
        return {
            "scaffold": self.scaffold,
            "summary": self.summary,
            "trust_score": self.trust_score,
            "inferential_distance": "model-level unverified -> deployment-verified via scaffold; human checklist required for low-trust claims",
        }

    def to_dict(self) -> dict:
        d: dict = {
            "claims": [claim.to_dict() for claim in self.claims],
            "contradictions": [c.to_dict() for c in self.contradictions],
            "checklist": [item.to_dict() for item in self.checklist],
            "summary": self.summary,
            "profile": self.profile,
        }
        if self.cost is not None:
            d["cost"] = self.cost
        if self.trust_score is not None:
            d["trust_score"] = self.trust_score
        return d
