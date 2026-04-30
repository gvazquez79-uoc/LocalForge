"""
Auto-update router — checks GitHub for new commits and applies updates.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

# Project root (two levels up from this file: backend/routers/update.py → root)
PROJECT_ROOT = Path(__file__).parent.parent.parent


def _git(*args: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


@router.get("/update/check")
async def check_update():
    """
    Fetch remote and compare HEAD with origin/<current-branch>.
    Returns whether an update is available and the list of new commits.
    """
    try:
        # Detect current branch
        _, current_branch, _ = await asyncio.to_thread(_git, "rev-parse", "--abbrev-ref", "HEAD")
        if not current_branch or current_branch == "HEAD":
            current_branch = "main"  # detached HEAD fallback

        # Fetch latest refs for this branch
        code, _, err = await asyncio.to_thread(_git, "fetch", "origin", current_branch, "--quiet")
        if code != 0:
            return {"error": f"git fetch failed: {err}", "update_available": False}

        # Current local commit
        _, local_hash, _ = await asyncio.to_thread(_git, "rev-parse", "HEAD")
        # Latest remote commit for this branch
        _, remote_hash, _ = await asyncio.to_thread(_git, "rev-parse", f"origin/{current_branch}")

        if local_hash == remote_hash:
            return {
                "update_available": False,
                "local_commit": local_hash[:8],
                "remote_commit": remote_hash[:8],
                "branch": current_branch,
                "commits": [],
            }

        # Get list of new commits (remote but not local)
        _, log, _ = await asyncio.to_thread(
            _git,
            "log",
            f"{local_hash}..origin/{current_branch}",
            "--oneline",
            "--no-merges",
        )
        commits = [line.strip() for line in log.splitlines() if line.strip()]

        return {
            "update_available": True,
            "local_commit": local_hash[:8],
            "remote_commit": remote_hash[:8],
            "branch": current_branch,
            "commits": commits,
        }

    except FileNotFoundError:
        return {"error": "git not found in PATH", "update_available": False}
    except Exception as e:
        return {"error": str(e), "update_available": False}


@router.post("/update/apply")
async def apply_update():
    """
    Pull latest changes from origin/<current-branch> and restart the backend.
    """
    try:
        _, current_branch, _ = await asyncio.to_thread(_git, "rev-parse", "--abbrev-ref", "HEAD")
        if not current_branch or current_branch == "HEAD":
            current_branch = "main"

        code, out, err = await asyncio.to_thread(_git, "pull", "origin", current_branch, "--ff-only")
        if code != 0:
            return {"ok": False, "error": f"git pull failed: {err or out}"}

        # Touch main.py so uvicorn --reload picks up the change
        import asyncio as _asyncio

        async def _restart():
            await _asyncio.sleep(0.5)
            from backend.main import __file__ as main_file
            Path(main_file).touch()

        asyncio.create_task(_restart())

        return {
            "ok": True,
            "output": out or "Already up to date.",
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}
