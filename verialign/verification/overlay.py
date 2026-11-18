"""Public response models for the verification overlay."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer

from verialign.verification.models import VerificationResult

ClaimLabel = Literal["verified", "unverifiable", "contradicted", "no_source"]
PolicyAction = Literal["pass-through", "warn", "block"]
Score = Annotated[float, Field(ge=0, le=1)]


class Evidence(BaseModel):
    source_id: str
    score: Score
    excerpt: str
    refutes: bool = False

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        data = handler(self)
        if not self.refutes:
            data.pop("refutes", None)
        return data


class ClaimResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str
    label: ClaimLabel
    confidence: Score
    evidence: list[Evidence]


class Overlay(BaseModel):
    model_config = ConfigDict(extra="allow")

    trust_score: Score | None
    claims: list[ClaimResult]
    policy_action: PolicyAction
    status: Literal["complete", "unverifiable"]

    @classmethod
    def from_result(
        cls,
        result: VerificationResult,
        policy_action: PolicyAction = "pass-through",
        *,
        failed: bool = False,
    ) -> "Overlay":
        payload = result.to_dict()
        conflicts = {
            text.lower()
            for contradiction in result.contradictions
            for text in (contradiction.claim_a, contradiction.claim_b)
        }
        for claim, original in zip(payload["claims"], result.claims, strict=True):
            if claim["status"] == "unverifiable":
                label = "unverifiable"
            elif claim["text"].lower() in conflicts or any(
                source.refutes for source in original.sources
            ):
                label = "contradicted"
            elif claim["status"] == "supported":
                label = "verified"
            elif claim["sources"]:
                label = "unverifiable"
            else:
                label = "no_source"
            claim.update(label=label, evidence=claim["sources"])
        return cls.model_validate(
            {
                **payload,
                "trust_score": result.trust_score,
                "policy_action": policy_action,
                "status": "unverifiable" if failed or result.incomplete else "complete",
            },
        )
