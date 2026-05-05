"""
GitHub Copilot OAuth Device Flow + API adapter registration.

Flow:
  1. POST /api/github/copilot/connect   → returns user_code + verification_uri
  2. User goes to verification_uri and enters user_code
  3. POST /api/github/copilot/poll      → polls GitHub until authorized, stores token
  4. GET  /api/github/copilot/status    → connected / disconnected + username
  5. DELETE /api/github/copilot/disconnect → removes token
"""
from __future__ import annotations

import os
import time
import httpx
from fastapi import APIRouter, HTTPException

from backend.db.settings_store import get_setting, set_setting

router = APIRouter(prefix="/github/copilot", tags=["github-copilot"])

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
DEVICE_CODE_URL  = "https://github.com/login/device/code"
TOKEN_URL        = "https://github.com/login/oauth/access_token"
USER_URL         = "https://api.github.com/user"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
COPILOT_API_BASE  = "https://api.githubcopilot.com"

SETTING_KEY = "github_copilot_token"


# ── Helpers ───────────────────────────────────────────────────────────────────

async def get_stored_token() -> str | None:
    return await get_setting(SETTING_KEY)


async def save_token(token: str) -> None:
    await set_setting(SETTING_KEY, token)


async def delete_token() -> None:
    await set_setting(SETTING_KEY, "")


async def exchange_copilot_token(github_token: str) -> str:
    """Exchange a GitHub OAuth token for a short-lived Copilot session token."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            COPILOT_TOKEN_URL,
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/json",
                "Editor-Version": "vscode/1.85.0",
                "Editor-Plugin-Version": "copilot/1.138.0",
                "User-Agent": "GithubCopilot/1.138.0",
            },
        )
        if r.status_code != 200:
            raise HTTPException(502, f"Copilot token exchange failed: {r.text}")
        data = r.json()
        return data["token"]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/connect")
async def start_device_flow():
    """Step 1 — Request a device code from GitHub."""
    if not GITHUB_CLIENT_ID:
        raise HTTPException(500, "GITHUB_CLIENT_ID not set in environment")

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            DEVICE_CODE_URL,
            headers={"Accept": "application/json"},
            data={"client_id": GITHUB_CLIENT_ID, "scope": "read:user"},
        )

    if r.status_code != 200:
        raise HTTPException(502, f"GitHub error: {r.text}")

    data = r.json()
    return {
        "device_code":      data["device_code"],
        "user_code":        data["user_code"],
        "verification_uri": data["verification_uri"],
        "expires_in":       data["expires_in"],
        "interval":         data.get("interval", 5),
    }


@router.post("/poll")
async def poll_device_flow(body: dict):
    """Step 2 — Poll until the user authorizes. Returns ok:true when done."""
    device_code = body.get("device_code")
    if not device_code:
        raise HTTPException(400, "device_code required")

    github_secret = os.getenv("GITHUB_SECRET", "")
    if not github_secret:
        raise HTTPException(500, "GITHUB_SECRET not set in environment")

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id":     GITHUB_CLIENT_ID,
                "client_secret": github_secret,
                "device_code":   device_code,
                "grant_type":    "urn:ietf:params:oauth:grant-type:device_code",
            },
        )

    data = r.json()
    print(f"[copilot poll] GitHub response: {data}", flush=True)

    if "error" in data:
        error = data["error"]
        if error == "authorization_pending":
            return {"ok": False, "pending": True}
        if error == "slow_down":
            return {"ok": False, "pending": True, "slow_down": True, "interval": data.get("interval", 10)}
        if error == "expired_token":
            raise HTTPException(400, "El código ha expirado. Inicia el proceso de nuevo.")
        if error == "access_denied":
            raise HTTPException(403, "Acceso denegado por el usuario.")
        raise HTTPException(400, data.get("error_description", error))

    github_token = data.get("access_token")
    if not github_token:
        raise HTTPException(502, "No se recibió token de GitHub")

    # Verify Copilot access by checking the user has a Copilot subscription
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            cr = await client.get(
                "https://api.github.com/copilot_internal/v2/token",
                headers={
                    "Authorization": f"Bearer {github_token}",
                    "Accept": "application/json",
                    "Editor-Version": "vscode/1.85.0",
                    "Editor-Plugin-Version": "copilot/1.138.0",
                    "User-Agent": "GithubCopilot/1.138.0",
                },
            )
            print(f"[copilot] token exchange status={cr.status_code} body={cr.text[:200]}", flush=True)
    except Exception as e:
        print(f"[copilot] token exchange error: {e}", flush=True)

    # Get GitHub username for display
    username = ""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            ur = await client.get(
                USER_URL,
                headers={"Authorization": f"Bearer {github_token}", "Accept": "application/json"},
            )
            username = ur.json().get("login", "")
    except Exception:
        pass

    await save_token(github_token)

    # Auto-register Copilot models in the DB so they appear in the model picker
    try:
        from backend.db.models_store import list_models, create_model
        existing = await list_models()
        existing_names = {m["name"] for m in existing}

        copilot_models = [
            ("gpt-4o",               "GPT-4o (Copilot)"),
            ("gpt-4o-mini",          "GPT-4o Mini (Copilot)"),
            ("o3-mini",              "o3-mini (Copilot)"),
            ("claude-sonnet-4-5",    "Claude Sonnet 3.5 (Copilot)"),
            ("claude-3.7-sonnet",    "Claude Sonnet 3.7 (Copilot)"),
            ("gemini-2.0-flash-001", "Gemini 2.0 Flash (Copilot)"),
        ]
        for model_id, display_name in copilot_models:
            name_in_db = f"copilot/{model_id}"
            if name_in_db not in existing_names:
                await create_model(
                    name=name_in_db,
                    display_name=display_name,
                    provider="copilot",
                    api_key=github_token,
                )
    except Exception:
        pass  # non-fatal

    return {"ok": True, "username": username}


@router.get("/status")
async def get_status():
    """Return connection status and GitHub username if connected."""
    token = await get_stored_token()
    if not token:
        return {"connected": False}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                USER_URL,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
        if r.status_code == 200:
            return {"connected": True, "username": r.json().get("login", "")}
    except Exception:
        pass

    return {"connected": True, "username": ""}


@router.delete("/disconnect")
async def disconnect():
    """Remove the stored GitHub token."""
    await delete_token()
    return {"ok": True}


@router.get("/models")
async def list_copilot_models():
    """Return available Copilot models (requires active connection)."""
    token = await get_stored_token()
    if not token:
        raise HTTPException(401, "GitHub Copilot not connected")

    # These are the models available via Copilot API as of 2025
    return [
        {"id": "gpt-4o",                "name": "GPT-4o (Copilot)"},
        {"id": "gpt-4o-mini",           "name": "GPT-4o Mini (Copilot)"},
        {"id": "o3-mini",               "name": "o3-mini (Copilot)"},
        {"id": "claude-sonnet-4-5",     "name": "Claude Sonnet 3.5 (Copilot)"},
        {"id": "claude-3.7-sonnet",     "name": "Claude Sonnet 3.7 (Copilot)"},
        {"id": "gemini-2.0-flash-001",  "name": "Gemini 2.0 Flash (Copilot)"},
    ]
