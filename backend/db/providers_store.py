"""
Providers table — CRUD for AI provider definitions (name, base_url, api_key_env).
Builtin providers are seeded on first run; custom ones are fully user-managed.
"""
from __future__ import annotations

import uuid
from typing import Optional

from backend.db.connection import get_db

# Builtin providers seeded when the table is empty
_BUILTIN_PROVIDERS = [
    {"name": "ollama",     "display_name": "Ollama (local)",  "base_url": "http://localhost:11434/v1",     "api_key_env": ""},
    {"name": "anthropic",  "display_name": "Anthropic",       "base_url": "",                              "api_key_env": "ANTHROPIC_API_KEY"},
    {"name": "openai",     "display_name": "OpenAI",          "base_url": "https://api.openai.com/v1",     "api_key_env": "OPENAI_API_KEY"},
    {"name": "groq",       "display_name": "Groq",            "base_url": "https://api.groq.com/openai/v1","api_key_env": "GROQ_API_KEY"},
    {"name": "openrouter", "display_name": "OpenRouter",      "base_url": "https://openrouter.ai/api/v1",  "api_key_env": "OPENROUTER_API_KEY"},
    {"name": "together",   "display_name": "Together AI",     "base_url": "https://api.together.xyz/v1",   "api_key_env": "TOGETHER_API_KEY"},
    {"name": "mistral",    "display_name": "Mistral",         "base_url": "https://api.mistral.ai/v1",     "api_key_env": "MISTRAL_API_KEY"},
    {"name": "deepseek",   "display_name": "DeepSeek",        "base_url": "https://api.deepseek.com/v1",   "api_key_env": "DEEPSEEK_API_KEY"},
]


async def init_providers_table() -> None:
    async with get_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS providers (
                id           VARCHAR(36)  NOT NULL PRIMARY KEY,
                name         VARCHAR(100) NOT NULL UNIQUE,
                display_name VARCHAR(255) NOT NULL,
                base_url     VARCHAR(500),
                api_key_env  VARCHAR(100),
                is_builtin   BOOLEAN      NOT NULL DEFAULT FALSE,
                created_at   DATETIME     DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def seed_providers() -> None:
    """Insert builtin providers if the table is empty."""
    async with get_db() as db:
        cur = await db.execute("SELECT COUNT(*) AS cnt FROM providers")
        count = (await cur.fetchone())["cnt"]
        if count == 0:
            for p in _BUILTIN_PROVIDERS:
                await db.execute(
                    "INSERT INTO providers (id, name, display_name, base_url, api_key_env, is_builtin) VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), p["name"], p["display_name"], p["base_url"], p["api_key_env"], True),
                )
            await db.commit()


def _row_to_dict(row) -> dict:
    return {
        "id":           row["id"],
        "name":         row["name"],
        "display_name": row["display_name"],
        "base_url":     row["base_url"] or "",
        "api_key_env":  row["api_key_env"] or "",
        "is_builtin":   bool(row["is_builtin"]),
    }


async def list_providers() -> list[dict]:
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM providers ORDER BY is_builtin DESC, name ASC")
        rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


async def get_provider_by_id(provider_id: str) -> Optional[dict]:
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM providers WHERE id = ?", (provider_id,))
        row = await cur.fetchone()
    return _row_to_dict(row) if row else None


async def create_provider(name: str, display_name: str, base_url: str = "", api_key_env: str = "") -> dict:
    pid = str(uuid.uuid4())
    try:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO providers (id, name, display_name, base_url, api_key_env, is_builtin) VALUES (?, ?, ?, ?, ?, ?)",
                (pid, name, display_name, base_url, api_key_env, False),
            )
            await db.commit()
            cur = await db.execute("SELECT * FROM providers WHERE id = ?", (pid,))
            row = await cur.fetchone()
    except Exception as exc:
        msg = str(exc)
        if "1062" in msg or "UNIQUE" in msg.upper() or "unique" in msg:
            raise ValueError(f"Ya existe un provider con el nombre '{name}'.") from exc
        raise
    return _row_to_dict(row)


async def update_provider(
    provider_id: str,
    name: Optional[str] = None,
    display_name: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key_env: Optional[str] = None,
) -> Optional[dict]:
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM providers WHERE id = ?", (provider_id,))
        row = await cur.fetchone()
        if row is None:
            return None
        new_name    = name         if name         is not None else row["name"]
        new_display = display_name if display_name is not None else row["display_name"]
        new_url     = base_url     if base_url     is not None else (row["base_url"] or "")
        new_env     = api_key_env  if api_key_env  is not None else (row["api_key_env"] or "")
        await db.execute(
            "UPDATE providers SET name=?, display_name=?, base_url=?, api_key_env=? WHERE id=?",
            (new_name, new_display, new_url, new_env, provider_id),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM providers WHERE id = ?", (provider_id,))
        row = await cur.fetchone()
    return _row_to_dict(row)


async def delete_provider(provider_id: str) -> bool:
    async with get_db() as db:
        cur = await db.execute("SELECT id FROM providers WHERE id = ?", (provider_id,))
        if await cur.fetchone() is None:
            return False
        await db.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
        await db.commit()
    return True


async def get_provider_map() -> dict[str, dict]:
    """Returns {name: {base_url, api_key_env}} for use by registry/config caches."""
    providers = await list_providers()
    return {
        p["name"]: {"base_url": p["base_url"], "api_key_env": p["api_key_env"]}
        for p in providers
    }
