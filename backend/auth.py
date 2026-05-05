"""
JWT authentication helpers.

Tokens are signed with HS256 using SECRET_KEY from .env.
If SECRET_KEY is not set, a random one is generated at startup (sessions won't
survive restarts — fine for dev, not for prod).
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


def create_access_token(user_id: str, remember: bool = False) -> str:
    expire = datetime.utcnow() + (
        timedelta(days=REMEMBER_TOKEN_EXPIRE_DAYS)
        if remember
        else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return jwt.encode(
        {"sub": user_id, "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> str | None:
    """Return user_id from token, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None
