"""
User persistence — stores users in the `users` table.
Passwords are hashed with bcrypt directly (no passlib).
"""
from __future__ import annotations

import uuid
from datetime import datetime

import bcrypt

from backend.db.connection import get_db


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


async def init_users_table() -> None:
    async with get_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            VARCHAR(36) PRIMARY KEY,
                first_name    VARCHAR(100) NOT NULL,
                last_name     VARCHAR(100) NOT NULL DEFAULT '',
                email         VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                is_admin      INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL,
                totp_secret   TEXT,
                totp_enabled  INTEGER NOT NULL DEFAULT 0
            )
        """)
        # Migrate existing tables that lack the TOTP columns
        try:
            await db.execute("ALTER TABLE users ADD COLUMN totp_secret TEXT")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        await db.commit()


async def count_users() -> int:
    async with get_db() as db:
        await db.execute("SELECT COUNT(*) as n FROM users")
        row = await db.fetchone()
        return row["n"] if row else 0


async def get_user_by_email(email: str) -> dict | None:
    async with get_db() as db:
        await db.execute(
            "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
        )
        row = await db.fetchone()
        return dict(row) if row else None


async def get_user_by_id(user_id: str) -> dict | None:
    async with get_db() as db:
        await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await db.fetchone()
        return dict(row) if row else None


async def list_users() -> list[dict]:
    async with get_db() as db:
        await db.execute(
            "SELECT id, first_name, last_name, email, is_admin, created_at FROM users ORDER BY created_at ASC"
        )
        rows = await db.fetchall()
        return [dict(r) for r in rows]


async def create_user(
    first_name: str,
    last_name: str,
    email: str,
    password: str,
    is_admin: bool = False,
) -> dict:
    user_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    hashed = hash_password(password)
    async with get_db() as db:
        await db.execute(
            """INSERT INTO users (id, first_name, last_name, email, password_hash, is_admin, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, first_name, last_name, email.lower().strip(), hashed, int(is_admin), now),
        )
        await db.commit()
    return await get_user_by_id(user_id)  # type: ignore


async def update_user(
    user_id: str,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    password: str | None = None,
    is_admin: bool | None = None,
) -> dict | None:
    user = await get_user_by_id(user_id)
    if not user:
        return None

    new_first   = first_name  if first_name  is not None else user["first_name"]
    new_last    = last_name   if last_name   is not None else user["last_name"]
    new_email   = email.lower().strip() if email is not None else user["email"]
    new_hash    = hash_password(password) if password else user["password_hash"]
    new_admin   = int(is_admin) if is_admin is not None else user["is_admin"]

    async with get_db() as db:
        await db.execute(
            """UPDATE users SET first_name=?, last_name=?, email=?, password_hash=?, is_admin=?
               WHERE id=?""",
            (new_first, new_last, new_email, new_hash, new_admin, user_id),
        )
        await db.commit()
    return await get_user_by_id(user_id)


async def update_password(user_id: str, password: str) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(password), user_id),
        )
        await db.commit()


async def delete_user(user_id: str) -> None:
    async with get_db() as db:
        await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.commit()


# ── TOTP helpers ─────────────────────────────────────────────────────────────

async def set_totp_secret(user_id: str, secret: str) -> None:
    """Store a (not-yet-confirmed) TOTP secret. totp_enabled stays 0."""
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET totp_secret = ? WHERE id = ?", (secret, user_id)
        )
        await db.commit()


async def enable_totp(user_id: str) -> None:
    """Mark TOTP as enabled after the user has verified the first code."""
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET totp_enabled = 1 WHERE id = ?", (user_id,)
        )
        await db.commit()


async def disable_totp(user_id: str) -> None:
    """Remove the TOTP secret and disable 2FA."""
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET totp_secret = NULL, totp_enabled = 0 WHERE id = ?",
            (user_id,),
        )
        await db.commit()
