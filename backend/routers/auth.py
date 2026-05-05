"""
Auth router — login, me, logout.

POST /api/auth/login   → { token, user }
GET  /api/auth/me      → { user }
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from backend.auth import create_access_token, decode_token
from backend.db.users_store import get_user_by_email, get_user_by_id, verify_password, count_users, create_user

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    email: str
    password: str
    remember: bool = False


def _safe(user: dict) -> dict:
    """Strip password hash before returning to client."""
    return {k: v for k, v in user.items() if k != "password_hash"}


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    if not creds:
        raise HTTPException(401, "Token requerido")
    user_id = decode_token(creds.credentials)
    if not user_id:
        raise HTTPException(401, "Token inválido o expirado")
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(401, "Usuario no encontrado")
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(403, "Se requieren permisos de administrador")
    return user


@router.post("/login")
async def login(body: LoginRequest):
    user = await get_user_by_email(body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Email o contraseña incorrectos")
    token = create_access_token(user["id"], remember=body.remember)
    return {"token": token, "user": _safe(user)}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return _safe(user)


class SetupRequest(BaseModel):
    first_name: str
    last_name: str = ""
    email: str
    password: str


@router.post("/setup")
async def setup_first_user(body: SetupRequest):
    """Create the first admin user — only works when no users exist."""
    total = await count_users()
    if total > 0:
        raise HTTPException(403, "Ya existe al menos un usuario. Usa el panel de administración.")
    user = await create_user(
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        password=body.password,
        is_admin=True,
    )
    safe = {k: v for k, v in user.items() if k != "password_hash"}
    token = create_access_token(user["id"], remember=False)
    return {"token": token, "user": safe}


@router.get("/status")
async def auth_status():
    """Public endpoint — tells the frontend whether login is required."""
    import os
    api_key = os.getenv("API_KEY", "").strip()
    total = await count_users()
    if total == 0:
        # No users yet — need to create first admin (setup mode)
        return {"required": True, "setup": True, "reason": "no_users"}
    if api_key:
        return {"required": True, "setup": False, "reason": "api_key"}
    return {"required": True, "setup": False, "reason": "users"}
