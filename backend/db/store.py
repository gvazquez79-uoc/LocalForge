"""
Conversation store — backed by SQLite or MySQL via connection.py.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Optional

from backend.db.connection import get_db


async def init_db() -> None:
    async with get_db() as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id VARCHAR(36) PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'New conversation',
                model VARCHAR(255) NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id VARCHAR(36) PRIMARY KEY,
                conversation_id VARCHAR(36) NOT NULL,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
        """)


async def create_conversation(model: str, title: str = "New conversation") -> dict:
    now = int(time.time())
    conv_id = str(uuid.uuid4())
    async with get_db() as db:
        await db.execute(
            "INSERT INTO conversations (id, title, model, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (conv_id, title, model, now, now),
        )
        await db.commit()
    return {"id": conv_id, "title": title, "model": model, "created_at": now, "updated_at": now}


async def list_conversations(limit: int = 50) -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,)
        )
        return await cursor.fetchall()


async def get_conversation(conv_id: str) -> Optional[dict]:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
        return await cursor.fetchone()


async def update_conversation_title(conv_id: str, title: str) -> None:
    now = int(time.time())
    async with get_db() as db:
        await db.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, now, conv_id),
        )
        await db.commit()


async def delete_conversation(conv_id: str) -> None:
    async with get_db() as db:
        await db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        await db.commit()


async def add_message(conv_id: str, role: str, content: str | list, metadata: dict | None = None) -> dict:
    now = int(time.time())
    msg_id = str(uuid.uuid4())
    content_str = json.dumps(content) if isinstance(content, list) else content
    meta_str = json.dumps(metadata) if metadata else None

    async with get_db() as db:
        await db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, conv_id, role, content_str, meta_str, now),
        )
        await db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id))
        await db.commit()

    return {"id": msg_id, "conversation_id": conv_id, "role": role, "content": content, "created_at": now}


async def get_messages(conv_id: str) -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conv_id,),
        )
        rows = await cursor.fetchall()

    result = []
    for r in rows:
        try:
            r["content"] = json.loads(r["content"])
        except (json.JSONDecodeError, TypeError):
            pass
        result.append(r)
    return result
