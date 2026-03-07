"""
Configuration system — reads localforge.json + .env
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


# ── JSON schema models ───────────────────────────────────────────────────────

class ModelConfig(BaseModel):
    name: str
    display_name: str
    provider: str  # "anthropic" | "ollama" | "openai" | "groq" | etc.
    api_key_env: Optional[str] = None   # env var name (backward compat)
    api_key: Optional[str] = None       # direct key (from DB)
    base_url: Optional[str] = None
    id: Optional[str] = None            # DB row id (None for JSON-sourced models)


class FilesystemToolConfig(BaseModel):
    enabled: bool = True
    allowed_paths: list[str] = Field(default_factory=lambda: ["~"])
    require_confirmation_for: list[str] = Field(default_factory=lambda: ["write_file", "delete_file"])
    max_file_size_mb: int = 10


class TerminalToolConfig(BaseModel):
    enabled: bool = True
    require_confirmation: bool = True
    timeout_seconds: int = 30
    blocked_patterns: list[str] = Field(default_factory=list)


class WebSearchToolConfig(BaseModel):
    enabled: bool = True
    max_results: int = 5


class AttachmentsConfig(BaseModel):
    """Size limits for files attached to chat messages (client-side enforcement)."""
    max_image_mb: int = 5    # max size for image attachments (JPEG, PNG, GIF, WebP)
    max_pdf_mb:   int = 25   # max size for PDF attachments
    max_text_kb:  int = 512  # max size for text/code file attachments


class ToolsConfig(BaseModel):
    filesystem:  FilesystemToolConfig  = Field(default_factory=FilesystemToolConfig)
    terminal:    TerminalToolConfig    = Field(default_factory=TerminalToolConfig)
    web_search:  WebSearchToolConfig   = Field(default_factory=WebSearchToolConfig)
    attachments: AttachmentsConfig     = Field(default_factory=AttachmentsConfig)


class AgentConfig(BaseModel):
    max_iterations: int = 20
    system_prompt: str = (
        "Eres LocalForge, un asistente de IA con acceso a herramientas que te permiten trabajar "
        "directamente con el ordenador del usuario.\n\n"
        "Tus herramientas:\n"
        "- **Sistema de archivos** — listar directorios, leer, escribir y buscar archivos\n"
        "- **Terminal** — ejecutar comandos y scripts de shell\n"
        "- **Búsqueda web** — buscar información actualizada en internet\n"
        "- **Visión** — analizar imágenes y documentos PDF\n\n"
        "Cómo comportarte:\n"
        "- Cuando el usuario te pida hacer algo, llama a la herramienta apropiada directamente. "
        "No anuncies lo que vas a hacer — simplemente hazlo.\n"
        "- Sé útil, directo y conciso. Muestra resultados reales, no descripciones de lo que harás.\n"
        "- Si te preguntan qué puedes hacer, explica tus herramientas de forma breve y natural.\n"
        "- Para conversación casual o saludos, responde con naturalidad sin listar capacidades."
    )


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    allowed_user_ids: list[int] = Field(default_factory=list)
    default_model: str = ""


class LocalForgeConfig(BaseModel):
    version: str = "1.0"
    default_model: str = "claude-sonnet-4-6"
    models: list[ModelConfig] = Field(default_factory=list)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)

    def get_model(self, name: str) -> Optional[ModelConfig]:
        for m in self.models:
            if m.name == name:
                return m
        return None

    def get_model_api_key(self, model: ModelConfig) -> Optional[str]:
        # 1. Explicit key stored in DB on the model itself (override)
        if model.api_key:
            return model.api_key
        # 2. Provider's direct API key stored in DB
        provider_key = _PROVIDER_KEYS.get(model.provider)
        if provider_key:
            return provider_key
        # 3. Explicit env-var name configured on the model
        if model.api_key_env:
            return os.environ.get(model.api_key_env)
        # 4. Auto-detect from standard env var for known providers
        env_var = _PROVIDER_ENV_VARS.get(model.provider)
        if env_var:
            return os.environ.get(env_var)
        return None

    def resolve_allowed_paths(self) -> list[Path]:
        paths = []
        for p in self.tools.filesystem.allowed_paths:
            paths.append(Path(p).expanduser().resolve())
        return paths


# ── App settings (from .env) ─────────────────────────────────────────────────

class AppSettings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000
    config_path: str = "./localforge.json"

    model_config = {"env_prefix": "LOCALFORGE_", "env_file": ".env", "extra": "ignore"}


# Standard env-var names for known providers (fallback when no key stored in DB).
# Populated from DB at startup via refresh_providers_cache(); defaults used before
# the DB is available.
_PROVIDER_ENV_VARS: dict[str, str] = {
    "anthropic":  "ANTHROPIC_API_KEY",
    "groq":       "GROQ_API_KEY",
    "openai":     "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "mistral":    "MISTRAL_API_KEY",
    "deepseek":   "DEEPSEEK_API_KEY",
    "together":   "TOGETHER_API_KEY",
}

# Direct API keys stored in DB per provider.
# Populated from DB at startup via refresh_providers_cache().
_PROVIDER_KEYS: dict[str, str] = {}

# ── Singleton loaders ─────────────────────────────────────────────────────────

_config: Optional[LocalForgeConfig] = None
_settings: Optional[AppSettings] = None


def get_settings() -> AppSettings:
    global _settings
    if _settings is None:
        _settings = AppSettings()
    return _settings


def load_config(path: Optional[str] = None) -> LocalForgeConfig:
    global _config
    settings = get_settings()
    config_file = Path(path or settings.config_path)

    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        _config = LocalForgeConfig(**data)
    else:
        _config = LocalForgeConfig()

    return _config


def get_config() -> LocalForgeConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def save_config(config: LocalForgeConfig, path: Optional[str] = None) -> None:
    settings = get_settings()
    config_file = Path(path or settings.config_path)
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, indent=2)
    global _config
    _config = config


async def save_config_to_db(config: LocalForgeConfig) -> None:
    """Save non-model config fields to DB. Models have their own table."""
    global _config
    _config = config
    from backend.db.settings_store import save_app_config
    data = config.model_dump(exclude={"models"})
    await save_app_config(data)


async def refresh_config_from_db() -> None:
    """Load non-model config from DB and update in-memory config.

    If DB has no stored config yet (first run / migration), seeds it from the
    currently loaded JSON values so future saves go to DB only.
    """
    global _config
    if _config is None:
        _config = load_config()
    try:
        from backend.db.settings_store import get_app_config, save_app_config
        data = await get_app_config()
        if data is None:
            # First run — seed DB from localforge.json values
            seed = _config.model_dump(exclude={"models"})
            await save_app_config(seed)
        else:
            # DB is the source of truth — override in-memory config
            current = _config.model_dump()
            for key in ("version", "default_model", "tools", "agent", "telegram"):
                if key in data:
                    current[key] = data[key]
            _config = LocalForgeConfig(**current)
    except Exception:
        pass  # DB unavailable — keep JSON config


async def refresh_models_from_db() -> None:
    """Load models from DB and update the in-memory config.
    Called at startup and after any model CRUD operation."""
    global _config
    if _config is None:
        _config = load_config()
    try:
        from backend.db.models_store import list_models_db
        db_models = await list_models_db()
        if db_models:
            _config.models = db_models
            # Sync default_model with DB flag
            for m in db_models:
                if getattr(m, "is_default", False):
                    _config.default_model = m.name
                    break
    except Exception:
        pass  # DB not available — keep JSON models


async def refresh_providers_cache() -> None:
    """Load providers from DB and update the in-memory caches used by
    get_model_api_key() and registry.get_adapter().
    Called at startup and after any provider CRUD operation."""
    global _PROVIDER_ENV_VARS, _PROVIDER_KEYS
    try:
        from backend.db.providers_store import get_provider_map
        pmap = await get_provider_map()
        # Update env-var lookup table
        _PROVIDER_ENV_VARS = {
            name: info["api_key_env"]
            for name, info in pmap.items()
            if info.get("api_key_env")
        }
        # Update direct API keys from DB
        _PROVIDER_KEYS = {
            name: info["api_key"]
            for name, info in pmap.items()
            if info.get("api_key")
        }
        # Update provider base-URL defaults in the model registry
        from backend.models.registry import update_provider_defaults
        provider_urls = {
            name: info["base_url"]
            for name, info in pmap.items()
            if info.get("base_url")
        }
        update_provider_defaults(provider_urls)
    except Exception:
        pass  # Keep current cache if DB unavailable
