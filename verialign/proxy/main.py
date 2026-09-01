import json
import logging
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import AsyncIterator

from fastapi import FastAPI, Query, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.security import APIKeyHeader

from verialign.proxy.config import get_settings
from verialign.proxy.routing.cost_model import calculate_cost
from verialign.proxy.routing.provider_router import (
    ProviderRouter,
    ProviderError,
    close_http_client,
)
from verialign.proxy.routing.fallback import with_fallback
from verialign.proxy.middleware.rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    get_rate_limiter,
)
from verialign.proxy.middleware.request_handler import (
    validate_request,
    build_upstream_payload,
)
from verialign.proxy.middleware.response_handler import ResponseHandler
from verialign.proxy.otel_genai import emit_genai_span
from verialign.proxy.middleware.logging_middleware import (
    configure_logging,
    CorrelationIdMiddleware,
    get_request_id,
)
from verialign.proxy.middleware.body_size_limit import RequestBodySizeLimitMiddleware
from verialign.proxy.middleware.metrics_middleware import (
    MetricsMiddleware,
    metrics_response,
)
from verialign.proxy.middleware.request_timeout import RequestTimeoutMiddleware
from verialign.proxy.middleware.safety_middleware import SafetyMiddleware
from verialign.proxy.admin import router as admin_router
from verialign.storage.store_factory import create_trace_store
from verialign.storage.async_trace_store import AsyncTraceStore
from verialign.storage.trace_store import TraceStore
from verialign.verification.engine import VerificationEngine
from verialign.verification.valkey_cache import ValkeyCache
from verialign.verification.alerting import send_alert

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

    if settings.enable_otel:
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            provider = TracerProvider(
                resource=Resource.create({"service.name": "verialign"})
            )
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            trace.set_tracer_provider(provider)
            FastAPIInstrumentor.instrument_app(app)
            logger.info("otel_initialized")
        except Exception:
            logger.exception("otel_init_failed")
    limiter = RateLimiter(
        RateLimitConfig(
            requests_per_minute=settings.rate_limit_requests_per_minute,
            tokens_per_minute=settings.rate_limit_tokens_per_minute,
            key_requests_per_minute=settings.rate_limit_key_rpm,
            key_tokens_per_minute=settings.rate_limit_key_tpm,
        )
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
                    "Check VERIALIGN_UPSTREAM_BASE_URL and VERIALIGN_UPSTREAM_API_KEY."
                },
            )

    logger.info("server_started", extra={"settings": self_sanitize(settings)})

    store = create_trace_store(
        settings.database_url, settings.db_path, settings.redact_traces
    )
    if isinstance(store, AsyncTraceStore):
        await store.initialize()
    app.state.trace_store = store

    if settings.valkey_url:
        app.state.cache = ValkeyCache()
        try:
            from valkey import Valkey

            valkey_client = Valkey.from_url(settings.valkey_url)
            limiter.set_valkey(valkey_client)
        except Exception:
            logger.exception("valkey_rate_limiter_init_failed")
    else:
        app.state.cache = None

    yield

    if isinstance(app.state.trace_store, AsyncTraceStore):
        await app.state.trace_store.close()
    await close_http_client()
    logger.info("server_stopped")


def self_sanitize(settings) -> dict:
    s = settings.model_dump()
    for key in ("upstream_api_key", "proxy_api_key"):
        if s.get(key):
            s[key] = "***"
    return s


def _build_llm_client(router: ProviderRouter):
    providers = router.get_configured_providers()
    if providers:
        provider = providers[0]

        async def llm_client(payload: dict) -> dict:
            resp = await provider.chat_completions(payload)
            return resp.data

        return llm_client
    return None


app = FastAPI(title="VeriAlign", version="0.1.0", lifespan=lifespan)

settings_at_startup = get_settings()

app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    RequestBodySizeLimitMiddleware, max_size=settings_at_startup.max_request_body_size
)
app.add_middleware(
    RequestTimeoutMiddleware, timeout_seconds=settings_at_startup.proxy_timeout_seconds
)
app.add_middleware(MetricsMiddleware)
origins = settings_at_startup.cors_allowed_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials="*" not in origins if origins else False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    SafetyMiddleware,
    pii_redact=settings_at_startup.safety_pii_redact_enabled,
    jailbreak_block=settings_at_startup.safety_jailbreak_enabled,
    toxicity_block=settings_at_startup.safety_toxicity_enabled,
)
app.include_router(admin_router)

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


def verify_proxy_auth(api_key: str = Depends(api_key_header)) -> None:
    settings = get_settings()
    if settings.require_proxy_auth and settings.proxy_api_key:
        provided = api_key.replace("Bearer ", "") if api_key else ""
        if provided != settings.proxy_api_key:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "message": "Invalid or missing API key",
                        "type": "auth_error",
                        "status_code": 401,
                    }
                },
            )


@app.get("/health")
async def health() -> dict:
    db_ok = False
    try:
        store: AsyncTraceStore | TraceStore = getattr(app.state, "trace_store", None)
        if store is None:
            settings = get_settings()
            store = create_trace_store(
                settings.database_url, settings.db_path, settings.redact_traces
            )
        await _ensure_list_recent(store)
        db_ok = True
    except Exception:
        logger.exception("health_check_db_failed")

    settings = get_settings()
    upstream_ok = False
    router = ProviderRouter(settings)
    try:
        upstream_ok = len(router.get_configured_providers()) > 0
    except Exception:
        logger.exception("health_check_upstream_failed")

    return {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "upstream_configured": upstream_ok,
    }


async def _ensure_list_recent(store):
    if isinstance(store, AsyncTraceStore):
        await store.list_recent(1)
    else:
        store.list_recent(1)


def _get_store():
    store = getattr(app.state, "trace_store", None)
    if store is None:
        settings = get_settings()
        store = create_trace_store(
            settings.database_url, settings.db_path, settings.redact_traces
        )
    return store


async def _write_trace(store, request_payload, response_payload, verification):
    if isinstance(store, AsyncTraceStore):
        await store.write_trace(request_payload, response_payload, verification)
    else:
        store.write_trace(request_payload, response_payload, verification)


@app.get("/metrics")
async def metrics() -> Response:
    return metrics_response()


@app.get("/traces")
async def traces(
    limit: int = Query(default=25, ge=1, le=100), _: None = Depends(verify_proxy_auth)
) -> dict:
    store = _get_store()
    if isinstance(store, AsyncTraceStore):
        return {"traces": await store.list_recent(limit)}
    return {"traces": store.list_recent(limit)}


async def _handle_streaming(
    validated,
    payload: dict,
    router: ProviderRouter,
    rate_limiter,
    client_ip: str,
    settings,
):
    rid = get_request_id()

    async def event_stream() -> AsyncIterator[str]:
        full_content_parts: list[str] = []
        first = True

        async for chunk in router.chat_completions_stream(payload):
            if isinstance(chunk, dict):
                chunk["usage"] = None
                line = f"data: {json.dumps(chunk)}\n\n"
                if first:
                    yield line
                    first = False
                else:
                    yield line

                choices = chunk.get("choices", [])
                for choice in choices:
                    delta = choice.get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        full_content_parts.append(content)

        full_text = "".join(full_content_parts)
        if full_text.strip():
            try:
                llm_client = _build_llm_client(router)
                verifier = VerificationEngine(
                    llm_client=llm_client,
                    web_api_key=settings.web_search_api_key,
                    web_provider=settings.web_search_provider,
                    cache=getattr(app.state, "cache", None),
                )
                verification = await verifier.verify(
                    full_text, payload.get("metadata", {}).get("context", [])
                )
                trust_components = {
                    "supported": verification.summary.get("supported", 0),
                    "unsupported": verification.summary.get("unsupported", 0),
                    "contradictions": verification.summary.get(
                        "contradictions_found", 0
                    ),
                    "checklist": verification.summary.get("checklist_items", 0),
                }
                emit_genai_span(
                    payload,
                    {"choices": [{"message": {"content": full_text}}]},
                    router.get_configured_providers()[0]
                    .__class__.__name__.replace("Provider", "")
                    .lower()
                    if router.get_configured_providers()
                    else None,
                    trust_score=verification.trust_score,
                    trust_components=trust_components,
                )
                store = _get_store()
                await _write_trace(
                    store,
                    payload,
                    {"choices": [{"message": {"content": full_text}}]},
                    verification,
                )
                logger.info(
                    "chat_completion_stream",
                    extra={
                        "request_id": rid,
                        "model": validated.model,
                        "claims": verification.summary["total_claims"],
                    },
                )
            except Exception:
                logger.exception("stream_verification_failed")

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, _: None = Depends(verify_proxy_auth)):
    settings = get_settings()

    payload = await request.json()

    try:
        validated = validate_request(payload)
    except ValueError as exc:
        logger.warning("validation_failed", extra={"error": str(exc)})
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "message": str(exc),
                    "type": "validation_error",
                    "status_code": 400,
                }
            },
        )

    upstream_payload = build_upstream_payload(validated)
    router = ProviderRouter(settings)
    rate_limiter = get_rate_limiter()
    client_ip = request.client.host if request.client else "unknown"
    auth_header = request.headers.get("authorization", "")
    api_key = (
        auth_header.replace("Bearer ", "")
        if auth_header.startswith("Bearer ")
        else None
    )
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
                }
            },
            headers=rate_limit_headers,
        )

    if validated.stream:
        return await _handle_streaming(
            validated, upstream_payload, router, rate_limiter, client_ip, settings
        )

    fallback_response = await with_fallback(
        router, upstream_payload, preferred_provider=None
    )

    provider_name = fallback_response.provider_name
    upstream_response = fallback_response.data

    llm_client = _build_llm_client(router)
    structured = payload.get("response_format", {}).get("type") == "json_object"
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
            float(header_threshold)
            if header_threshold is not None
            else settings.block_threshold
        )
    except ValueError:
        threshold = settings.block_threshold
    verifier = VerificationEngine(
        llm_client=llm_client,
        web_api_key=settings.web_search_api_key,
        web_provider=settings.web_search_provider,
        cache=getattr(app.state, "cache", None),
    )
    response_handler = ResponseHandler(
        verifier, structured_output=structured, policy=policy, block_threshold=threshold
    )
    augmented = await response_handler.augment(upstream_response, payload)

    import asyncio

    asyncio.create_task(
        send_alert(
            settings.alert_webhook_url,
            settings.alert_slack_webhook_url,
            upstream_response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", ""),
            augmented.verification,
        )
    )

    usage = upstream_response.get("usage", {})
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

    trust_components = {
        "supported": augmented.verification.summary.get("supported", 0),
        "unsupported": augmented.verification.summary.get("unsupported", 0),
        "contradictions": augmented.verification.summary.get("contradictions_found", 0),
        "checklist": augmented.verification.summary.get("checklist_items", 0),
    }
    emit_genai_span(
        payload,
        upstream_response,
        provider_name,
        trust_score=augmented.verification.trust_score,
        trust_components=trust_components,
    )

    store = _get_store()
    await _write_trace(store, payload, augmented.data, augmented.verification)

    response_headers = dict(rate_limit_headers)
    response_headers["X-Provider"] = provider_name
    # Merge policy-driven headers (warn/block)
    response_headers.update(augmented.headers)

    logger.info(
        "chat_completion",
        extra={
            "provider": provider_name,
            "model": validated.model,
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
async def verify_text(request: Request, _: None = Depends(verify_proxy_auth)):
    settings = get_settings()
    payload = await request.json()
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
                }
            },
        )

    try:
        llm_client = _build_llm_client(ProviderRouter(settings))
        verifier = VerificationEngine(
            llm_client=llm_client,
            web_api_key=settings.web_search_api_key,
            web_provider=settings.web_search_provider,
            cache=getattr(app.state, "cache", None),
        )
        result = await verifier.verify(text, context)
        return JSONResponse(content={"verification": result.to_dict()})
    except Exception:
        logger.exception("verify_failed")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": "Verification failed",
                    "type": "internal_error",
                    "status_code": 500,
                }
            },
        )


@app.exception_handler(ProviderError)
async def provider_error_handler(request: Request, exc: ProviderError) -> JSONResponse:
    logger.error(
        "upstream_error",
        extra={
            "provider": exc.provider,
            "status_code": exc.status_code,
            "detail": str(exc),
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
            }
        },
    )
