"""
Persistent settings storage in DB.

Stores the app config (tools, agent, telegram, default_model) as a JSON blob
under the key 'app_config' in the settings table.
The models table handles model entries separately.
"""
from __future__ import annotations

import json

from backend.db.connection import get_db

_CONFIG_KEY = "app_config"


async def init_settings_table() -> None:
    async with get_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                setting_key VARCHAR(255) PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.commit()


async def _get_setting(key: str) -> str | None:
    async with get_db() as db:
        await db.execute(
            "SELECT value FROM settings WHERE setting_key = ?", (key,)
        )
        row = await db.fetchone()
        return row["value"] if row else None


async def _set_setting(key: str, value: str) -> None:
    async with get_db() as db:
        await db.execute(
            "DELETE FROM settings WHERE setting_key = ?", (key,)
        )
        await db.execute(
            "INSERT INTO settings (setting_key, value) VALUES (?, ?)", (key, value)
        )
        await db.commit()


async def get_app_config() -> dict | None:
    """Return stored config dict, or None if not yet seeded."""
    raw = await _get_setting(_CONFIG_KEY)
    if raw is None:
        return None
    return json.loads(raw)


async def save_app_config(data: dict) -> None:
    """Persist config dict to DB."""
    await _set_setting(_CONFIG_KEY, json.dumps(data, ensure_ascii=False))
