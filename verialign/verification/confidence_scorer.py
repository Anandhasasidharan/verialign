import math
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class ConfidenceScore:
    score: float
    method: str
    details: dict[str, Any]


class ConfidenceScorer:
    def __init__(self) -> None:
        self.logprob_weight = 0.7
        self.overlap_weight = 0.3

    def score_claim(
        self,
        claim: str,
        source_overlap: float,
        logprobs: list[float] | None = None,
    ) -> ConfidenceScore:
        if logprobs:
            return self._score_with_logprobs(claim, source_overlap, logprobs)
        return self._score_heuristic(claim, source_overlap)

    def _score_with_logprobs(
        self,
        claim: str,
        source_overlap: float,
        logprobs: list[float],
    ) -> ConfidenceScore:
        if not logprobs:
            return self._score_heuristic(claim, source_overlap)

        avg_logprob = sum(logprobs) / len(logprobs)
        prob = math.exp(avg_logprob)
        logprob_confidence = max(0.0, min(1.0, prob * 2))

        overlap_confidence = source_overlap

        combined = (
            self.logprob_weight * logprob_confidence
            + self.overlap_weight * overlap_confidence
        )

        return ConfidenceScore(
            score=round(combined, 3),
            method="logprob+overlap",
            details={
                "avg_logprob": round(avg_logprob, 4),
                "logprob_confidence": round(logprob_confidence, 3),
                "overlap_confidence": round(overlap_confidence, 3),
                "token_count": len(logprobs),
            },
        )

    def _score_heuristic(self, claim: str, source_overlap: float) -> ConfidenceScore:
        claim_length = len(claim.split())
        length_factor = min(1.0, claim_length / 20.0)

        hedging_phrases = [
            "might",
            "could",
            "possibly",
            "perhaps",
            "maybe",
            "likely",
            "unlikely",
            "probably",
            "seems",
            "appears",
            "suggests",
            "indicates",
            "around",
            "approximately",
        ]
        hedging_penalty = 0.0
        claim_lower = claim.lower()
        for phrase in hedging_phrases:
            if phrase in claim_lower:
                hedging_penalty += 0.05
        hedging_penalty = min(0.3, hedging_penalty)

        specificity_bonus = 0.0
        if any(char.isdigit() for char in claim):
            specificity_bonus += 0.1
        if re.search(r"\b(in|on|at|by)\s+\d{4}\b", claim):
            specificity_bonus += 0.1

        base_confidence = 0.5
        confidence = (
            base_confidence
            + (source_overlap * 0.4)
            + (length_factor * 0.1)
            - hedging_penalty
            + specificity_bonus
        )
        confidence = max(0.0, min(1.0, confidence))

        return ConfidenceScore(
            score=round(confidence, 3),
            method="heuristic",
            details={
                "source_overlap": round(source_overlap, 3),
                "length_factor": round(length_factor, 3),
                "hedging_penalty": round(hedging_penalty, 3),
                "specificity_bonus": round(specificity_bonus, 3),
                "claim_length": claim_length,
            },
        )

    def score_response(self, response_data: dict) -> dict[str, float] | None:
        choices = response_data.get("choices", [])
        if not choices:
            return None

        choice = choices[0]
        logprobs_data = choice.get("logprobs")
        if not logprobs_data:
            return None

        content = logprobs_data.get("content", [])
        if not content:
            return None

        token_logprobs = [token.get("logprob", 0.0) for token in content]
        if not token_logprobs:
            return None

        return {
            "avg_logprob": sum(token_logprobs) / len(token_logprobs),
            "min_logprob": min(token_logprobs),
            "token_count": len(token_logprobs),
        }
