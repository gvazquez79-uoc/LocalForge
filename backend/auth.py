"""
JWT authentication helpers.

Tokens are signed with HS256 using SECRET_KEY from .env.
If SECRET_KEY is not set, a random one is generated at startup (sessions won't
survive restarts — fine for dev, not for prod).

Temp tokens (type="totp_challenge") are issued when a user has 2FA enabled.
They are short-lived (5 minutes) and can ONLY be exchanged at /auth/totp/verify.
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta

from jose import JWTError, jwt

# Load or generate secret key
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
ALGORITHM  = "HS256"

ACCESS_TOKEN_EXPIRE_MINUTES  = 60 * 8    # 8 hours
REMEMBER_TOKEN_EXPIRE_DAYS   = 30        # 30 days if "remember me"
TOTP_CHALLENGE_EXPIRE_MINUTES = 5        # 5 minutes for 2FA challenge
PASSWORD_RESET_EXPIRE_MINUTES = 30       # 30 minutes for password reset links


def create_access_token(user_id: str, remember: bool = False) -> str:
    expire = datetime.utcnow() + (
        timedelta(days=REMEMBER_TOKEN_EXPIRE_DAYS)
        if remember
        else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "access"},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def create_totp_challenge_token(user_id: str, remember: bool = False) -> str:
    """Short-lived token issued when password is correct but 2FA code is still pending."""
    expire = datetime.utcnow() + timedelta(minutes=TOTP_CHALLENGE_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "totp_challenge", "remember": remember},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def create_password_reset_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=PASSWORD_RESET_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "password_reset"},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> str | None:
    """Return user_id from a full access token, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        token_type = payload.get("type")
        if token_type and token_type != "access":
            return None  # challenge tokens cannot be used as access tokens
        return payload.get("sub")
    except JWTError:
        return None


def decode_totp_challenge_token(token: str) -> dict | None:
    """Return {user_id, remember} from a TOTP challenge token, or None."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "totp_challenge":
            return None
        return {"user_id": payload.get("sub"), "remember": payload.get("remember", False)}
    except JWTError:
        return None


def decode_password_reset_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "password_reset":
            return None
        return payload.get("sub")
    except JWTError:
        return None
