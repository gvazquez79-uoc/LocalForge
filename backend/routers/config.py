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

from backend.config import get_config, save_config, save_config_to_db, ToolsConfig, AgentConfig, TelegramConfig

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
    """Return only explicitly configured models (from DB).
    Ollama auto-discovery is handled by GET /config/models/discover."""
    cfg = get_config()

    all_models = [
        {
            "name": m.name,
            "display_name": m.display_name,
            "provider": m.provider,
            # Ollama models never need a key; others need one to be available
            "available": m.provider == "ollama" or bool(cfg.get_model_api_key(m)),
        }
        for m in cfg.models
    ]

    default = cfg.default_model
    available_names = {m["name"] for m in all_models if m["available"]}
    if default not in available_names and available_names:
        default = next(m["name"] for m in all_models if m["available"])

    return {
        "models": all_models,
        "default_model": default,
    }


@router.get("/models/discover")
async def discover_models():
    """Auto-discover Ollama models running locally.
    Returns all discovered models plus whether each is already configured in DB."""
    cfg = get_config()
    configured_names = {m.name for m in cfg.models}

    # Resolve Ollama base URL from providers table
    from backend.models.registry import _PROVIDER_DEFAULTS
    ollama_base_url = _PROVIDER_DEFAULTS.get("ollama", "http://localhost:11434/v1")

    ollama_models = await _discover_ollama_models(ollama_base_url)
    return [
        {**m, "already_configured": m["name"] in configured_names}
        for m in ollama_models
    ]


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

    await save_config_to_db(cfg)
    return {"ok": True}


@router.get("/memory")
async def read_memory():
    """Return the contents of the persistent memory file and its resolved path."""
    from pathlib import Path
    cfg = get_config()
    memory_path = Path(cfg.agent.memory_file).expanduser()
    content = memory_path.read_text(encoding="utf-8") if memory_path.exists() else ""
    return {"content": content, "path": str(memory_path)}


@router.delete("/memory")
async def clear_memory():
    """Overwrite the persistent memory file with empty content."""
    from pathlib import Path
    cfg = get_config()
    memory_path = Path(cfg.agent.memory_file).expanduser()
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text("", encoding="utf-8")
    return {"ok": True}


@router.get("/project-instructions")
async def get_project_instructions(working_directory: str):
    """Return the contents of LOCALFORGE.md (or CLAUDE.md) from the project root."""
    from pathlib import Path
    wd = Path(working_directory).expanduser()
    for filename in ("LOCALFORGE.md", "localforge.md", "CLAUDE.md", ".claude.md"):
        candidate = wd / filename
        if candidate.exists():
            try:
                return {
                    "content": candidate.read_text(encoding="utf-8"),
                    "filename": filename,
                    "path": str(candidate),
                    "exists": True,
                }
            except Exception:
                pass
    return {
        "content": "",
        "filename": "LOCALFORGE.md",
        "path": str(wd / "LOCALFORGE.md"),
        "exists": False,
    }


@router.put("/project-instructions")
async def save_project_instructions(body: dict):
    """Write LOCALFORGE.md to the project root."""
    from pathlib import Path
    working_directory = body.get("working_directory", "")
    content = body.get("content", "")
    filename = body.get("filename", "LOCALFORGE.md")
    if not working_directory:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="working_directory required")
    path = Path(working_directory).expanduser() / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(path)}


@router.post("/providers/{provider_name}/discover-models")
async def discover_provider_models(provider_name: str):
    """Discover and load available models from a provider."""
    import os
    from fastapi import HTTPException
    from backend.db.providers_store import list_providers
    from backend.db.models_store import list_models_masked, create_model
    from backend.config import refresh_models_from_db, _PROVIDER_KEYS

    # Load provider from DB
    all_providers = await list_providers()
    provider = next((p for p in all_providers if p["name"] == provider_name), None)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' not found")

    # Get API key: DB key takes priority, then env cache, then raw env var
    api_key = (
        _PROVIDER_KEYS.get(provider_name)
        or os.environ.get(provider.get("api_key_env") or "", "")
    )

    discovered: list[dict] = []

    try:
        if provider_name == "anthropic":
            if not api_key:
                raise ValueError("API key de Anthropic no configurada. Ve a Settings → Providers → Anthropic y añade tu key.")
            discovered = [
                {"name": "claude-opus-4-5",          "display_name": "Claude Opus 4.5"},
                {"name": "claude-sonnet-4-5",         "display_name": "Claude Sonnet 4.5"},
                {"name": "claude-haiku-4-5-20251001", "display_name": "Claude Haiku 4.5"},
            ]

        elif provider_name == "ollama":
            base_url = provider.get("base_url") or "http://localhost:11434/v1"
            discovered = await _discover_ollama_models(base_url)

        elif provider_name == "openai":
            if not api_key:
                raise ValueError("API key de OpenAI no configurada.")
            base_url = provider.get("base_url") or "https://api.openai.com/v1"
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
                resp.raise_for_status()
                discovered = [
                    {"name": m["id"], "display_name": m["id"]}
                    for m in resp.json().get("data", [])
                    if "gpt" in m["id"].lower()
                ]

        elif provider_name == "groq":
            if not api_key:
                raise ValueError("API key de Groq no configurada.")
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {api_key}"})
                resp.raise_for_status()
                discovered = [
                    {"name": m["id"], "display_name": m["id"]}
                    for m in resp.json().get("data", [])
                ]

        else:
            raise HTTPException(status_code=400, detail=f"Discovery no soportado para '{provider_name}'")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:300])

    # Save to DB, skip duplicates
    existing_names = {m["name"] for m in await list_models_masked()}
    saved_count = 0
    for model in discovered:
        if model["name"] not in existing_names:
            await create_model(
                name=model["name"],
                display_name=model["display_name"],
                provider=provider_name,
                base_url=provider.get("base_url") or None,
            )
            saved_count += 1

    if saved_count > 0:
        await refresh_models_from_db()

    return {"ok": True, "discovered": len(discovered), "saved": saved_count, "models": discovered}


@router.post("/telegram/restart")
async def restart_telegram():
    """Stop and restart the Telegram bot with the current config (no backend restart needed)."""
    import asyncio
    from backend.telegram.bot import stop_telegram_bot, start_telegram_bot
    await stop_telegram_bot()
    await asyncio.sleep(1)   # give Telegram servers time to release the connection
    await start_telegram_bot()
    cfg = get_config()
    return {"ok": True, "running": cfg.telegram.enabled and bool(cfg.telegram.bot_token)}
