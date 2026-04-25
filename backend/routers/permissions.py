"""
Project permissions API.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class PermissionRequest(BaseModel):
    project_path: str
    permission_type: str  # "execute_command" | "write_file" | "delete_file"


@router.get("/permissions")
async def get_permissions(project_path: str):
    from backend.db.permissions_store import list_permissions
    perms = await list_permissions(project_path)
    return {"project_path": project_path, "permissions": perms}


@router.post("/permissions/grant")
async def grant(req: PermissionRequest):
    from backend.db.permissions_store import grant_permission
    await grant_permission(req.project_path, req.permission_type)
    return {"ok": True}


@router.post("/permissions/revoke")
async def revoke(req: PermissionRequest):
    from backend.db.permissions_store import revoke_permission
    await revoke_permission(req.project_path, req.permission_type)
    return {"ok": True}


@router.delete("/permissions")
async def revoke_all(project_path: str):
    from backend.db.permissions_store import revoke_all_permissions
    await revoke_all_permissions(project_path)
    return {"ok": True}
