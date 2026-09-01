import pytest
from verialign.verification.source_grounder import SourceGrounder


@pytest.mark.asyncio
async def test_rescoring_downgrades_warrant_gap():
    # Without rescoring, NLI would mark supported if entailment high; but we simulate
    # warrant gap via keyword overlap low. Since NLI not available in test env, we test warrant_score logic directly.
    grounder = SourceGrounder(use_semantic=False, use_nli=False, use_rescoring=True)
    # Evidence does not contain claim terms -> warrant score low
    context = [("doc-1", "The system uses JWT for auth.")]
    warrant = grounder._warrant_score("The refund was processed for $50", context)
    assert warrant < 0.35


@pytest.mark.asyncio
async def test_rescoring_preserves_good_warrant():
    grounder = SourceGrounder(use_semantic=False, use_nli=False, use_rescoring=True)
    context = [("doc-1", "The refund was processed for $50 and status is processed.")]
    warrant = grounder._warrant_score("The refund was processed for $50", context)
    assert warrant > 0.5


@pytest.mark.asyncio
async def test_rescoring_flag_exists():
    g = SourceGrounder(use_rescoring=True)
    assert g.use_rescoring is True
    g2 = SourceGrounder(use_rescoring=False)
    assert g2.use_rescoring is False
