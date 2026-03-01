"""
Config API router.
GET  /config         — return current config (without secret keys)
GET  /config/models  — list available models (auto-discovers Ollama models)
PUT  /config         — update tools + agent settings
"""
from __future__ import annotations
from typing import Any, Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from backend.config import get_config, save_config, ToolsConfig, AgentConfig, TelegramConfig

router = APIRouter(prefix="/config", tags=["config"])


class UpdateConfigRequest(BaseModel):
    tools: Optional[dict[str, Any]] = None
    agent: Optional[dict[str, Any]] = None
    telegram: Optional[dict[str, Any]] = None
    default_model: Optional[str] = None


async def _discover_ollama_models(base_url: str) -> list[dict]:
    """Query Ollama's /api/tags to get installed models."""
    # base_url is like http://localhost:11434/v1 → strip /v1
    ollama_root = base_url.rstrip("/")
    if ollama_root.endswith("/v1"):
        ollama_root = ollama_root[:-3]

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{ollama_root}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = []
            for m in data.get("models", []):
                name = m.get("name", "")
                family = m.get("details", {}).get("family", "")
                size = m.get("details", {}).get("parameter_size", "")
                display = f"{name} ({size})" if size else name
                models.append({
                    "name": name,
                    "display_name": display,
                    "provider": "ollama",
                    "available": True,
                    "base_url": base_url,
                })
            return models
    except Exception:
        return []


@router.get("")
async def read_config():
    cfg = get_config()
    safe_models = []
    for m in cfg.models:
        safe_models.append({
            "name": m.name,
            "display_name": m.display_name,
            "provider": m.provider,
            "has_api_key": bool(cfg.get_model_api_key(m)),
            "base_url": m.base_url,
        })
    return {
        "version": cfg.version,
        "default_model": cfg.default_model,
        "models": safe_models,
        "tools": cfg.tools.model_dump(),
        "agent": cfg.agent.model_dump(),
        "telegram": {
            "enabled": cfg.telegram.enabled,
            "bot_token": "***" if cfg.telegram.bot_token else "",
            "allowed_user_ids": cfg.telegram.allowed_user_ids,
            "default_model": cfg.telegram.default_model,
        },
    }


@router.get("/models")
async def list_models():
    cfg = get_config()

    # Find Ollama base_url from first ollama model in config
    ollama_base_url = "http://localhost:11434/v1"
    for m in cfg.models:
        if m.provider == "ollama" and m.base_url:
            ollama_base_url = m.base_url
            break

    # Auto-discover Ollama models
    ollama_models = await _discover_ollama_models(ollama_base_url)
    ollama_names = {m["name"] for m in ollama_models}

    # Non-Ollama models from config (Claude, OpenAI, etc.)
    other_models = [
        {
            "name": m.name,
            "display_name": m.display_name,
            "provider": m.provider,
            "available": bool(cfg.get_model_api_key(m)),
            "base_url": m.base_url,
        }
        for m in cfg.models
        if m.provider != "ollama" and m.name not in ollama_names
    ]

    all_models = ollama_models + other_models

    # Determine which model to use as default
    # Priority: config default_model → first available ollama → first available
    default = cfg.default_model
    available_names = {m["name"] for m in all_models if m["available"]}
    if default not in available_names and available_names:
        default = next(m["name"] for m in all_models if m["available"])

    return {
        "models": all_models,
        "default_model": default,
    }


@router.put("")
async def update_config(body: UpdateConfigRequest):
    cfg = get_config()

    if body.tools is not None:
        current = cfg.tools.model_dump()
        for section, values in body.tools.items():
            if section in current and isinstance(values, dict):
                current[section].update(values)
            else:
                current[section] = values
        cfg.tools = ToolsConfig(**current)

    if body.agent is not None:
        current = cfg.agent.model_dump()
        current.update(body.agent)
        cfg.agent = AgentConfig(**current)

    if body.telegram is not None:
        current = cfg.telegram.model_dump()
        # Only update fields that are provided
        if "enabled" in body.telegram:
            current["enabled"] = body.telegram["enabled"]
        if "bot_token" in body.telegram and body.telegram["bot_token"] and body.telegram["bot_token"] != "***":
            current["bot_token"] = body.telegram["bot_token"]
        if "allowed_user_ids" in body.telegram:
            current["allowed_user_ids"] = body.telegram["allowed_user_ids"]
        if "default_model" in body.telegram:
            current["default_model"] = body.telegram["default_model"]
        cfg.telegram = TelegramConfig(**current)

    if body.default_model is not None:
        cfg.default_model = body.default_model

    save_config(cfg)
    return {"ok": True}


@router.post("/telegram/restart")
async def restart_telegram():
    """Stop and restart the Telegram bot with the current config (no backend restart needed)."""
    from backend.telegram.bot import stop_telegram_bot, start_telegram_bot
    await stop_telegram_bot()
    await start_telegram_bot()
    cfg = get_config()
    return {"ok": True, "running": cfg.telegram.enabled and bool(cfg.telegram.bot_token)}
