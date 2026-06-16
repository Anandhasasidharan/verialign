from verialign.verification.models import ChecklistItem as ModelChecklistItem


class ChecklistGenerator:
    ACTION_KEYWORDS = {
        "security": [
            "password",
            "encrypt",
            "authentication",
            "authorization",
            "token",
            "secret",
            "key",
            "ssl",
            "tls",
            "certificate",
        ],
        "deployment": [
            "deploy",
            "install",
            "configure",
            "setup",
            "docker",
            "kubernetes",
            "k8s",
            "ci/cd",
            "pipeline",
            "environment",
        ],
        "database": [
            "migration",
            "schema",
            "query",
            "index",
            "backup",
            "transaction",
            "connection",
            "pool",
        ],
        "api": [
            "endpoint",
            "request",
            "response",
            "rate limit",
            "timeout",
            "retry",
            "pagination",
            "version",
        ],
        "testing": [
            "test",
            "mock",
            "assert",
            "coverage",
            "integration",
            "unit",
            "e2e",
            "fixture",
        ],
        "performance": [
            "cache",
            "optimize",
            "latency",
            "throughput",
            "memory",
            "cpu",
            "bottleneck",
            "profile",
        ],
        "data": [
            "validate",
            "transform",
            "schema",
            "etl",
            "pipeline",
            "quality",
            "privacy",
            "pii",
            "gdpr",
        ],
    }

    CLAIM_CATEGORIES = {
        "factual": [
            "is",
            "are",
            "was",
            "were",
            "has",
            "have",
            "contains",
            "supports",
            "uses",
            "requires",
            "returns",
            "stores",
        ],
        "conditional": ["if", "when", "unless", "provided that", "assuming"],
        "causal": [
            "because",
            "since",
            "therefore",
            "thus",
            "leads to",
            "results in",
            "causes",
        ],
        "comparative": [
            "better",
            "worse",
            "faster",
            "slower",
            "more",
            "less",
            "than",
            "compared to",
        ],
        "temporal": [
            "before",
            "after",
            "during",
            "while",
            "since",
            "until",
            "by the time",
        ],
    }

    def generate(
        self, response_text: str, claims: list[str], verification_results: list[dict]
    ) -> list[ModelChecklistItem]:
        items: list[ModelChecklistItem] = []

        items.extend(self._generate_verification_items(claims, verification_results))
        items.extend(self._generate_action_items(response_text))
        items.extend(self._generate_claim_category_items(claims))

        return items

    def _generate_verification_items(
        self, claims: list[str], verification_results: list[dict]
    ) -> list[ModelChecklistItem]:
        items: list[ModelChecklistItem] = []

        for i, (claim, result) in enumerate(zip(claims, verification_results)):
            status = result.get("status", "unclear")
            confidence = result.get("confidence", 0.0)

            if status == "unsupported":
                items.append(
                    ModelChecklistItem(
                        description=f"Verify unsupported claim: {claim[:100]}...",
                        category="verification",
                        priority="high",
                        related_claims=[claim],
                    )
                )
            elif status == "unclear" and confidence < 0.5:
                items.append(
                    ModelChecklistItem(
                        description=f"Clarify ambiguous claim: {claim[:100]}...",
                        category="verification",
                        priority="medium",
                        related_claims=[claim],
                    )
                )
            elif status == "supported" and confidence < 0.7:
                items.append(
                    ModelChecklistItem(
                        description=f"Double-check weakly supported claim: {claim[:100]}...",
                        category="verification",
                        priority="low",
                        related_claims=[claim],
                    )
                )

        return items

    def _generate_action_items(self, text: str) -> list[ModelChecklistItem]:
        items: list[ModelChecklistItem] = []
        text_lower = text.lower()

        for category, keywords in self.ACTION_KEYWORDS.items():
            matches = [kw for kw in keywords if kw in text_lower]
            if matches:
                priority = (
                    "high" if category in ("security", "deployment") else "medium"
                )
                items.append(
                    ModelChecklistItem(
                        description=f"Review {category} implications (mentions: {', '.join(matches[:3])})",
                        category=category,
                        priority=priority,
                        related_claims=[],
                    )
                )

        return items

    def _generate_claim_category_items(
        self, claims: list[str]
    ) -> list[ModelChecklistItem]:
        items: list[ModelChecklistItem] = []
        categories_found: dict[str, int] = {}

        for claim in claims:
            claim_lower = claim.lower()
            for category, keywords in self.CLAIM_CATEGORIES.items():
                if any(kw in claim_lower for kw in keywords):
                    categories_found[category] = categories_found.get(category, 0) + 1

        for category, count in categories_found.items():
            if count >= 2:
                items.append(
                    ModelChecklistItem(
                        description=f"Multiple {category} claims detected ({count}) - verify consistency",
                        category="consistency",
                        priority="medium"
                        if category in ("causal", "conditional")
                        else "low",
                        related_claims=[],
                    )
                )

        return items

    def to_dict(self, items: list[ModelChecklistItem]) -> list[dict]:
        return [
            {
                "description": item.description,
                "category": item.category,
                "priority": item.priority,
                "related_claims": item.related_claims,
            }
            for item in items
        ]
