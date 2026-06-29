import logging

logger = logging.getLogger(__name__)


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

    def _lazy_init(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self._model_name
            )
            if torch.cuda.is_available():
                self._device = "cuda"
                self._model = self._model.to("cuda")
        except ImportError:
            logger.warning("nli_transformers_not_available")
            self._model = False
        except Exception:
            logger.exception("nli_model_load_failed")
            self._model = False

    def is_available(self) -> bool:
        self._lazy_init()
        return self._model is not None

    async def score(self, claim: str, context_chunks: list[str]) -> list[dict]:
        self._lazy_init()
        if self._model is None:
            return []

        if not context_chunks:
            return []

        try:
            import torch

            pairs = [(claim, chunk) for chunk in context_chunks]
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

            results = []
            for i, chunk in enumerate(context_chunks):
                prob = probs[i]
                results.append(
                    {
                        "chunk_index": i,
                        "entailment": round(prob[0].item(), 4),
                        "neutral": round(prob[1].item(), 4),
                        "contradiction": round(prob[2].item(), 4),
                    }
                )
            return results
        except Exception:
            logger.exception("nli_scoring_failed")
            return []

    async def ground(
        self, claim: str, context_chunks: list[str], threshold: float | None = None
    ) -> tuple[str, float, list[dict]]:
        scores = await self.score(claim, context_chunks)
        if not scores:
            return "unclear", 0.0, []

        threshold = threshold or self._threshold
        max_contradiction = max(s["contradiction"] for s in scores)
        max_entailment = max(s["entailment"] for s in scores)

        if max_contradiction > threshold and max_contradiction > max_entailment:
            return "unsupported", max_contradiction, scores

        if max_entailment > threshold:
            return "supported", max_entailment, scores

        return "unclear", max_entailment, scores
