import pytest
from verialign.verification.confidence_scorer import ConfidenceScorer


class TestConfidenceScorer:
    def setup_method(self):
        self.scorer = ConfidenceScorer()

    def test_heuristic_scoring_basic(self):
        claim = "The Earth orbits the Sun."
        score = self.scorer._score_heuristic(claim, 0.8)
        assert 0.0 <= score.score <= 1.0
        assert score.method == "heuristic"

    def test_heuristic_scoring_with_hedging(self):
        claim = "The Earth might orbit the Sun."
        score = self.scorer._score_heuristic(claim, 0.5)
        assert score.details["hedging_penalty"] > 0

    def test_heuristic_scoring_with_numbers(self):
        claim = "The population is 1000000."
        score = self.scorer._score_heuristic(claim, 0.5)
        assert score.details["specificity_bonus"] > 0

    def test_heuristic_scoring_with_date(self):
        claim = "The event happened in 2024."
        score = self.scorer._score_heuristic(claim, 0.5)
        assert score.details["specificity_bonus"] > 0

    def test_logprob_scoring(self):
        claim = "The Earth orbits the Sun."
        logprobs = [-0.1, -0.2, -0.15, -0.1, -0.05]
        score = self.scorer._score_with_logprobs(claim, 0.8, logprobs)
        assert 0.0 <= score.score <= 1.0
        assert score.method == "logprob+overlap"
        assert "avg_logprob" in score.details
        assert "token_count" in score.details

    def test_score_claim_uses_heuristic_when_no_logprobs(self):
        claim = "The Earth orbits the Sun."
        score = self.scorer.score_claim(claim, 0.8, logprobs=None)
        assert score.method == "heuristic"

    def test_score_claim_uses_logprobs_when_available(self):
        claim = "The Earth orbits the Sun."
        logprobs = [-0.1, -0.2, -0.15]
        score = self.scorer.score_claim(claim, 0.8, logprobs=logprobs)
        assert score.method == "logprob+overlap"

    def test_score_response_extracts_logprobs(self):
        response = {
            "choices": [
                {
                    "logprobs": {
                        "content": [
                            {"logprob": -0.1},
                            {"logprob": -0.2},
                            {"logprob": -0.15},
                        ]
                    }
                }
            ]
        }
        result = self.scorer.score_response(response)
        assert result is not None
        assert "avg_logprob" in result
        assert "token_count" in result

    def test_score_response_handles_missing_logprobs(self):
        response = {"choices": [{}]}
        result = self.scorer.score_response(response)
        assert result is None

    def test_score_response_handles_empty_choices(self):
        response = {"choices": []}
        result = self.scorer.score_response(response)
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
