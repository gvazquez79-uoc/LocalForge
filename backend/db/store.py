"""
SQLite-backed conversation store using aiosqlite.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

import aiosqlite

DB_PATH = Path("./localforge.db")


@asynccontextmanager
async def get_db():
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        yield db


async def init_db() -> None:
    async with get_db() as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'New conversation',
                model TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );
        """)
        await db.commit()


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
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_conversation(conv_id: str) -> Optional[dict]:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


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
            d = dict(r)
            try:
                d["content"] = json.loads(d["content"])
            except (json.JSONDecodeError, TypeError):
                pass
            result.append(d)
        return result
