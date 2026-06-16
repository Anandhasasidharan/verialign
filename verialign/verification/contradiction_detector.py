import re

from verialign.verification.models import Contradiction


class ContradictionDetector:
    NEGATION_PATTERNS = [
        (
            re.compile(r"\b(is|are|was|were)\b"),
            re.compile(
                r"\b(is not|are not|was not|were not|isn't|aren't|wasn't|weren't)\b"
            ),
        ),
        (
            re.compile(r"\b(can|will|does|do|did)\b"),
            re.compile(
                r"\b(cannot|can't|will not|won't|does not|doesn't|do not|don't|did not|didn't)\b"
            ),
        ),
        (
            re.compile(r"\b(has|have|had)\b"),
            re.compile(r"\b(has not|have not|had not|hasn't|haven't|hadn't)\b"),
        ),
        (
            re.compile(r"\b(always|all|every|everyone|everything)\b"),
            re.compile(r"\b(never|none|no one|nothing)\b"),
        ),
        (
            re.compile(r"\b(must|should|need to)\b"),
            re.compile(r"\b(must not|mustn't|should not|shouldn't|need not|needn't)\b"),
        ),
    ]

    VERB_ANTONYMS = {
        "increase": "decrease",
        "decrease": "increase",
        "rise": "fall",
        "fall": "rise",
        "grow": "shrink",
        "shrink": "grow",
        "add": "remove",
        "remove": "add",
        "enable": "disable",
        "disable": "enable",
        "allow": "deny",
        "deny": "allow",
        "accept": "reject",
        "reject": "accept",
        "true": "false",
        "false": "true",
        "yes": "no",
        "no": "yes",
        "support": "oppose",
        "oppose": "support",
        "agree": "disagree",
        "disagree": "agree",
        "before": "after",
        "after": "before",
        "first": "last",
        "last": "first",
        "minimum": "maximum",
        "maximum": "minimum",
    }

    def detect(self, claims: list[str]) -> list[Contradiction]:
        contradictions: list[Contradiction] = []

        for i, claim_a in enumerate(claims):
            for claim_b in claims[i + 1 :]:
                contradiction = self._check_pair(claim_a, claim_b)
                if contradiction:
                    contradictions.append(contradiction)

        return contradictions

    def _check_pair(self, claim_a: str, claim_b: str) -> Contradiction | None:
        a_lower = claim_a.lower()
        b_lower = claim_b.lower()

        negation = self._check_negation(a_lower, b_lower)
        if negation:
            return negation

        antonym = self._check_antonyms(a_lower, b_lower)
        if antonym:
            return antonym

        numeric = self._check_numeric_contradiction(a_lower, b_lower)
        if numeric:
            return numeric

        return None

    def _check_negation(self, a: str, b: str) -> Contradiction | None:
        for pos_pattern, neg_pattern in self.NEGATION_PATTERNS:
            if pos_pattern.search(a) and neg_pattern.search(b):
                if self._similar_subject(a, b):
                    return Contradiction(
                        claim_a=a,
                        claim_b=b,
                        type="negation",
                        confidence=0.8,
                    )
            if pos_pattern.search(b) and neg_pattern.search(a):
                if self._similar_subject(a, b):
                    return Contradiction(
                        claim_a=a,
                        claim_b=b,
                        type="negation",
                        confidence=0.8,
                    )
        return None

    def _check_antonyms(self, a: str, b: str) -> Contradiction | None:
        for verb, antonym in self.VERB_ANTONYMS.items():
            if verb in a and antonym in b:
                if self._similar_subject(a, b):
                    return Contradiction(
                        claim_a=a,
                        claim_b=b,
                        type="antonym",
                        confidence=0.7,
                    )
            if verb in b and antonym in a:
                if self._similar_subject(a, b):
                    return Contradiction(
                        claim_a=a,
                        claim_b=b,
                        type="antonym",
                        confidence=0.7,
                    )
        return None

    def _check_numeric_contradiction(self, a: str, b: str) -> Contradiction | None:
        numbers_a = re.findall(r"\b\d+(?:\.\d+)?\b", a)
        numbers_b = re.findall(r"\b\d+(?:\.\d+)?\b", b)

        if numbers_a and numbers_b:
            if self._similar_subject(a, b):
                if numbers_a != numbers_b:
                    return Contradiction(
                        claim_a=a,
                        claim_b=b,
                        type="numeric",
                        confidence=0.6,
                    )
        return None

    def _similar_subject(self, a: str, b: str) -> bool:
        words_a = set(re.findall(r"\b[a-z]{3,}\b", a))
        words_b = set(re.findall(r"\b[a-z]{3,}\b", b))

        common = words_a & words_b
        if len(common) >= 2:
            return True

        stopwords = {
            "the",
            "and",
            "or",
            "but",
            "not",
            "is",
            "are",
            "was",
            "were",
            "has",
            "have",
            "had",
            "can",
            "will",
            "does",
            "do",
            "did",
            "this",
            "that",
            "with",
            "for",
            "from",
        }
        words_a_filtered = words_a - stopwords
        words_b_filtered = words_b - stopwords

        if words_a_filtered and words_b_filtered:
            intersection = words_a_filtered & words_b_filtered
            union = words_a_filtered | words_b_filtered
            if union and len(intersection) / len(union) > 0.3:
                return True

        return False
