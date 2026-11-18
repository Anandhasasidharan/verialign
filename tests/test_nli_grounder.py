import sys
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from verialign.verification.nli_grounder import NLIGrounder
from verialign.verification.source_grounder import SourceGrounder


class TestNLIGrounder:
    def test_init(self) -> None:
        grounder = NLIGrounder()
        assert grounder is not None
        assert grounder._model_name == "cross-encoder/nli-deberta-v3-base"

    def test_is_available_returns_bool(self) -> None:
        grounder = NLIGrounder()
        result = grounder.is_available()
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_score_empty_context_returns_empty(self) -> None:
        grounder = NLIGrounder()
        result = await grounder.score("Paris is in France", [])
        assert result == []

    @pytest.mark.asyncio
    async def test_ground_no_context(self) -> None:
        grounder = NLIGrounder()
        status, score, _details = await grounder.ground("test claim", [])
        assert status == "unclear"
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_ground_unavailable_fallback(self) -> None:
        grounder = NLIGrounder()
        grounder._model = False
        status, score, _details = await grounder.ground("test", ["some context"])
        assert status == "unclear"
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_batch_decodes_checkpoint_label_order(self, monkeypatch) -> None:
        class Probability(float):
            def item(self):
                return float(self)

        class Tokens(dict):
            def to(self, device):
                return self

        rows = [
            [Probability(value) for value in row]
            for row in ((0.05, 0.9, 0.05), (0.1, 0.8, 0.1), (0.95, 0.04, 0.01), (0.8, 0.1, 0.1))
        ]
        model = Mock(return_value=SimpleNamespace(logits=rows))
        model.config.id2label = {0: "contradiction", 1: "entailment", 2: "neutral"}
        monkeypatch.setitem(
            sys.modules,
            "torch",
            SimpleNamespace(
                no_grad=nullcontext,
                nn=SimpleNamespace(functional=SimpleNamespace(softmax=lambda logits, dim: logits)),
            ),
        )
        grounder = NLIGrounder()
        grounder._model = model
        grounder._tokenizer = Mock(return_value=Tokens())
        scores = await grounder.score_batch(["first", "second"], ["source A", "source B"])

        model.assert_called_once()
        assert grounder._tokenizer.call_args.args[0] == [
            ("source A", "first"),
            ("source B", "first"),
            ("source A", "second"),
            ("source B", "second"),
        ]
        assert grounder.interpret(scores[0])[:2] == ("supported", 0.9)
        assert grounder.interpret(scores[1])[:2] == ("unsupported", 0.95)


class TestSourceGrounderNLI:
    def test_source_grounder_creates_nli(self) -> None:
        grounder = SourceGrounder(use_nli=True)
        assert grounder._nli_grounder is not None

    def test_source_grounder_disabled_nli(self) -> None:
        grounder = SourceGrounder(use_nli=False)
        assert grounder._nli_grounder is None

    @pytest.mark.asyncio
    async def test_ground_with_nli_fallback_when_not_available(self) -> None:
        grounder = SourceGrounder(use_nli=True)
        status, score, _sources = await grounder.ground(
            "test claim",
            [("ctx-1", "some context text")],
        )
        assert status in ("supported", "unsupported", "unclear")
        assert isinstance(score, float)
