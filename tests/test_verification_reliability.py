import asyncio
import threading
from collections import Counter
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import State

from verialign.proxy import main as proxy
from verialign.proxy.config import Settings
from verialign.proxy.middleware import rate_limiter
from verialign.proxy.middleware.request_timeout import RequestTimeoutMiddleware
from verialign.verification.claim_extractor import ClaimExtractor
from verialign.verification.engine import VerificationEngine
from verialign.verification.models import SourceMatch, VerificationResult, VerifiedClaim
from verialign.verification.nli_grounder import NLIGrounder
from verialign.verification.overlay import Overlay
from verialign.verification.valkey_cache import ValkeyCache
from verialign.verification.verification_cache import VerificationCache
from verialign.verification.workers import BoundedExecutor

CHAT = {"model": "demo", "messages": [{"role": "user", "content": "Summarize the project."}]}
TEXT = "Paris is in France. Berlin is in Germany. Rome is in Italy."


@pytest.fixture
def client(tmp_path, monkeypatch):
    for var in ("VERIALIGN_LOCAL_BASE_URL", "VERIALIGN_ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(
        _env_file=None,
        db_path=str(tmp_path / "traces.sqlite3"),
        upstream_base_url=None,
        upstream_api_key=None,
        proxy_api_key="reliability-key",
        require_proxy_auth=False,
        proxy_timeout_seconds=0.30,
        verification_max_ms=2000,
        use_nli=False,
    )
    monkeypatch.setattr(proxy, "get_settings", lambda: settings)
    monkeypatch.setattr(proxy.app, "state", State())
    monkeypatch.setattr(proxy.app, "middleware_stack", None)
    monkeypatch.setattr(rate_limiter, "_global_limiter", None)
    timeout_middleware = next(
        m for m in proxy.app.user_middleware if m.cls is RequestTimeoutMiddleware
    )
    monkeypatch.setitem(
        timeout_middleware.kwargs, "timeout_seconds", settings.proxy_timeout_seconds
    )
    with TestClient(proxy.app, headers={"Authorization": "Bearer reliability-key"}) as test_client:
        yield test_client


async def hang(*args, **kwargs):
    await asyncio.Event().wait()


@pytest.mark.parametrize(
    ("path", "payload"),
    [("/v1/chat/completions", CHAT), ("/v1/verify", {"text": "Paris is in France."})],
)
def test_outer_deadline_preserves_response_after_verification_begins(
    client, monkeypatch, path, payload
):
    monkeypatch.setattr(VerificationEngine, "verify", hang)
    response = client.post(path, json=payload, headers={"X-VeriAlign-Policy": "block"})
    assert response.status_code == 200
    body = response.json()
    assert Overlay.model_validate(body["verification"]).status == "unverifiable"
    assert body["verification"]["trust_score"] is None
    if path.endswith("completions"):
        assert body["choices"][0]["message"]["role"] == "assistant"


def test_outer_deadline_still_applies_to_upstream(client, monkeypatch):
    monkeypatch.setattr(proxy, "with_fallback", hang)
    assert client.post("/v1/chat/completions", json=CHAT).status_code == 408


def test_stream_verifier_failure_preserves_done_and_stores_status(client, monkeypatch):
    verifier = AsyncMock(side_effect=TimeoutError)
    monkeypatch.setattr(VerificationEngine, "verify", verifier)
    context = [{"id": "doc", "text": "Example source."}]
    response = client.post(
        "/v1/chat/completions", json={**CHAT, "stream": True, "metadata": {"context": context}}
    )
    assert response.status_code == 200
    assert response.text.rstrip().endswith("data: [DONE]")
    rows = client.get("/traces").json()["traces"]
    assert rows[0]["verification"]["incomplete"] is True
    assert verifier.await_args.args[1] == context


def test_readiness_reflects_database_and_supports_demo_mode(client, monkeypatch):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "upstream_configured": False}

    def broken_store():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(proxy, "_get_store", broken_store)
    assert client.get("/health").status_code == 200
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["database"] == "error"


@pytest.mark.parametrize("failure", ["exception", "claim_timeout", "request_timeout"])
async def test_partial_failure_keeps_completed_claims_and_never_caches_failure(
    monkeypatch, failure
):
    engine = VerificationEngine(
        use_nli=False,
        max_ms=200 if failure == "request_timeout" else 1500,
        claim_timeout_ms=100 if failure == "claim_timeout" else 1000,
    )

    async def ground(text, context):
        if text.startswith("Berlin"):
            if failure == "exception":
                raise RuntimeError("injected grounding failure")
            await hang()
        return "supported", 0.85, [SourceMatch("doc", 0.85, "evidence")]

    monkeypatch.setattr(engine.source_grounder, "ground", ground)
    result = await engine.verify(TEXT, [])
    overlay = Overlay.from_result(result)
    assert [claim.label for claim in overlay.claims] == ["verified", "unverifiable", "verified"]
    assert overlay.status == "unverifiable"
    assert overlay.trust_score is None
    assert engine._cache.size == 0


async def test_claim_limit_reports_skipped_work(monkeypatch):
    engine = VerificationEngine(use_nli=False, max_claims=1)
    ground = AsyncMock(return_value=("supported", 0.85, []))
    monkeypatch.setattr(engine.source_grounder, "ground", ground)
    result = await engine.verify(TEXT, [])
    assert ground.await_count == 1
    assert result.skipped_claims == 2
    assert Overlay.from_result(result).status == "unverifiable"


async def test_semaphore_bounds_concurrency_and_preserves_order(monkeypatch):
    engine = VerificationEngine(use_nli=False, concurrency=2)
    ready = asyncio.Event()
    release = asyncio.Event()
    started = []

    async def ground(text, context):
        started.append(text)
        if len(started) == 2:
            ready.set()
        await release.wait()
        return "supported", 0.8, []

    monkeypatch.setattr(engine.source_grounder, "ground", ground)
    task = asyncio.create_task(engine.verify(TEXT, []))
    try:
        await asyncio.wait_for(ready.wait(), timeout=1)
        await asyncio.sleep(0)
        assert len(started) == 2
    finally:
        release.set()
    result = await task
    assert [claim.claim_id for claim in result.claims] == ["claim-0", "claim-1", "claim-2"]
    assert len(started) == 3


async def test_nli_batches_on_a_worker_without_blocking_event_loop(monkeypatch):
    engine = VerificationEngine(use_nli=True)
    engine.source_grounder.use_semantic = False
    worker_ready = asyncio.Event()
    release_worker = threading.Event()
    loop = asyncio.get_running_loop()
    caller = threading.get_ident()
    batches = []

    def score(self, claims, chunks):
        batches.append((threading.get_ident(), claims, chunks))
        loop.call_soon_threadsafe(worker_ready.set)
        if not release_worker.wait(timeout=2):
            raise RuntimeError("event loop did not resume")
        return [
            [{"chunk_index": 0, "entailment": 0.9, "neutral": 0.05, "contradiction": 0.05}]
            for _ in claims
        ]

    monkeypatch.setattr(NLIGrounder, "_score_batch", score)
    task = asyncio.create_task(engine.verify(TEXT, [{"text": "All three cities exist."}]))
    try:
        await asyncio.wait_for(worker_ready.wait(), timeout=1)
        assert not task.done()
    finally:
        release_worker.set()
    result = await task
    assert len(batches) == 1
    assert batches[0][0] != caller
    assert len(batches[0][1]) == len(result.claims) == 3
    assert batches[0][2] == ["All three cities exist."]
    assert all(claim.status == "supported" for claim in result.claims)


async def test_cancelled_worker_keeps_its_slot_until_work_finishes():
    executor = BoundedExecutor("test-capacity", workers=1, capacity=1)
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def work():
        loop.call_soon_threadsafe(started.set)
        release.wait(timeout=2)

    task = asyncio.create_task(executor.run(work))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(TimeoutError):
            await executor.run(lambda: None)
    finally:
        release.set()


def test_proxy_cache_scopes_model_system_prompt_and_params(client, monkeypatch):
    calls = Counter()

    async def extract(self, text):
        calls["extract"] += 1
        return ["This is a test completion."]

    monkeypatch.setattr(ClaimExtractor, "extract", extract)
    proxy.app.state.cache = VerificationCache()
    payload = {**CHAT, "messages": [{"role": "system", "content": "Baseline."}, *CHAT["messages"]]}
    variations = [
        payload,
        payload,
        {**payload, "model": "different-model"},
        {**payload, "messages": [{"role": "system", "content": "Different."}, *CHAT["messages"]]},
        {**payload, "temperature": 0.7},
    ]
    for variant in variations:
        response = client.post("/v1/chat/completions", json=variant)
        assert response.status_code == 200
        assert response.json()["verification"]["status"] == "complete"
    assert calls["extract"] == 4


def test_valkey_round_trip_preserves_nested_evidence(monkeypatch):
    monkeypatch.delenv("VERIALIGN_VALKEY_URL", raising=False)
    cache = ValkeyCache()
    data = {}

    class FakeValkey:
        def setex(self, key, ttl, value):
            data[key] = value

        def get(self, key):
            return data.get(key)

    cache._client = FakeValkey()
    cache._enabled = True
    result = VerificationResult(
        [VerifiedClaim("Example.", "supported", 1, [SourceMatch("doc", 1, "excerpt")])],
        [],
        [],
        trust_score=0.8,
    )
    cache.set("Example.", {"request": "scope"}, result)
    assert cache.get("Example.", {"request": "scope"}) == result
    assert cache.get("Example.", {"request": "different scope"}) is None


async def test_cache_isolates_upstream_logprobs():
    engine = VerificationEngine(use_nli=False)
    engine.source_grounder.use_semantic = False
    text = "Paris is in France."

    def response(logprob):
        return {"choices": [{"logprobs": {"content": [{"logprob": logprob}]}}]}

    high = await engine.verify(text, [text], response_data=response(0.0))
    low = await engine.verify(text, [text], response_data=response(-4.0))
    assert high.claims[0].confidence > low.claims[0].confidence
    assert await engine.verify(text, [text], response_data=response(-4.0)) is low
