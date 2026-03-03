"""
Database connection abstraction — SQLite (default) or MySQL.

Set DATABASE_URL=mysql://user:pass@host:3306/dbname in .env to use MySQL.
Without it, falls back to SQLite (./localforge.db).
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DATABASE_URL: str = os.getenv("DATABASE_URL", "")
DB_PATH = Path("./localforge.db")

_mysql_pool: Any = None


def is_mysql() -> bool:
    return DATABASE_URL.lower().startswith("mysql")


def _parse_mysql_url(url: str) -> dict:
    p = urlparse(url)
    return {
        "host": p.hostname or "localhost",
        "port": p.port or 3306,
        "user": p.username,
        "password": p.password or "",
        "db": p.path.lstrip("/"),
    }


async def init_pool() -> None:
    """Create MySQL connection pool. No-op for SQLite."""
    global _mysql_pool
    if is_mysql() and _mysql_pool is None:
        import aiomysql
        params = _parse_mysql_url(DATABASE_URL)
        _mysql_pool = await aiomysql.create_pool(
            host=params["host"],
            port=params["port"],
            user=params["user"],
            password=params["password"],
            db=params["db"],
            charset="utf8mb4",
            autocommit=False,
            minsize=1,
            maxsize=10,
            cursorclass=aiomysql.DictCursor,
        )


async def close_pool() -> None:
    """Close MySQL pool. No-op for SQLite."""
    global _mysql_pool
    if _mysql_pool is not None:
        _mysql_pool.close()
        await _mysql_pool.wait_closed()
        _mysql_pool = None


class _Wrapper:
    """Unified interface over aiosqlite connection or aiomysql cursor."""

    def __init__(self, backend: str, conn: Any, cursor: Any = None):
        self._backend = backend
        self._conn = conn
        self._cursor = cursor

    async def execute(self, sql: str, params: tuple = ()) -> "_Wrapper":
        if self._backend == "mysql":
            await self._cursor.execute(sql.replace("?", "%s"), params or None)
        else:
            self._cursor = await self._conn.execute(sql, params)
        return self

    async def executescript(self, sql: str) -> None:
        """Run multiple ';'-separated statements."""
        if self._backend == "mysql":
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt:
                    await self._cursor.execute(stmt)
            await self._conn.commit()
        else:
            await self._conn.executescript(sql)

    async def fetchall(self) -> list[dict]:
        rows = await self._cursor.fetchall()
        if self._backend == "sqlite":
            return [dict(r) for r in rows]
        return list(rows)

    async def fetchone(self) -> dict | None:
        row = await self._cursor.fetchone()
        if row is None:
            return None
        return dict(row) if self._backend == "sqlite" else dict(row)

    async def commit(self) -> None:
        await self._conn.commit()


@asynccontextmanager
async def get_db():
    """Async context manager — yields a unified _Wrapper for the active DB."""
    if is_mysql():
        if _mysql_pool is None:
            raise RuntimeError("MySQL pool not initialised. Call init_pool() first.")
        async with _mysql_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                wrapper = _Wrapper("mysql", conn, cursor)
                try:
                    yield wrapper
                except Exception:
                    await conn.rollback()
                    raise
    else:
        import aiosqlite
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            yield _Wrapper("sqlite", conn)
