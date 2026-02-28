"""
Model registry — creates the right adapter based on config.
Falls back to Ollama for any model not explicitly in localforge.json.
"""
from __future__ import annotations

from backend.config import LocalForgeConfig, get_config
from backend.models.base import BaseModelAdapter


def _get_ollama_base_url(cfg: LocalForgeConfig) -> str:
    """Return the base_url of the first Ollama model in config, or default."""
    for m in cfg.models:
        if m.provider == "ollama" and m.base_url:
            return m.base_url
    return "http://localhost:11434/v1"


def get_adapter(model_name: str | None = None, config: LocalForgeConfig | None = None) -> BaseModelAdapter:
    cfg = config or get_config()
    name = model_name or cfg.default_model
    model_cfg = cfg.get_model(name)

    # Model explicitly configured in localforge.json
    if model_cfg is not None:
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

    # Model not in config — assume it's an Ollama model discovered at runtime
    from backend.models.openai_compat import OpenAICompatAdapter
    ollama_url = _get_ollama_base_url(cfg)
    return OpenAICompatAdapter(model_name=name, base_url=ollama_url, api_key="ollama")
