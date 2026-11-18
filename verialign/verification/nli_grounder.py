import logging
from functools import lru_cache

from verialign.verification.workers import BoundedExecutor

logger = logging.getLogger(__name__)
_nli_worker = BoundedExecutor("verialign-nli", workers=1, capacity=2)
_MAX_PAIRS = 64


class NLIGrounder:
    def __init__(
        self,
        model_name: str = "cross-encoder/nli-deberta-v3-base",
        threshold: float = 0.5,
    ) -> None:
        self._model_name = model_name
        self._threshold = threshold
        self._model = None
        self._tokenizer = None
        self._device = "cpu"
        self._load_failed = False

    def _lazy_init(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self._model_name,
            )
            if torch.cuda.is_available():
                self._device = "cuda"
                self._model = self._model.to("cuda")
        except ImportError:
            logger.warning("nli_transformers_not_available")
            self._model = False
        except Exception:
            logger.warning("nli_model_load_failed")
            self._model = False
            self._load_failed = True

    def is_available(self) -> bool:
        self._lazy_init()
        return self._model is not None and self._model is not False

    async def score(self, claim: str, context_chunks: list[str]) -> list[dict]:
        return (await self.score_batch([claim], context_chunks))[0]

    async def score_batch(self, claims: list[str], context_chunks: list[str]) -> list[list[dict]]:
        if not claims or not context_chunks:
            return [[] for _ in claims]
        return await _nli_worker.run(self._score_batch, claims, context_chunks)

    def _score_batch(self, claims: list[str], context_chunks: list[str]) -> list[list[dict]]:
        if not self.is_available():
            if self._load_failed:
                raise RuntimeError("NLI model unavailable")
            return [[] for _ in claims]
        if len(claims) * len(context_chunks) > _MAX_PAIRS:
            raise TimeoutError("NLI batch exceeds its pair limit")
        try:
            import torch

            pairs = [(chunk, claim) for claim in claims for chunk in context_chunks]
            inputs = self._tokenizer(
                pairs,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            ).to(self._device)

            with torch.no_grad():
                outputs = self._model(**inputs)
                probs = torch.nn.functional.softmax(outputs.logits, dim=1)

            indices = {
                label.lower(): int(index) for index, label in self._model.config.id2label.items()
            }
            width = len(context_chunks)
            return [
                [
                    {
                        "chunk_index": chunk,
                        **{
                            label: round(probs[offset + chunk][indices[label]].item(), 4)
                            for label in ("entailment", "neutral", "contradiction")
                        },
                    }
                    for chunk in range(width)
                ]
                for offset in range(0, len(pairs), width)
            ]
        except Exception as exc:
            logger.warning("nli_scoring_failed")
            raise RuntimeError("NLI inference failed") from exc

    async def ground(
        self,
        claim: str,
        context_chunks: list[str],
        threshold: float | None = None,
    ) -> tuple[str, float, list[dict]]:
        return self.interpret(await self.score(claim, context_chunks), threshold)

    def interpret(
        self, scores: list[dict], threshold: float | None = None
    ) -> tuple[str, float, list[dict]]:
        if not scores:
            return "unclear", 0.0, []

        threshold = self._threshold if threshold is None else threshold
        max_contradiction = max(s["contradiction"] for s in scores)
        max_entailment = max(s["entailment"] for s in scores)

        if max_contradiction > threshold and max_contradiction > max_entailment:
            return "unsupported", max_contradiction, scores

        if max_entailment > threshold:
            return "supported", max_entailment, scores

        return "unclear", max_entailment, scores


@lru_cache(maxsize=1)
def shared_nli_grounder() -> NLIGrounder:
    return NLIGrounder()
