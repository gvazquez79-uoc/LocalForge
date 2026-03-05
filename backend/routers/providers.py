"""
Provider management endpoints — CRUD for AI providers.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.db.providers_store import (
    create_provider,
    delete_provider,
    list_providers,
    update_provider,
)

router = APIRouter(tags=["providers"])


class ProviderCreate(BaseModel):
    name: str
    display_name: str
    base_url: str = ""
    api_key_env: str = ""


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None


@router.get("/providers")
async def api_list_providers():
    return await list_providers()


@router.post("/providers", status_code=201)
async def api_create_provider(body: ProviderCreate):
    from backend.config import refresh_providers_cache
    try:
        provider = await create_provider(
            name=body.name,
            display_name=body.display_name,
            base_url=body.base_url,
            api_key_env=body.api_key_env,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await refresh_providers_cache()
    return provider


@router.put("/providers/{provider_id}")
async def api_update_provider(provider_id: str, body: ProviderUpdate):
    from backend.config import refresh_providers_cache
    provider = await update_provider(
        provider_id=provider_id,
        name=body.name,
        display_name=body.display_name,
        base_url=body.base_url,
        api_key_env=body.api_key_env,
    )
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    await refresh_providers_cache()
    return provider


@router.delete("/providers/{provider_id}")
async def api_delete_provider(provider_id: str):
    from backend.config import refresh_providers_cache
    ok = await delete_provider(provider_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Provider not found")
    await refresh_providers_cache()
    return {"ok": True}
