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
    try:
        model = await create_model(
            name=body.name,
            display_name=body.display_name,
            provider=body.provider,
            api_key=body.api_key,
            base_url=body.base_url,
            is_default=body.is_default,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
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


@router.post("/models/{model_id}/test")
async def api_test_model(model_id: str):
    """Send a minimal request to verify the model is reachable and the API key works."""
    row = await get_model_by_id(model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Model not found")

    from backend.config import get_config
    from backend.models.registry import get_adapter

    cfg = get_config()
    try:
        adapter = get_adapter(row["name"], cfg)
        response = ""
        async for event in adapter.stream_chat(
            messages=[{"role": "user", "content": "Reply with just the word OK."}],
            tools=[],
            system="You are a test assistant. Reply with a single word: OK.",
        ):
            if event.type == "text_delta":
                response += event.data.get("text", "")
            elif event.type == "error":
                return {"ok": False, "error": event.data.get("message", "Unknown error")}
            elif event.type == "done":
                break
        return {"ok": True, "response": response.strip()[:200]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
