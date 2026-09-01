from verialign.verification.models import VerificationResult


class TrustScorer:
    def score(self, result: VerificationResult) -> float:
        if not result.claims:
            return 0.5

        total = len(result.claims)
        supported = sum(1 for c in result.claims if c.status == "supported")
        unsupported = sum(1 for c in result.claims if c.status == "unsupported")
        avg_conf = sum(c.confidence for c in result.claims) / total if total else 0.0
        contradictions = len(result.contradictions)
        critical = sum(1 for i in result.checklist if i.priority == "high")

        score = (
            0.35 * avg_conf
            + 0.25 * (supported / total)
            + 0.20 * (1 - min(contradictions / max(total, 1), 1.0))
            + 0.20 * (1 - min(critical / max(len(result.checklist), 1), 1.0))
        )
        score -= 0.10 * min(unsupported, 3)
        score -= 0.05 * min(critical, 4)

        return round(max(0.0, min(1.0, score)), 3)
