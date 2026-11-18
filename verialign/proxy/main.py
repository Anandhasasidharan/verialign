import asyncio
import hmac
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.security import APIKeyHeader

from verialign.proxy.admin import router as admin_router
from verialign.proxy.config import Settings, get_settings
from verialign.proxy.middleware.body_size_limit import RequestBodySizeLimitMiddleware
from verialign.proxy.middleware.logging_middleware import (
    CorrelationIdMiddleware,
    configure_logging,
    get_request_id,
)
from verialign.proxy.middleware.metrics_middleware import (
    MetricsMiddleware,
    metrics_response,
)
from verialign.proxy.middleware.rate_limiter import (
    RateLimitConfig,
    RateLimiter,
    get_rate_limiter,
)
from verialign.proxy.middleware.request_handler import (
    build_upstream_payload,
    validate_request,
)
from verialign.proxy.middleware.request_timeout import RequestTimeoutMiddleware, verification_window
from verialign.proxy.middleware.response_handler import ResponseHandler
from verialign.proxy.middleware.safety_middleware import SafetyMiddleware
from verialign.proxy.middleware.stream_redaction import ChatStreamRedactor
from verialign.proxy.otel_genai import emit_genai_span
from verialign.proxy.otel_metrics import Operation, create_telemetry
from verialign.proxy.routing.cost_model import calculate_cost
from verialign.proxy.routing.fallback import with_fallback
from verialign.proxy.routing.provider_router import (
    ProviderError,
    ProviderRouter,
    close_http_client,
)
from verialign.storage.async_trace_store import AsyncTraceStore
from verialign.storage.store_factory import create_trace_store
from verialign.verification.alerting import send_alert
from verialign.verification.engine import VerificationEngine
from verialign.verification.models import VerificationResult
from verialign.verification.overlay import Overlay, PolicyAction
from verialign.verification.valkey_cache import ValkeyCache
from verialign.verification.workers import verification_workers

if TYPE_CHECKING:
    from verialign.storage.trace_store import TraceStore

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()

    if settings.sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.1)
            logger.info("sentry_initialized")
        except Exception:
            logger.exception("sentry_init_failed")

    limiter = RateLimiter(
        RateLimitConfig(
            requests_per_minute=settings.rate_limit_requests_per_minute,
            tokens_per_minute=settings.rate_limit_tokens_per_minute,
            key_requests_per_minute=settings.rate_limit_key_rpm,
            key_tokens_per_minute=settings.rate_limit_key_tpm,
        ),
    )
    get_rate_limiter.__globals__["_global_limiter"] = limiter

    router = ProviderRouter(settings)
    if not router.get_configured_providers():
        has_upstream_key = bool(settings.upstream_api_key or settings.proxy_api_key)
        if has_upstream_key:
            logger.warning(
                "demo_mode_with_upstream_keys",
                extra={
                    "detail": "Upstream API keys are set but no provider is fully configured. "
                    "Check VERIALIGN_UPSTREAM_BASE_URL and VERIALIGN_UPSTREAM_API_KEY.",
                },
            )

    logger.info("server_started")

    store = create_trace_store(
        settings.database_url,
        settings.db_path,
        settings.redact_traces,
    )
    if isinstance(store, AsyncTraceStore):
        await store.initialize()
    app.state.trace_store = store

    if settings.valkey_url:
        app.state.cache = await asyncio.to_thread(ValkeyCache, url=settings.valkey_url)
        try:
            from valkey import Valkey

            valkey_client = Valkey.from_url(settings.valkey_url)
            limiter.set_valkey(valkey_client)
        except Exception:
            logger.exception("valkey_rate_limiter_init_failed")
    else:
        app.state.cache = None

    telemetry = instrumentor = None
    app.state.verification_telemetry = None
    if settings.enable_otel:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            telemetry = create_telemetry(
                settings.agentops_traces_endpoint, settings.agentops_api_key
            )
            app.state.verification_telemetry = telemetry
            FastAPIInstrumentor.instrument_app(
                app,
                tracer_provider=telemetry.tracer_provider,
                meter_provider=telemetry.meter_provider,
            )
            instrumentor = FastAPIInstrumentor
            logger.info("otel_initialized")
        except Exception:
            logger.warning("otel_init_failed")

    try:
        yield
    finally:
        app.state.verification_telemetry = None
        if instrumentor:
            instrumentor.uninstrument_app(app)
        if telemetry:
            await asyncio.to_thread(telemetry.shutdown)
        if isinstance(app.state.trace_store, AsyncTraceStore):
            await app.state.trace_store.close()
        await close_http_client()
        logger.info("server_stopped")


def _build_llm_client(router: ProviderRouter, model: str):
    if not router.get_configured_providers():
        return None

    async def llm_client(payload: dict) -> dict:
        resp = await router.chat_completions({**payload, "model": model})
        return resp.data

    return llm_client


def _create_verifier(
    router: ProviderRouter,
    settings: Settings,
    seconds: float,
    request_scope: object,
    request_model: str | None,
) -> VerificationEngine:
    extractor_model = settings.llm_extractor_model or request_model
    return VerificationEngine(
        llm_client=(
            _build_llm_client(router, extractor_model)
            if settings.use_llm_extractor and extractor_model
            else None
        ),
        web_api_key=settings.web_search_api_key,
        web_provider=settings.web_search_provider,
        cache=getattr(app.state, "cache", None),
        use_rescoring=settings.use_rescoring,
        use_nli=settings.use_nli,
        max_claims=settings.verification_max_claims,
        # Reserve a short window for returning completed claims before the hard boundary.
        max_ms=(seconds - min(0.010, seconds * 0.1)) * 1000,
        claim_timeout_ms=settings.verification_claim_timeout_ms,
        concurrency=settings.verification_concurrency,
        request_scope=request_scope,
        llm_extractor_model=extractor_model if settings.use_llm_extractor else None,
    )


app = FastAPI(title="VeriAlign", version="0.1.0", lifespan=lifespan)

settings_at_startup = get_settings()

app.add_middleware(
    SafetyMiddleware,
    pii_redact=settings_at_startup.safety_pii_redact_enabled,
    jailbreak_block=settings_at_startup.safety_jailbreak_enabled,
    toxicity_block=settings_at_startup.safety_toxicity_enabled,
    max_body_size=settings_at_startup.max_request_body_size,
)
app.add_middleware(
    RequestBodySizeLimitMiddleware,
    max_size=settings_at_startup.max_request_body_size,
)
app.add_middleware(
    RequestTimeoutMiddleware,
    timeout_seconds=settings_at_startup.proxy_timeout_seconds,
)
app.add_middleware(MetricsMiddleware)
app.add_middleware(CorrelationIdMiddleware)
origins = settings_at_startup.cors_allowed_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials="*" not in origins if origins else False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(admin_router)

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


def _bearer_key(authorization: str | None) -> str:
    scheme, _, key = (authorization or "").partition(" ")
    return key if scheme.lower() == "bearer" else ""


def _check_proxy_key(configured: str | None, authorization: str | None) -> None:
    if not configured:
        raise HTTPException(status_code=503, detail="Proxy API key is not configured")
    key = _bearer_key(authorization)
    if not hmac.compare_digest(key.encode(), configured.encode()):
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Invalid or missing API key",
                    "type": "auth_error",
                    "status_code": 401,
                },
            },
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_proxy_auth(api_key: str | None = Depends(api_key_header)) -> None:
    settings = get_settings()
    if (
        settings.proxy_api_key
        or settings.require_proxy_auth
        or settings.web_search_api_key
        or ProviderRouter(settings).get_configured_providers()
    ):
        _check_proxy_key(settings.proxy_api_key, api_key)


def verify_trace_auth(api_key: str | None = Depends(api_key_header)) -> None:
    _check_proxy_key(get_settings().proxy_api_key, api_key)


async def _read_json_object(request: Request) -> dict:
    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON object") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object")
    return payload


@app.get("/health")
async def health() -> dict:
    db_ok = False
    try:
        async with asyncio.timeout(1):
            store = await verification_workers.run(_get_store)
            await _ensure_list_recent(store)
        db_ok = True
    except Exception:
        logger.warning("health_check_db_failed")

    settings = get_settings()
    upstream_ok = False
    try:
        upstream_ok = len(ProviderRouter(settings).get_configured_providers()) > 0
    except Exception:
        logger.exception("health_check_upstream_failed")

    return {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "upstream_configured": upstream_ok,
    }


async def _ensure_list_recent(store) -> None:
    if isinstance(store, AsyncTraceStore):
        await store.list_recent(1)
    else:
        await verification_workers.run(store.list_recent, 1)


@app.get("/ready")
async def ready() -> JSONResponse:
    state = await health()
    settings = get_settings()
    if not settings.proxy_api_key and (
        settings.require_proxy_auth or settings.web_search_api_key or state["upstream_configured"]
    ):
        return JSONResponse(
            content={**state, "status": "degraded", "auth": "missing_proxy_key"},
            status_code=503,
        )
    return JSONResponse(content=state, status_code=200 if state["database"] == "ok" else 503)


def _get_store():
    store: AsyncTraceStore | TraceStore | None = getattr(app.state, "trace_store", None)
    if store is None:
        settings = get_settings()
        store = create_trace_store(
            settings.database_url,
            settings.db_path,
            settings.redact_traces,
        )
    return store


async def _write_trace(store, request_payload, response_payload, verification) -> None:
    if isinstance(store, AsyncTraceStore):
        await store.write_trace(request_payload, response_payload, verification)
    else:
        await verification_workers.run(
            store.write_trace, request_payload, response_payload, verification
        )


async def _save_trace(request_payload, response_payload, verification) -> None:
    try:
        async with asyncio.timeout(0.25):
            store = await verification_workers.run(_get_store)
            await _write_trace(store, request_payload, response_payload, verification)
    except Exception:
        logger.warning("chat_trace_write_failed")


def _record_verification(
    request_payload: dict,
    response_payload: dict,
    verification: VerificationResult,
    operation: Operation,
    policy_action: PolicyAction = "pass-through",
    provider: str | None = None,
) -> None:
    telemetry = getattr(app.state, "verification_telemetry", None)
    if telemetry is None or verification.incomplete or verification.trust_score is None:
        return
    try:
        score = verification.trust_score
        telemetry.record(score, operation, policy_action)
        summary = verification.summary
        emit_genai_span(
            request_payload,
            response_payload,
            provider,
            trust_score=score,
            trust_components={
                "supported": summary["supported"],
                "unsupported": summary["unsupported"],
                "contradictions": summary["contradictions_found"],
                "checklist": summary["checklist_items"],
            },
            operation=operation,
            tracer=telemetry.tracer,
        )
    except Exception:
        logger.warning("verification_telemetry_failed")


@app.get("/metrics")
async def metrics() -> Response:
    return metrics_response()


@app.get("/traces")
async def traces(
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    _: None = Depends(verify_trace_auth),
) -> dict:
    store = _get_store()
    if isinstance(store, AsyncTraceStore):
        return {"traces": await store.list_recent(limit)}
    return {"traces": store.list_recent(limit)}


async def _handle_streaming(
    payload: dict,
    request_payload: dict,
    router: ProviderRouter,
    settings: Settings,
):
    rid = get_request_id()

    async def event_stream() -> AsyncIterator[str]:
        full_content_parts: list[str] = []
        response_type = (request_payload.get("response_format") or {}).get("type")
        redactor = (
            ChatStreamRedactor(structured=response_type in {"json_object", "json_schema"})
            if settings.safety_pii_redact_enabled
            else None
        )
        async for chunk in router.chat_completions_stream(payload):
            if isinstance(chunk, dict):
                chunk["usage"] = None
                for output in redactor.feed(chunk) if redactor else (chunk,):
                    yield f"data: {json.dumps(output)}\n\n"
                choices = chunk.get("choices", [])
                for choice in choices:
                    delta = choice.get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        full_content_parts.append(content)

        if redactor:
            for output in redactor.flush():
                yield f"data: {json.dumps(output)}\n\n"

        full_text = "".join(full_content_parts)
        if full_text.strip():
            seconds = settings.verification_max_ms / 1000
            try:
                verifier = _create_verifier(
                    router,
                    settings,
                    seconds,
                    {"stream": {k: v for k, v in request_payload.items() if k != "metadata"}},
                    payload["model"],
                )
                async with asyncio.timeout(seconds):
                    verification = await verifier.verify(
                        full_text, (request_payload.get("metadata") or {}).get("context", [])
                    )
            except Exception:
                logger.warning("stream_verification_unavailable")
                verification = VerificationResult([], [], [], incomplete=True)
            response = {"choices": [{"message": {"content": full_text}}]}
            _record_verification(payload, response, verification, "chat_stream")
            logger.info(
                "chat_completion_stream",
                extra={"request_id": rid, "claims": verification.summary["total_claims"]},
            )
            await _save_trace(request_payload, response, verification)

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, _: Annotated[None, Depends(verify_proxy_auth)]):
    settings = get_settings()

    payload = await _read_json_object(request)

    try:
        validated = validate_request(payload)
    except ValueError as exc:
        logger.warning("validation_failed")
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "message": str(exc),
                    "type": "validation_error",
                    "status_code": 400,
                },
            },
        )

    upstream_payload = build_upstream_payload(validated)
    router = ProviderRouter(settings)
    rate_limiter = get_rate_limiter()
    client_ip = request.client.host if request.client else "unknown"
    api_key = _bearer_key(request.headers.get("authorization")) or None
    allowed, rate_info = rate_limiter.check_limit(client_ip, api_key=api_key)
    rate_limit_headers = rate_limiter.build_headers(rate_info, allowed)

    if not allowed:
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "message": "Rate limit exceeded",
                    "type": "rate_limit_error",
                    "status_code": 429,
                },
            },
            headers=rate_limit_headers,
        )

    if validated.stream:
        return await _handle_streaming(
            upstream_payload,
            payload,
            router,
            settings,
        )

    fallback_response = await with_fallback(
        router,
        upstream_payload,
        preferred_provider=None,
    )

    provider_name = fallback_response.provider_name
    upstream_response = fallback_response.data
    seconds = verification_window(request, settings.verification_max_ms)

    structured = (payload.get("response_format") or {}).get("type") == "json_object"
    # Per-request policy override via headers (enables per-route / per-API-key config)
    header_policy = request.headers.get("x-verialign-policy")
    header_threshold = request.headers.get("x-verialign-block-threshold")
    policy = (
        header_policy
        if header_policy in ("pass-through", "warn", "block")
        else settings.response_policy
    )
    try:
        threshold = (
            float(header_threshold) if header_threshold is not None else settings.block_threshold
        )
    except ValueError:
        threshold = settings.block_threshold
    try:
        verifier = _create_verifier(
            router,
            settings,
            seconds,
            {
                "request": {k: v for k, v in payload.items() if k != "metadata"},
                "provider": provider_name,
            },
            validated.model,
        )
        response_handler = ResponseHandler(
            verifier,
            structured_output=structured,
            policy=policy,
            block_threshold=threshold,
            timeout_seconds=seconds,
        )
        augmented = await response_handler.augment(upstream_response, payload)
    except Exception:
        logger.warning("chat_verification_unavailable")
        augmented = ResponseHandler.unavailable(upstream_response, structured)

    if settings.alert_webhook_url or settings.alert_slack_webhook_url:
        choices = upstream_response.get("choices") or [{}]
        message = choices[0].get("message") or {}
        asyncio.create_task(
            send_alert(
                settings.alert_webhook_url,
                settings.alert_slack_webhook_url,
                message.get("content", ""),
                augmented.verification,
            ),
        )

    usage = upstream_response.get("usage") or {}
    cost = calculate_cost(
        validated.model,
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
    )
    if cost is not None:
        augmented = replace(augmented)
        augmented.data["cost"] = cost
        with_cost = replace(augmented.verification, cost=cost)
        augmented = replace(augmented, verification=with_cost)

    overlay = augmented.data["data" if structured else "verification"]
    _record_verification(
        payload,
        upstream_response,
        augmented.verification,
        "chat",
        overlay["policy_action"],
        provider_name,
    )
    await _save_trace(payload, augmented.data, augmented.verification)

    response_headers = dict(rate_limit_headers)
    response_headers["X-Provider"] = provider_name
    # Merge policy-driven headers (warn/block)
    response_headers.update(augmented.headers)

    logger.info(
        "chat_completion",
        extra={
            "provider": provider_name,
            "claims": augmented.verification.summary["total_claims"],
            "cost": cost,
        },
    )

    return JSONResponse(
        content=augmented.data,
        headers=response_headers,
        status_code=augmented.status_code,
    )


@app.post("/v1/verify")
async def verify_text(request: Request, _: Annotated[None, Depends(verify_proxy_auth)]):
    settings = get_settings()
    payload = await _read_json_object(request)
    text = payload.get("text", "")
    context = payload.get("context", [])

    if not text or not isinstance(text, str):
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "message": "text is required",
                    "type": "validation_error",
                    "status_code": 400,
                },
            },
        )

    try:
        seconds = verification_window(request, settings.verification_max_ms)
        verifier = _create_verifier(
            ProviderRouter(settings),
            settings,
            seconds,
            {
                "verify": {
                    key: value for key, value in payload.items() if key not in {"text", "context"}
                }
            },
            payload["model"] if isinstance(payload.get("model"), str) else None,
        )
        async with asyncio.timeout(seconds):
            result = await verifier.verify(text, context)
        overlay_payload = Overlay.from_result(result).model_dump(mode="json")
        _record_verification(payload, {}, result, "verify")
    except Exception:
        logger.warning("direct_verification_unavailable")
        overlay_payload = Overlay.from_result(
            VerificationResult(claims=[], contradictions=[], checklist=[]),
            failed=True,
        ).model_dump(mode="json")
    return JSONResponse(content={"verification": overlay_payload})


@app.exception_handler(ProviderError)
async def provider_error_handler(request: Request, exc: ProviderError) -> JSONResponse:
    logger.error(
        "upstream_error",
        extra={
            "provider": exc.provider,
            "status_code": exc.status_code,
        },
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": str(exc),
                "type": "upstream_error",
                "provider": exc.provider,
                "status_code": exc.status_code,
            },
        },
    )
