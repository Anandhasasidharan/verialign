import json
import logging
from functools import lru_cache
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Query, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.security import APIKeyHeader

from verialign.proxy.config import get_settings
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
from verialign.storage.store_factory import create_trace_store
from verialign.storage.async_trace_store import AsyncTraceStore
from verialign.storage.trace_store import TraceStore
from verialign.verification.engine import VerificationEngine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    limiter = RateLimiter(
        RateLimitConfig(
            requests_per_minute=settings.rate_limit_requests_per_minute,
            tokens_per_minute=settings.rate_limit_tokens_per_minute,
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings_at_startup.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
                )
                verification = await verifier.verify(
                    full_text, payload.get("metadata", {}).get("context", [])
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


@lru_cache
def _get_router() -> ProviderRouter:
    return ProviderRouter(get_settings())


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
    rate_limiter.check_limit(client_ip)

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
    verifier = VerificationEngine(
        llm_client=llm_client,
        web_api_key=settings.web_search_api_key,
        web_provider=settings.web_search_provider,
    )
    response_handler = ResponseHandler(verifier, structured_output=structured)
    augmented = await response_handler.augment(upstream_response, payload)

    store = _get_store()
    await _write_trace(store, payload, augmented.data, augmented.verification)

    response_headers = {}
    rate_limit_headers = rate_limiter.get_headers(client_ip)
    response_headers.update(rate_limit_headers)
    response_headers["X-Provider"] = provider_name

    logger.info(
        "chat_completion",
        extra={
            "provider": provider_name,
            "model": validated.model,
            "claims": augmented.verification.summary["total_claims"],
        },
    )

    return JSONResponse(content=augmented.data, headers=response_headers)


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
