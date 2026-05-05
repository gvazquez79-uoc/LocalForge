"""
Users CRUD — admin only.

GET    /api/users          → list all users
POST   /api/users          → create user
PUT    /api/users/{id}     → update user
DELETE /api/users/{id}     → delete user
"""
from __future__ import annotations

import secrets
import string

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.routers.auth import require_admin, get_current_user
from backend.db.users_store import (
    list_users, create_user, update_user, delete_user,
    get_user_by_email, get_user_by_id, count_users,
)

router = APIRouter(prefix="/users", tags=["users"])


def _safe(user: dict) -> dict:
    return {k: v for k, v in user.items() if k != "password_hash"}


def generate_strong_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        # Ensure at least one of each required type
        if (any(c.islower() for c in pwd) and
            any(c.isupper() for c in pwd) and
            any(c.isdigit() for c in pwd) and
            any(c in "!@#$%^&*" for c in pwd)):
            return pwd


class CreateUserRequest(BaseModel):
    first_name: str
    last_name: str = ""
    email: str
    password: str | None = None   # None = auto-generate
    is_admin: bool = False


class UpdateUserRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    password: str | None = None
    is_admin: bool | None = None


@router.get("/generate-password")
async def gen_password(_: dict = Depends(require_admin)):
    return {"password": generate_strong_password()}


@router.get("")
async def list_all(admin: dict = Depends(require_admin)):
    users = await list_users()
    return [_safe(u) for u in users]


@router.post("")
async def create(body: CreateUserRequest, admin: dict = Depends(require_admin)):
    # Check email not already taken
    existing = await get_user_by_email(body.email)
    if existing:
        raise HTTPException(400, "Ya existe un usuario con ese email")

    # Auto-generate password if not provided
    generated_password = None
    password = body.password
    if not password:
        password = generate_strong_password()
        generated_password = password

    # First user ever is always admin
    total = await count_users()
    is_admin = body.is_admin or total == 0

    user = await create_user(
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        password=password,
        is_admin=is_admin,
    )
    result = _safe(user)
    if generated_password:
        result["generated_password"] = generated_password
    return result


@router.put("/{user_id}")
async def update(user_id: str, body: UpdateUserRequest, admin: dict = Depends(require_admin)):
    # Prevent removing admin from yourself
    if user_id == admin["id"] and body.is_admin is False:
        raise HTTPException(400, "No puedes quitarte los permisos de administrador")

    if body.email:
        existing = await get_user_by_email(body.email)
        if existing and existing["id"] != user_id:
            raise HTTPException(400, "Ya existe un usuario con ese email")

    user = await update_user(
        user_id,
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        password=body.password,
        is_admin=body.is_admin,
    )
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    return _safe(user)


@router.delete("/{user_id}")
async def delete(user_id: str, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(400, "No puedes eliminar tu propio usuario")
    total = await count_users()
    if total <= 1:
        raise HTTPException(400, "Debe existir al menos un usuario")
    await delete_user(user_id)
    return {"ok": True}
