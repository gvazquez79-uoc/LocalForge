"""
Model management endpoints — CRUD for stored models.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import refresh_models_from_db
from backend.db.models_store import (
    create_model,
    delete_model,
    get_model_by_id,
    list_models_masked,
    set_default_model,
    update_model,
)

router = APIRouter(tags=["models"])


class ModelCreate(BaseModel):
    name: str
    display_name: str
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    is_default: bool = False


class ModelUpdate(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    provider: Optional[str] = None
    api_key: Optional[str] = None   # None = keep; "" = clear
    base_url: Optional[str] = None
    is_default: Optional[bool] = None


@router.get("/models")
async def api_list_models():
    return await list_models_masked()


@router.post("/models", status_code=201)
async def api_create_model(body: ModelCreate):
    model = await create_model(
        name=body.name,
        display_name=body.display_name,
        provider=body.provider,
        api_key=body.api_key,
        base_url=body.base_url,
        is_default=body.is_default,
    )
    await refresh_models_from_db()
    return model


@router.put("/models/{model_id}")
async def api_update_model(model_id: str, body: ModelUpdate):
    model = await update_model(
        model_id=model_id,
        name=body.name,
        display_name=body.display_name,
        provider=body.provider,
        api_key=body.api_key,
        base_url=body.base_url,
        is_default=body.is_default,
    )
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    await refresh_models_from_db()
    return model


@router.delete("/models/{model_id}")
async def api_delete_model(model_id: str):
    ok = await delete_model(model_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Model not found")
    await refresh_models_from_db()
    return {"ok": True}


@router.patch("/models/{model_id}/default")
async def api_set_default(model_id: str):
    model = await set_default_model(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    await refresh_models_from_db()
    return model
