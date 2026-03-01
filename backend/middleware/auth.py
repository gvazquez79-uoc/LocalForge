"""
Simple API-key authentication middleware.

Configuration:
  Set API_KEY=<your-secret> in .env (or environment).
  If API_KEY is empty / not set → auth is disabled (localhost dev mode).

Clients must send the key as:
  Authorization: Bearer <key>
  OR
  X-API-Key: <key>

Public endpoints (always allowed regardless of key):
  GET /api/health
"""
from __future__ import annotations

import os

from fastapi import Request
from fastapi.responses import JSONResponse

# Paths that don't require auth
_PUBLIC_PATHS = {"/api/health"}


async def api_key_middleware(request: Request, call_next):
    api_key = os.getenv("API_KEY", "").strip()

    # If no key configured → open access (dev / trusted network)
    if not api_key:
        return await call_next(request)

    # Always allow public paths
    if request.url.path in _PUBLIC_PATHS:
        return await call_next(request)

    # Extract key from headers
    auth_header = request.headers.get("Authorization", "")
    x_api_key   = request.headers.get("X-API-Key", "")

    if auth_header.startswith("Bearer "):
        provided = auth_header[7:].strip()
    elif x_api_key:
        provided = x_api_key.strip()
    else:
        provided = ""

    if provided != api_key:
        return JSONResponse(
            {"error": "Unauthorized", "detail": "API key required"},
            status_code=401,
        )

    return await call_next(request)
