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
    system_prompt: Optional[str] = None # per-model system prompt override
    temperature: Optional[float] = None  # None = use adapter default (0.3)


class FilesystemToolConfig(BaseModel):
    enabled: bool = True
    allowed_paths: list[str] = Field(default_factory=lambda: ["~"])
    require_confirmation_for: list[str] = Field(default_factory=list)  # empty = no confirmations
    max_file_size_mb: int = 10


class TerminalToolConfig(BaseModel):
    enabled: bool = True
    require_confirmation: bool = False  # off by default — use project permissions
    timeout_seconds: int = 30
    blocked_patterns: list[str] = Field(default_factory=list)


class WebSearchToolConfig(BaseModel):
    enabled: bool = True
    max_results: int = 5


class VideoToolConfig(BaseModel):
    enabled: bool = True
    ffmpeg_path: str = "ffmpeg"   # path or "ffmpeg" if it's on PATH


class ReplicateToolConfig(BaseModel):
    enabled: bool = False
    api_key: str = ""
    default_image_model: str = "black-forest-labs/flux-schnell"
    default_video_model: str = "wan-ai/wan2.1-t2v-480p"


class AttachmentsConfig(BaseModel):
    """Size limits for files attached to chat messages (client-side enforcement)."""
    max_image_mb: int = 5    # max size for image attachments (JPEG, PNG, GIF, WebP)
    max_pdf_mb:   int = 25   # max size for PDF attachments
    max_text_kb:  int = 2048  # max size for text/code file attachments (2 MB)


class ToolsConfig(BaseModel):
    filesystem:  FilesystemToolConfig  = Field(default_factory=FilesystemToolConfig)
    terminal:    TerminalToolConfig    = Field(default_factory=TerminalToolConfig)
    web_search:  WebSearchToolConfig   = Field(default_factory=WebSearchToolConfig)
    video:       VideoToolConfig       = Field(default_factory=VideoToolConfig)
    replicate:   ReplicateToolConfig   = Field(default_factory=ReplicateToolConfig)
    attachments: AttachmentsConfig     = Field(default_factory=AttachmentsConfig)


class AgentConfig(BaseModel):
    max_iterations: int = 40
    memory_file: str = "~/.localforge_memory.md"
    compact_threshold: int = 80_000  # chars — truncate old tool results above this limit
    ollama_num_ctx: int = 8192  # Ollama context window; default 2048 truncates the system prompt
    system_prompt: str = (
        "Eres LocalForge, un agente de programación autónomo con acceso completo al sistema del usuario. "
        "Tu objetivo es escribir, modificar y depurar código real — no describir lo que harías.\n\n"

        "**IDIOMA:** Responde siempre en español salvo que el usuario use otro idioma explícitamente.\n\n"

        "## HERRAMIENTAS DISPONIBLES\n"
        "- **Archivos**: read_file, write_file, edit_file, list_directory, glob, grep, search_files, delete_file\n"
        "- **Terminal**: execute_command — para instalar paquetes, correr tests, compilar, scripts\n"
        "- **Git**: git_status, git_diff, git_log, git_add, git_commit, git_checkout, git_branch, git_pull, git_push\n"
        "- **Planificación**: todo_write, todo_update, todo_read — para rastrear pasos en tareas largas\n"
        "- **Web**: web_search, web_fetch — buscar documentación y leer URLs\n\n"

        "## REGLAS DE COMPORTAMIENTO (NO NEGOCIABLES)\n\n"

        "**Actúa, no anuncies.**\n"
        "PROHIBIDO escribir 'voy a...', 'déjame ver...', 'primero leeré...' sin llamar a la herramienta. "
        "Llama directamente a la herramienta. El texto solo aparece DESPUÉS de los resultados.\n\n"

        "**Lee antes de editar.**\n"
        "Antes de modificar cualquier archivo, usa read_file() para ver el contenido actual exacto. "
        "Nunca supongas cómo está el código — léelo. Luego usa edit_file() con old_string exacto.\n\n"

        "**Explora antes de programar.**\n"
        "En un proyecto existente: usa glob() y grep() para entender la estructura antes de tocar nada. "
        "Busca patrones existentes y síguelos. No inventes arquitecturas nuevas si ya hay una.\n\n"

        "**Planifica tareas complejas.**\n"
        "Si la tarea tiene más de 3 pasos (ej: añadir una feature, refactorizar un módulo, crear una API): "
        "1. Llama a todo_write() con todos los pasos concretos.\n"
        "2. Llama a todo_update() marcando cada paso al iniciarlo (in_progress) y al terminarlo (done).\n"
        "3. Al final verifica con todo_read() que todo está hecho.\n\n"

        "**Usa git correctamente.**\n"
        "- Antes de empezar cambios grandes: git_status() para ver el estado actual.\n"
        "- Después de completar una feature/fix: git_add() + git_commit() con mensaje descriptivo.\n"
        "- Si el usuario pide 'haz un commit', hazlo sin pedir confirmación.\n\n"

        "**Edición de archivos.**\n"
        "- Modificar código existente: SIEMPRE edit_file() con old_string exacto (misma indentación).\n"
        "- Si no conoces el contenido exacto: read_file() primero, luego edit_file().\n"
        "- write_file() solo para crear archivos nuevos o reescritura total.\n\n"

        "**Proyectos multi-archivo.**\n"
        "Si el usuario pide un proyecto completo o varios archivos: crea TODOS de una vez, uno tras otro, "
        "sin pedir confirmación entre archivos. Llama a write_file() repetidamente hasta terminar.\n\n"

        "**Errores de terminal.**\n"
        "Si execute_command falla: analiza el error y corrígelo inmediatamente. "
        "Instala dependencias faltantes, ajusta rutas, modifica el código — lo que haga falta. No preguntes.\n\n"

        "**Archivos adjuntos.**\n"
        "Si el usuario adjunta un archivo (CSV, JSON, código), su contenido está en el mensaje dentro de ```. "
        "Léelo directamente del mensaje — no digas que no lo tienes.\n\n"

        "**Análisis de datos.**\n"
        "Al analizar un dataset: cita valores reales del archivo, no descripciones genéricas. "
        "Usa execute_command con python/pandas para estadísticas reales cuando haya directorio activo.\n\n"

        "## FLUJO TÍPICO DE UNA TAREA DE CÓDIGO\n"
        "1. git_status() — ver estado del repo\n"
        "2. glob() + grep() — explorar estructura del proyecto\n"
        "3. todo_write() — planificar pasos si la tarea es compleja\n"
        "4. read_file() de archivos relevantes\n"
        "5. edit_file() / write_file() para los cambios\n"
        "6. execute_command() para tests / lint / build\n"
        "7. git_add() + git_commit() si procede\n"
        "8. todo_update() marcando cada paso como done\n"
    )


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    allowed_user_ids: list[int] = Field(default_factory=list)
    default_model: str = ""


class SmtpConfig(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    from_email: str = ""
    from_name: str = "LocalForge"
    use_tls: bool = True
    use_ssl: bool = False


class LocalForgeConfig(BaseModel):
    version: str = "1.0"
    default_model: str = "claude-sonnet-4-6"
    models: list[ModelConfig] = Field(default_factory=list)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    smtp: SmtpConfig = Field(default_factory=SmtpConfig)

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
    smtp_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "LocalForge"
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False

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


def get_smtp_config() -> SmtpConfig:
    """Return SMTP config with .env values taking precedence over stored config."""
    cfg = get_config()
    settings = get_settings()
    smtp = cfg.smtp.model_dump()

    if "smtp_enabled" in settings.model_fields_set:
        smtp["enabled"] = settings.smtp_enabled
    if "smtp_host" in settings.model_fields_set:
        smtp["host"] = settings.smtp_host
    if "smtp_port" in settings.model_fields_set:
        smtp["port"] = settings.smtp_port
    if "smtp_username" in settings.model_fields_set:
        smtp["username"] = settings.smtp_username
    if "smtp_password" in settings.model_fields_set:
        smtp["password"] = settings.smtp_password
    if "smtp_from_email" in settings.model_fields_set:
        smtp["from_email"] = settings.smtp_from_email
    if "smtp_from_name" in settings.model_fields_set:
        smtp["from_name"] = settings.smtp_from_name
    if "smtp_use_tls" in settings.model_fields_set:
        smtp["use_tls"] = settings.smtp_use_tls
    if "smtp_use_ssl" in settings.model_fields_set:
        smtp["use_ssl"] = settings.smtp_use_ssl

    return SmtpConfig(**smtp)


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
