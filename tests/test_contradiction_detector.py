import pytest
from verialign.verification.contradiction_detector import ContradictionDetector


class TestContradictionDetector:
    def setup_method(self):
        self.detector = ContradictionDetector()

    def test_negation_contradiction(self):
        claims = [
            "The system is secure.",
            "The system is not secure.",
        ]
        contradictions = self.detector.detect(claims)
        assert len(contradictions) == 1
        assert contradictions[0].type == "negation"
        assert contradictions[0].confidence == 0.8

    def test_antonym_contradiction(self):
        claims = [
            "The temperature will increase.",
            "The temperature will decrease.",
        ]
        contradictions = self.detector.detect(claims)
        assert len(contradictions) >= 1
        found = False
        for c in contradictions:
            if c.type == "antonym":
                found = True
                assert c.confidence == 0.7
        assert found

    def test_numeric_contradiction(self):
        claims = [
            "The population is 1000000.",
            "The population is 2000000.",
        ]
        contradictions = self.detector.detect(claims)
        assert len(contradictions) >= 1
        found = False
        for c in contradictions:
            if c.type == "numeric":
                found = True
                assert c.confidence == 0.6
        assert found

    def test_no_contradiction(self):
        claims = [
            "The sky is blue.",
            "The grass is green.",
        ]
        contradictions = self.detector.detect(claims)
        assert len(contradictions) == 0

    def test_multiple_claims(self):
        claims = [
            "Feature A increases performance.",
            "Feature A decreases performance.",
            "The system is fast.",
        ]
        contradictions = self.detector.detect(claims)
        assert len(contradictions) >= 1

    def test_empty_claims(self):
        contradictions = self.detector.detect([])
        assert contradictions == []

    def test_single_claim(self):
        claims = ["The system is secure."]
        contradictions = self.detector.detect(claims)
        assert contradictions == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
