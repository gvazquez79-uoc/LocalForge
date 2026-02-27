"""
Model registry — creates the right adapter based on config.
"""
from __future__ import annotations

from backend.config import LocalForgeConfig, ModelConfig, get_config
from backend.models.base import BaseModelAdapter


def get_adapter(model_name: str | None = None, config: LocalForgeConfig | None = None) -> BaseModelAdapter:
    cfg = config or get_config()
    name = model_name or cfg.default_model
    model_cfg = cfg.get_model(name)

    if model_cfg is None:
        raise ValueError(f"Model '{name}' not found in localforge.json")

    api_key = cfg.get_model_api_key(model_cfg) or ""

    if model_cfg.provider == "anthropic":
        from backend.models.anthropic import AnthropicAdapter
        if not api_key:
            raise ValueError(f"API key not set for model '{name}'. Set {model_cfg.api_key_env} in .env")
        return AnthropicAdapter(model_name=name, api_key=api_key)

    elif model_cfg.provider in ("ollama", "openai"):
        from backend.models.openai_compat import OpenAICompatAdapter
        base_url = model_cfg.base_url or "https://api.openai.com/v1"
        return OpenAICompatAdapter(model_name=name, base_url=base_url, api_key=api_key or "ollama")

    else:
        raise ValueError(f"Unknown provider '{model_cfg.provider}' for model '{name}'")
