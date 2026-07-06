"""Admin API for runtime config management."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from verialign.proxy.config import get_settings
from verialign.proxy.routing.cost_model import list_model_prices, update_model_pricing

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])
admin_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


def verify_admin(api_key: str = Depends(admin_key_header)) -> None:
    settings = get_settings()
    if not settings.admin_api_key:
        raise HTTPException(
            status_code=503,
            detail="Admin API is disabled: set VERIALIGN_ADMIN_API_KEY to enable it.",
        )
    if api_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")


class PricingUpdate(BaseModel):
    model: str
    input_price: float
    output_price: float


@router.put("/pricing", dependencies=[Depends(verify_admin)])
async def update_pricing(update: PricingUpdate) -> dict:
    update_model_pricing(update.model, update.input_price, update.output_price)
    logger.info("admin_pricing_updated", extra={"model": update.model})
    return {
        "status": "ok",
        "model": update.model,
        "pricing": {"input": update.input_price, "output": update.output_price},
    }


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


@router.get("/pricing", dependencies=[Depends(verify_admin)])
async def admin_pricing() -> dict:
    return {"models": list_model_prices()}


@router.get("/circuits", dependencies=[Depends(verify_admin)])
async def admin_circuits() -> dict:
    from verialign.proxy.routing.provider_router import ProviderRouter

    settings = get_settings()
    router_inst = ProviderRouter(settings)
    return {"circuits": router_inst.get_circuit_statuses()}
