"""
Auth router — login, me, logout, 2FA TOTP.

POST /api/auth/login              → { token, user } or { totp_required, temp_token }
GET  /api/auth/me                 → { user }
GET  /api/auth/status             → { required, setup, reason }
POST /api/auth/setup              → create first admin user

2FA endpoints (require valid JWT):
  GET  /api/auth/totp/setup       → { secret, qr_uri, qr_image_b64 }
  POST /api/auth/totp/confirm     → { ok } — verifies first code and activates 2FA
  POST /api/auth/totp/disable     → { ok } — verifies current code and removes 2FA

Exchange endpoint (no auth needed — only accepts totp_challenge tokens):
  POST /api/auth/totp/verify      → { token, user }
"""
from __future__ import annotations

import asyncio
import base64
import io

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from backend.auth import (
    create_access_token,
    create_password_reset_token,
    create_totp_challenge_token,
    decode_token,
    decode_password_reset_token,
    decode_totp_challenge_token,
)
from backend.config import get_smtp_config
from backend.db.users_store import (
    count_users,
    create_user,
    disable_totp,
    enable_totp,
    get_user_by_email,
    get_user_by_id,
    set_totp_secret,
    update_password,
    verify_password,
)
from backend.email import send_password_reset_email

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe(user: dict) -> dict:
    """Strip sensitive fields before returning to client."""
    return {k: v for k, v in user.items() if k not in ("password_hash", "totp_secret")}


def _totp_valid(secret: str, code: str) -> bool:
    try:
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)
    except Exception:
        return False


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


# ── Login ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str
    remember: bool = False


@router.post("/login")
async def login(body: LoginRequest):
    user = await get_user_by_email(body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Email o contraseña incorrectos")

    # 2FA is active → issue a short-lived challenge token instead of a full JWT
    if user.get("totp_enabled") and user.get("totp_secret"):
        temp_token = create_totp_challenge_token(user["id"], remember=body.remember)
        return {"totp_required": True, "temp_token": temp_token}

    token = create_access_token(user["id"], remember=body.remember)
    return {"token": token, "user": _safe(user)}


# ── Me ────────────────────────────────────────────────────────────────────────

@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return _safe(user)


# ── Setup first user ──────────────────────────────────────────────────────────

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
    token = create_access_token(user["id"], remember=False)
    return {"token": token, "user": _safe(user)}


# ── Auth status ───────────────────────────────────────────────────────────────

@router.get("/status")
async def auth_status():
    """Public endpoint — tells the frontend whether login is required."""
    import os
    api_key = os.getenv("API_KEY", "").strip()
    total = await count_users()
    if total == 0:
        return {"required": True, "setup": True, "reason": "no_users"}
    if api_key:
        return {"required": True, "setup": False, "reason": "api_key"}
    return {"required": True, "setup": False, "reason": "users"}


# ── Password reset ───────────────────────────────────────────────────────────

class PasswordResetRequestRequest(BaseModel):
    email: str
    reset_url_base: str


class PasswordResetConfirmRequest(BaseModel):
    token: str
    password: str


@router.post("/password-reset/request")
async def request_password_reset(body: PasswordResetRequestRequest):
    smtp = get_smtp_config()
    if not smtp.enabled or not smtp.host:
        raise HTTPException(503, "El reseteo por correo no está configurado")

    user = await get_user_by_email(body.email)
    if user:
        token = create_password_reset_token(user["id"])
        base = body.reset_url_base.strip().rstrip("/") or "http://localhost:5173"
        separator = "&" if "?" in base else "?"
        reset_url = f"{base}{separator}reset_token={token}"
        await asyncio.to_thread(send_password_reset_email, smtp, user["email"], reset_url)

    return {
        "ok": True,
        "message": "Si existe una cuenta con ese email, recibirás un enlace para restablecer la contraseña.",
    }


@router.post("/password-reset/confirm")
async def confirm_password_reset(body: PasswordResetConfirmRequest):
    if len(body.password) < 8:
        raise HTTPException(400, "La nueva contraseña debe tener al menos 8 caracteres")

    user_id = decode_password_reset_token(body.token)
    if not user_id:
        raise HTTPException(400, "El enlace de restablecimiento es inválido o ha expirado")

    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(400, "Usuario no encontrado")

    await update_password(user_id, body.password)
    return {"ok": True, "message": "Contraseña actualizada correctamente"}


# ── TOTP: verify challenge (public) ──────────────────────────────────────────

class TotpVerifyRequest(BaseModel):
    temp_token: str
    code: str


@router.post("/totp/verify")
async def totp_verify(body: TotpVerifyRequest):
    """Exchange a TOTP challenge token + valid 6-digit code for a full JWT."""
    data = decode_totp_challenge_token(body.temp_token)
    if not data:
        raise HTTPException(401, "Token de desafío inválido o expirado")

    user = await get_user_by_id(data["user_id"])
    if not user or not user.get("totp_secret"):
        raise HTTPException(401, "Usuario no encontrado o 2FA no configurado")

    if not _totp_valid(user["totp_secret"], body.code.strip()):
        raise HTTPException(401, "Código TOTP incorrecto")

    token = create_access_token(user["id"], remember=data.get("remember", False))
    return {"token": token, "user": _safe(user)}


# ── TOTP: setup — generate secret + QR (requires auth) ───────────────────────

@router.get("/totp/setup")
async def totp_setup(user: dict = Depends(get_current_user)):
    """Generate a new TOTP secret for the user and return the QR code."""
    secret = pyotp.random_base32()
    await set_totp_secret(user["id"], secret)

    totp = pyotp.TOTP(secret)
    label = user["email"]
    issuer = "LocalForge"
    uri = totp.provisioning_uri(name=label, issuer_name=issuer)

    # Build QR as a base64 PNG
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    return {"secret": secret, "qr_uri": uri, "qr_image_b64": qr_b64}


# ── TOTP: confirm — verify first code and activate 2FA ───────────────────────

class TotpConfirmRequest(BaseModel):
    code: str


@router.post("/totp/confirm")
async def totp_confirm(body: TotpConfirmRequest, user: dict = Depends(get_current_user)):
    """Verify the first TOTP code from the authenticator app and enable 2FA."""
    if not user.get("totp_secret"):
        raise HTTPException(400, "Primero genera un secreto con GET /auth/totp/setup")

    if not _totp_valid(user["totp_secret"], body.code.strip()):
        raise HTTPException(400, "Código TOTP incorrecto. Verifica la hora del dispositivo.")

    await enable_totp(user["id"])
    return {"ok": True, "message": "Autenticación de dos factores activada"}


# ── TOTP: disable ─────────────────────────────────────────────────────────────

class TotpDisableRequest(BaseModel):
    code: str


@router.post("/totp/disable")
async def totp_disable(body: TotpDisableRequest, user: dict = Depends(get_current_user)):
    """Disable 2FA after verifying the current TOTP code."""
    if not user.get("totp_enabled") or not user.get("totp_secret"):
        raise HTTPException(400, "El 2FA no está activado en esta cuenta")

    if not _totp_valid(user["totp_secret"], body.code.strip()):
        raise HTTPException(400, "Código TOTP incorrecto")

    await disable_totp(user["id"])
    return {"ok": True, "message": "Autenticación de dos factores desactivada"}
