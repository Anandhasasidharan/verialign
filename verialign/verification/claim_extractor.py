import re
import json
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

        return claims

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
                {"messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
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
            if content.startswith("json"):
                content = content[4:]

            claims = json.loads(content)
            if isinstance(claims, list) and all(isinstance(c, str) for c in claims):
                return [c for c in claims if c.strip()]
        except Exception:
            pass
        return []

    def _clean(self, sentence: str) -> str:
        sentence = re.sub(r"\s+", " ", sentence).strip(" -\n\t")
        return sentence
