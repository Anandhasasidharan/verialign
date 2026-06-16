import pytest
from verialign.verification.checklist_generator import ChecklistGenerator


class TestChecklistGenerator:
    def setup_method(self):
        self.generator = ChecklistGenerator()

    def test_generate_empty(self):
        items = self.generator.generate("", [], [])
        assert items == []

    def test_generate_verification_items_unsupported(self):
        claims = ["The Earth is flat."]
        verification = [{"status": "unsupported", "confidence": 0.2}]
        items = self.generator.generate("The Earth is flat.", claims, verification)
        unsupported_items = [
            i for i in items if i.category == "verification" and i.priority == "high"
        ]
        assert len(unsupported_items) >= 1

    def test_generate_verification_items_unclear_low_confidence(self):
        claims = ["Something unclear."]
        verification = [{"status": "unclear", "confidence": 0.3}]
        items = self.generator.generate("Something unclear.", claims, verification)
        unclear_items = [
            i for i in items if i.category == "verification" and i.priority == "medium"
        ]
        assert len(unclear_items) >= 1

    def test_generate_action_items_security(self):
        text = "Make sure to encrypt the password and store the secret key securely."
        items = self.generator.generate(text, [], [])
        security_items = [i for i in items if i.category == "security"]
        assert len(security_items) >= 1

    def test_generate_action_items_deployment(self):
        text = "Deploy the docker container to kubernetes using the CI/CD pipeline."
        items = self.generator.generate(text, [], [])
        deployment_items = [i for i in items if i.category == "deployment"]
        assert len(deployment_items) >= 1

    def test_generate_action_items_database(self):
        text = "Run the database migration and create the index on the users table."
        items = self.generator.generate(text, [], [])
        db_items = [i for i in items if i.category == "database"]
        assert len(db_items) >= 1

    def test_generate_claim_category_causal(self):
        claims = [
            "A causes B because of mechanism X.",
            "C results in D since E happened.",
        ]
        items = self.generator.generate("", claims, [])
        causal_items = [
            i
            for i in items
            if i.category == "consistency" and "causal" in i.description.lower()
        ]
        assert len(causal_items) >= 1

    def test_generate_claim_category_conditional(self):
        claims = [
            "If X happens then Y will occur.",
            "When A is true then B follows.",
        ]
        items = self.generator.generate("", claims, [])
        conditional_items = [
            i
            for i in items
            if i.category == "consistency" and "conditional" in i.description.lower()
        ]
        assert len(conditional_items) >= 1

    def test_to_dict(self):
        from verialign.verification.models import ChecklistItem

        items = [
            ChecklistItem(
                description="Test item",
                category="test",
                priority="high",
                related_claims=["claim1"],
            ),
        ]
        dicts = self.generator.to_dict(items)
        assert len(dicts) == 1
        assert dicts[0]["description"] == "Test item"
        assert dicts[0]["category"] == "test"
        assert dicts[0]["priority"] == "high"
        assert dicts[0]["related_claims"] == ["claim1"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
