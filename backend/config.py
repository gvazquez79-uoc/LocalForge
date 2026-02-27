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
    provider: str  # "anthropic" | "ollama" | "openai"
    api_key_env: Optional[str] = None
    base_url: Optional[str] = None


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


class ToolsConfig(BaseModel):
    filesystem: FilesystemToolConfig = Field(default_factory=FilesystemToolConfig)
    terminal: TerminalToolConfig = Field(default_factory=TerminalToolConfig)
    web_search: WebSearchToolConfig = Field(default_factory=WebSearchToolConfig)


class AgentConfig(BaseModel):
    max_iterations: int = 20
    system_prompt: str = (
        "You are LocalForge, a helpful AI assistant with access to the local file "
        "system, terminal, and web search. Always be precise when working with files "
        "and commands. Ask for confirmation before destructive operations."
    )


class LocalForgeConfig(BaseModel):
    version: str = "1.0"
    default_model: str = "claude-sonnet-4-6"
    models: list[ModelConfig] = Field(default_factory=list)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)

    def get_model(self, name: str) -> Optional[ModelConfig]:
        for m in self.models:
            if m.name == name:
                return m
        return None

    def get_model_api_key(self, model: ModelConfig) -> Optional[str]:
        if model.api_key_env:
            return os.environ.get(model.api_key_env)
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
