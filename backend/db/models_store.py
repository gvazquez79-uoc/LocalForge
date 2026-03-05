"""
Persistent model store — CRUD for the `models` table.
Works with both SQLite and MySQL via connection.py.
"""
from __future__ import annotations

import uuid
from typing import Optional

from backend.config import ModelConfig
from backend.db.connection import get_db


async def init_models_table() -> None:
    async with get_db() as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS models (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                display_name VARCHAR(255) NOT NULL,
                provider VARCHAR(50) NOT NULL,
                api_key TEXT,
                base_url VARCHAR(500),
                is_default TINYINT(1) DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)


async def list_models_db() -> list[ModelConfig]:
    """Return all models from DB as ModelConfig objects (api_key populated)."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM models ORDER BY is_default DESC, created_at ASC"
        )
        rows = await cursor.fetchall()
    return [_row_to_model(r) for r in rows]


async def list_models_masked() -> list[dict]:
    """Return all models with api_key masked (for API responses)."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM models ORDER BY is_default DESC, created_at ASC"
        )
        rows = await cursor.fetchall()
    return [_row_to_dict_masked(r) for r in rows]


async def get_model_by_id(model_id: str) -> Optional[dict]:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM models WHERE id = ?", (model_id,))
        row = await cursor.fetchone()
    return _row_to_dict_masked(row) if row else None


async def create_model(
    name: str,
    display_name: str,
    provider: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    is_default: bool = False,
) -> dict:
    model_id = str(uuid.uuid4())
    if is_default:
        await _clear_default()
    try:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO models (id, name, display_name, provider, api_key, base_url, is_default) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (model_id, name, display_name, provider, api_key or None, base_url or None, 1 if is_default else 0),
            )
            await db.commit()
    except Exception as exc:
        msg = str(exc)
        if "1062" in msg or "UNIQUE" in msg.upper() or "unique" in msg:
            raise ValueError(f"Ya existe un modelo con el nombre '{name}'. Usa un nombre diferente.") from exc
        raise
    row = await _fetch_by_id(model_id)
    return _row_to_dict_masked(row)


async def update_model(
    model_id: str,
    name: Optional[str] = None,
    display_name: Optional[str] = None,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,   # None = don't change; "" = clear key
    base_url: Optional[str] = None,
    is_default: Optional[bool] = None,
) -> Optional[dict]:
    row = await _fetch_by_id(model_id)
    if row is None:
        return None

    new_name         = name         if name         is not None else row["name"]
    new_display_name = display_name if display_name is not None else row["display_name"]
    new_provider     = provider     if provider     is not None else row["provider"]
    new_base_url     = base_url     if base_url     is not None else row["base_url"]

    # api_key: None = keep existing, "" = clear, otherwise replace
    if api_key is None:
        new_api_key = row["api_key"]
    elif api_key == "":
        new_api_key = None
    else:
        new_api_key = api_key

    if is_default:
        await _clear_default()
    new_is_default = 1 if is_default else (row.get("is_default", 0) if is_default is None else 0)

    async with get_db() as db:
        await db.execute(
            "UPDATE models SET name=?, display_name=?, provider=?, api_key=?, "
            "base_url=?, is_default=? WHERE id=?",
            (new_name, new_display_name, new_provider, new_api_key,
             new_base_url or None, new_is_default, model_id),
        )
        await db.commit()

    row = await _fetch_by_id(model_id)
    return _row_to_dict_masked(row)


async def delete_model(model_id: str) -> bool:
    row = await _fetch_by_id(model_id)
    if row is None:
        return False
    async with get_db() as db:
        await db.execute("DELETE FROM models WHERE id = ?", (model_id,))
        await db.commit()
    return True


async def set_default_model(model_id: str) -> Optional[dict]:
    await _clear_default()
    async with get_db() as db:
        await db.execute("UPDATE models SET is_default = 1 WHERE id = ?", (model_id,))
        await db.commit()
    row = await _fetch_by_id(model_id)
    return _row_to_dict_masked(row) if row else None


async def seed_from_config(models: list) -> None:
    """Seed the DB from localforge.json models if the table is empty."""
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM models")
        row = await cursor.fetchone()
        count = row["cnt"] if row else 0

    if count > 0:
        return  # already seeded

    for i, m in enumerate(models):
        await create_model(
            name=m.name,
            display_name=m.display_name,
            provider=m.provider,
            api_key=m.api_key,  # usually None for JSON models
            base_url=m.base_url,
            is_default=(i == 0),
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fetch_by_id(model_id: str) -> Optional[dict]:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM models WHERE id = ?", (model_id,))
        return await cursor.fetchone()


async def _clear_default() -> None:
    async with get_db() as db:
        await db.execute("UPDATE models SET is_default = 0")
        await db.commit()


def _mask_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    if len(key) <= 4:
        return "****"
    return "****" + key[-4:]


def _row_to_dict_masked(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "display_name": row["display_name"],
        "provider": row["provider"],
        "api_key_masked": _mask_key(row.get("api_key")),
        "base_url": row.get("base_url"),
        "is_default": bool(row.get("is_default", 0)),
    }


def _row_to_model(row: dict) -> ModelConfig:
    return ModelConfig(
        id=row["id"],
        name=row["name"],
        display_name=row["display_name"],
        provider=row["provider"],
        api_key=row.get("api_key"),
        base_url=row.get("base_url"),
    )
