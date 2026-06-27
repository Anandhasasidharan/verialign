"""Admin API for runtime config management."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from verialign.proxy.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])
admin_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


def verify_admin(api_key: str = Depends(admin_key_header)) -> None:
    settings = get_settings()
    if settings.admin_api_key and api_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")


class ConfigUpdate(BaseModel):
    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None
    redact_traces: bool | None = None
    require_proxy_auth: bool | None = None


@router.get("/config", dependencies=[Depends(verify_admin)])
async def get_config() -> dict:
    settings = get_settings()
    s = settings.model_dump()
    for key in ("upstream_api_key", "proxy_api_key", "admin_api_key"):
        if s.get(key):
            s[key] = "***"
    return s


@router.get("/health", dependencies=[Depends(verify_admin)])
async def admin_health() -> dict:
    return {"status": "ok", "version": "0.1.0"}


@router.get("/providers", dependencies=[Depends(verify_admin)])
async def list_providers() -> dict:
    from verialign.proxy.routing.provider_router import ProviderRouter

    settings = get_settings()
    router_inst = ProviderRouter(settings)
    return {"providers": router_inst.get_configured_providers()}


@router.get("/traces", dependencies=[Depends(verify_admin)])
async def admin_traces(limit: int = 100) -> dict:
    from verialign.proxy.main import _get_store

    store = _get_store()
    if hasattr(store, "list_recent"):
        from verialign.storage.async_trace_store import AsyncTraceStore

        if isinstance(store, AsyncTraceStore):
            return {"traces": await store.list_recent(limit)}
        return {"traces": store.list_recent(limit)}
    return {"traces": []}
