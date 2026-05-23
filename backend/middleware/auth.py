"""
Authentication middleware.

Supports two modes:
  1. JWT Bearer token  — frontend users (login via /api/auth/login)
  2. API key (legacy)  — Telegram bot and external integrations (API_KEY in .env)

If neither API_KEY nor any users exist → open access (dev mode).

Public endpoints (no auth required):
  GET  /api/health
  POST /api/auth/login
  GET  /api/auth/me     (handled by its own JWT dep)
"""
from __future__ import annotations

import os

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.auth import decode_token

_PUBLIC_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/api/auth/status",
    "/api/auth/setup",
}


def _cors_headers(request: Request) -> dict:
    """Return CORS headers mirroring the request Origin (if present)."""
    origin = request.headers.get("origin", "")
    if not origin:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
    }


async def auth_middleware(request: Request, call_next):
    # Always allow CORS preflight
    if request.method == "OPTIONS":
        return await call_next(request)

    # Always allow public paths
    if request.url.path in _PUBLIC_PATHS:
        return await call_next(request)

    # Extract token/key from headers or query params
    auth_header = request.headers.get("Authorization", "")
    x_api_key   = request.headers.get("X-API-Key", "")
    q_api_key   = request.query_params.get("api_key", "")

    provided = ""
    if auth_header.startswith("Bearer "):
        provided = auth_header[7:].strip()
    elif x_api_key:
        provided = x_api_key.strip()
    elif q_api_key:
        provided = q_api_key.strip()

    if not provided:
        # Check if auth is even required (async-safe version)
        if await _is_open_mode_async():
            return await call_next(request)
        return JSONResponse(
            {"error": "Unauthorized", "detail": "Token requerido"},
            status_code=401,
            headers=_cors_headers(request),
        )

    # Try JWT first
    user_id = decode_token(provided)
    if user_id:
        request.state.user_id = user_id
        return await call_next(request)

    # Fall back to legacy API key (for Telegram bot and integrations)
    api_key = os.getenv("API_KEY", "").strip()
    if api_key and provided == api_key:
        request.state.user_id = None  # system/bot request
        return await call_next(request)

    return JSONResponse(
        {"error": "Unauthorized", "detail": "Token inválido"},
        status_code=401,
        headers=_cors_headers(request),
    )


async def _is_open_mode_async() -> bool:
    """Return True if no auth is configured (dev/open mode)."""
    api_key = os.getenv("API_KEY", "").strip()
    if api_key:
        return False
    try:
        from backend.db.users_store import count_users
        count = await count_users()
        return count == 0
    except Exception:
        return True
