"""
Project-level permission store.
Remembers which tool categories the user has approved per project path.
"""
from __future__ import annotations

from backend.db.connection import get_db


async def init_permissions_table() -> None:
    async with get_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS project_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_path TEXT NOT NULL,
                permission_type TEXT NOT NULL,
                granted_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (project_path, permission_type)
            )
        """)
        await db.commit()


async def has_permission(project_path: str, permission_type: str) -> bool:
    """Return True if the user has previously granted this permission for this project."""
    async with get_db() as db:
        await db.execute(
            "SELECT 1 FROM project_permissions WHERE project_path = ? AND permission_type = ?",
            (project_path, permission_type),
        )
        row = await db.fetchone()
        return row is not None


async def grant_permission(project_path: str, permission_type: str) -> None:
    """Save a granted permission for this project."""
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO project_permissions (project_path, permission_type)
            VALUES (?, ?)
            ON CONFLICT(project_path, permission_type) DO NOTHING
            """,
            (project_path, permission_type),
        )
        await db.commit()


async def revoke_permission(project_path: str, permission_type: str) -> None:
    """Remove a saved permission."""
    async with get_db() as db:
        await db.execute(
            "DELETE FROM project_permissions WHERE project_path = ? AND permission_type = ?",
            (project_path, permission_type),
        )
        await db.commit()


async def list_permissions(project_path: str) -> list[str]:
    """Return all granted permission types for this project."""
    async with get_db() as db:
        await db.execute(
            "SELECT permission_type FROM project_permissions WHERE project_path = ?",
            (project_path,),
        )
        rows = await db.fetchall()
        return [r["permission_type"] for r in rows]


async def revoke_all_permissions(project_path: str) -> None:
    """Revoke all permissions for a project."""
    async with get_db() as db:
        await db.execute(
            "DELETE FROM project_permissions WHERE project_path = ?",
            (project_path,),
        )
        await db.commit()
