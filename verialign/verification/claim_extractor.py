import json
import re
from typing import Any

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_FACTUAL_CUES = re.compile(
    r"\b(is|are|was|were|has|have|had|can|will|supports?|contains?|uses?|requires?|returns?|stores?)\b",
    re.IGNORECASE,
)
_META_SENTENCE = re.compile(
    r"\b(latest user request|user asked|you asked|this response|as an ai|i can|i cannot|i'm unable)\b",
    re.IGNORECASE,
)

_LLM_EXTRACT_PROMPT = """Extract factual claims from the following text. Return a JSON array of strings.
Only include claims that make verifiable factual assertions about the world.
Exclude opinions, instructions, questions, and meta-commentary about the response itself.

Text:
{text}

Return a JSON array of claim strings:"""


class ClaimExtractor:
    def __init__(self, llm_client: Any | None = None) -> None:
        self.llm_client = llm_client

    async def extract(self, text: str, use_llm_fallback: bool = True) -> list[str]:
        if not text.strip():
            return []

        claims = self._extract_regex(text)

        if len(claims) < 2 and use_llm_fallback and self.llm_client:
            llm_claims = await self._extract_with_llm(text)
            if len(llm_claims) > len(claims):
                claims = llm_claims

        # Claim decomposition: split compound sentences into atomic sub-claims
        decomposed: list[str] = []
        for claim in claims:
            subs = self._decompose(claim)
            decomposed.extend(subs)
        return decomposed

    def _extract_regex(self, text: str) -> list[str]:
        claims: list[str] = []
        for sentence in _SENTENCE_BOUNDARY.split(text.strip()):
            cleaned = self._clean(sentence)
            if not cleaned:
                continue
            if _META_SENTENCE.search(cleaned):
                continue
            if _FACTUAL_CUES.search(cleaned):
                claims.append(cleaned)
        return claims

    async def _extract_with_llm(self, text: str) -> list[str]:
        try:
            prompt = _LLM_EXTRACT_PROMPT.format(text=text[:2000])
            result = self.llm_client(
                {"messages": [{"role": "user", "content": prompt}], "temperature": 0.1},
            )
            if hasattr(result, "__await__"):
                result = await result
            response = result if isinstance(result, dict) else {}
            content = (
                response.get("choices", [{}])[0].get("message", {}).get("content", "")
            )

            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1]
                content = content.rsplit("```", 1)[0]
            content = content.removeprefix("json")

            claims = json.loads(content)
            if isinstance(claims, list) and all(isinstance(c, str) for c in claims):
                return [c for c in claims if c.strip()]
        except Exception:
            pass
        return []

    def _decompose(self, claim: str) -> list[str]:
        # Split on ' and ' when both sides look like factual statements
        # e.g. "X is Y and Z does W" -> ["X is Y", "Z does W"]
        if " and " not in claim.lower():
            return [claim]
        # Avoid splitting short claims where 'and' is not clausal
        parts = re.split(r"\s+and\s+", claim, flags=re.IGNORECASE)
        if len(parts) < 2:
            return [claim]
        # Only decompose if multiple parts each contain a factual cue or looks like a clause
        atomic: list[str] = []
        for part in parts:
            part = part.strip().rstrip(",;")
            if not part:
                continue
            # Require at least 3 tokens and either a factual verb cue or capital start
            if _FACTUAL_CUES.search(part) or len(part.split()) >= 3:
                # Ensure sentence-ending punctuation for downstream grounding
                if not part.endswith((".", "!", "?")):
                    part = part + "."
                atomic.append(part)
        # If decomposition produced meaningful splits, use it; otherwise keep original
        if len(atomic) >= 2:
            return atomic
        return [claim]

    def _clean(self, sentence: str) -> str:
        return re.sub(r"\s+", " ", sentence).strip(" -\n\t")
