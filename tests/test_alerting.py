from unittest.mock import patch

import pytest

from verialign.verification.alerting import send_alert
from verialign.verification.models import (
    Contradiction,
    VerificationResult,
    VerifiedClaim,
)


def _make_result(unsupported: int = 0, contradictions: int = 0) -> VerificationResult:
    claims = [
        VerifiedClaim(
            text=f"claim {i}",
            status="unsupported" if i < unsupported else "supported",
            confidence=0.9,
            sources=[],
            claim_id=f"c-{i}",
        )
        for i in range(max(unsupported, 1))
    ]
    return VerificationResult(
        claims=claims,
        contradictions=[
            Contradiction(claim_a="a", claim_b="b", type="negation", confidence=0.9),
        ]
        * contradictions,
        checklist=[],
    )


@pytest.mark.asyncio
async def test_no_alert_when_no_urls() -> None:
    result = _make_result(unsupported=2)
    await send_alert(None, None, "test", result)  # should not raise


@pytest.mark.asyncio
async def test_no_alert_when_all_supported() -> None:
    result = _make_result(unsupported=0, contradictions=0)
    with patch("httpx.AsyncClient") as mock:
        await send_alert("http://hook.example.com", None, "test", result)
        mock.assert_not_called()


@pytest.mark.asyncio
async def test_alert_fires_on_unsupported() -> None:
    result = _make_result(unsupported=1)
    with patch("httpx.AsyncClient") as mock:
        client_instance = mock.return_value.__aenter__.return_value
        await send_alert("http://hook.example.com", None, "test text", result)
        assert client_instance.post.called


@pytest.mark.asyncio
async def test_alert_slack_format() -> None:
    result = _make_result(unsupported=1)
    with patch("httpx.AsyncClient") as mock:
        client_instance = mock.return_value.__aenter__.return_value
        await send_alert(None, "https://hooks.slack.com/abc", "test text", result)
        call_kwargs = client_instance.post.call_args[1]
        assert call_kwargs["json"]["text"].startswith("VeriAlign Alert")
