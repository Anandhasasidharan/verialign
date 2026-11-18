import pytest

from verialign.verification.engine import VerificationEngine
from verialign.verification.overlay import Overlay
from verialign.verification.source_grounder import SourceGrounder


@pytest.mark.asyncio
async def test_supported_claim() -> None:
    status, confidence, sources = await SourceGrounder().ground(
        "VeriAlign is a verification support proxy for LLM outputs.",
        [
            {
                "id": "paper",
                "text": "VeriAlign is a verification support proxy for LLM outputs.",
            },
        ],
    )

    assert status == "supported"
    assert confidence >= 0.55
    assert sources[0].source_id == "paper"


@pytest.mark.asyncio
async def test_unsupported_claim() -> None:
    status, _confidence, _sources = await SourceGrounder().ground(
        "VeriAlign requires a GPU cluster.",
        [{"id": "plan", "text": "VeriAlign runs as a Python FastAPI service."}],
    )

    assert status == "unsupported"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claim", "source", "refuted"),
    [
        ("The reactor is operational.", "The reactor is not operational.", True),
        ("Jane Smith was born in 1998.", "Jane Smith was born in 2001.", True),
        ("The reactor is operational.", "The plant is not operational.", False),
        ("The reactor is operational.", "The reactor is not only operational.", False),
        ("The book was published in 1998.", "The book was published in 2001.", False),
        ("The book was published in 1998.", "The book was reprinted in 2001.", False),
    ],
)
async def test_keyword_refutation_requires_same_proposition(claim, source, refuted) -> None:
    engine = VerificationEngine(use_nli=False)
    engine.source_grounder.use_semantic = False
    result = Overlay.from_result(await engine.verify(claim, [{"id": "evidence", "text": source}]))
    assert (result.claims[0].label == "contradicted") == refuted
    assert result.claims[0].evidence[0].source_id == "evidence"
    claim_payload = result.model_dump()["claims"][0]
    assert claim_payload["sources"] == claim_payload["evidence"]
    assert claim_payload["evidence"][0].get("refutes", False) is refuted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("support", "refute", "label", "sources"),
    [
        (0.1, 0.95, "contradicted", ["refutation"]),
        (0.9, 0.95, "unverifiable", ["overlapping", "refutation"]),
        (0.1, 0.1, "unverifiable", ["overlapping"]),
    ],
)
async def test_nli_citations_follow_evidence_relation(monkeypatch, support, refute, label, sources):
    engine = VerificationEngine(use_nli=True)

    async def scores(claims, context):
        return [
            [
                {"chunk_index": 0, "entailment": support, "contradiction": 0.01},
                {"chunk_index": 1, "entailment": 0.01, "contradiction": refute},
            ]
            for _ in claims
        ]

    monkeypatch.setattr(engine.source_grounder, "batch_nli", scores)
    claim = "The reactor is operational."
    evidence = [
        {"id": "overlapping", "text": claim},
        {"id": "refutation", "text": "The equipment is shut down."},
    ]
    evaluated = Overlay.from_result(await engine.verify(claim, evidence)).claims[0]
    assert evaluated.label == label
    assert [source.source_id for source in evaluated.evidence] == sources
