"""
Model registry — creates the right adapter based on config.

Supported providers:
  anthropic  → AnthropicAdapter (Claude models)
  ollama     → OpenAICompatAdapter (local, no key needed)
  openai     → OpenAICompatAdapter (api.openai.com)
  groq       → OpenAICompatAdapter (api.groq.com/openai/v1)
  openrouter → OpenAICompatAdapter (openrouter.ai/api/v1)
  together   → OpenAICompatAdapter (api.together.xyz/v1)
  <any>      → OpenAICompatAdapter if base_url is set in config

Falls back to Ollama for any model not explicitly in localforge.json.
"""
from __future__ import annotations

from backend.config import LocalForgeConfig, get_config
from backend.models.base import BaseModelAdapter

# Well-known base URLs for providers that don't require base_url in config.
# Populated from DB at startup via config.refresh_providers_cache();
# these are the defaults used before the DB is available.
_PROVIDER_DEFAULTS: dict[str, str] = {
    "openai":      "https://api.openai.com/v1",
    "groq":        "https://api.groq.com/openai/v1",
    "openrouter":  "https://openrouter.ai/api/v1",
    "together":    "https://api.together.xyz/v1",
    "mistral":     "https://api.mistral.ai/v1",
    "deepseek":    "https://api.deepseek.com/v1",
    "ollama":      "http://localhost:11434/v1",
}


def update_provider_defaults(defaults: dict[str, str]) -> None:
    """Called by config.refresh_providers_cache() to sync DB provider URLs."""
    global _PROVIDER_DEFAULTS
    _PROVIDER_DEFAULTS = defaults


def _get_ollama_base_url(cfg: LocalForgeConfig) -> str:
    """Return the base_url of the first Ollama model in config, or default."""
    for m in cfg.models:
        if m.provider == "ollama" and m.base_url:
            return m.base_url
    return "http://localhost:11434/v1"


def get_adapter(model_name: str | None = None, config: LocalForgeConfig | None = None) -> BaseModelAdapter:
    cfg = config or get_config()
    name = (model_name or cfg.default_model).strip()

    import logging
    logging.getLogger(__name__).info(f"get_adapter called: model_name={model_name!r} → name={name!r}")

    model_cfg = cfg.get_model(name)

    # ── Model explicitly configured in localforge.json ────────────────────────
    if model_cfg is not None:
        api_key = cfg.get_model_api_key(model_cfg) or ""

        if model_cfg.provider == "anthropic":
            from backend.models.anthropic import AnthropicAdapter
            if not api_key:
                raise ValueError(
                    f"API key not set for model '{name}'. Set {model_cfg.api_key_env} in .env"
                )
            return AnthropicAdapter(model_name=name, api_key=api_key)

        # Ollama → use native /api/chat adapter (avoids empty-response bug in /v1/chat/completions)
        if model_cfg.provider == "ollama":
            from backend.models.ollama_native import OllamaNativeAdapter
            base_url = (
                model_cfg.base_url
                or _PROVIDER_DEFAULTS.get("ollama")
                or _get_ollama_base_url(cfg)
            )
            return OllamaNativeAdapter(model_name=name, base_url=base_url)

        # Any other OpenAI-compatible provider (openai, groq, openrouter, etc.)
        from backend.models.openai_compat import OpenAICompatAdapter

        # Resolve base_url: explicit config > known provider defaults > Ollama fallback
        base_url = (
            model_cfg.base_url
            or _PROVIDER_DEFAULTS.get(model_cfg.provider)
            or _get_ollama_base_url(cfg)
        )
        effective_key = api_key or "no-key"
        return OpenAICompatAdapter(model_name=name, base_url=base_url, api_key=effective_key)

    # ── Model not in config → assume it's an Ollama model discovered at runtime ─
    from backend.models.ollama_native import OllamaNativeAdapter
    ollama_url = _get_ollama_base_url(cfg)
    return OllamaNativeAdapter(model_name=name, base_url=ollama_url)
