"""
Git tools: status, diff, log, add, commit, checkout, branch, push, pull.
These run via execute_command internally but expose a clean schema so the
model doesn't have to guess git syntax or flags.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool


async def _git(args: list[str], cwd: str, timeout: int = 30) -> str:
    """Run a git command and return combined stdout+stderr."""
    cmd = ["git"] + args
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path(cwd).expanduser().resolve()),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        out = stdout.decode("utf-8", errors="replace").rstrip()
        err = stderr.decode("utf-8", errors="replace").rstrip()
        parts = []
        if out:
            parts.append(out)
        if err:
            parts.append(f"[stderr] {err}")
        result = "\n".join(parts) if parts else "(no output)"
        return f"exit {proc.returncode}\n{result}"
    except asyncio.TimeoutError:
        return f"Error: git timed out after {timeout}s"
    except FileNotFoundError:
        return "Error: git not found in PATH"
    except Exception as e:
        return f"Error: {e}"


class GitStatusTool(BaseTool):
    name = "git_status"
    description = (
        "Show the working tree status of a git repository: staged, unstaged, "
        "and untracked files. Use before any commit to know what changed."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the git repository root"},
        },
        "required": ["path"],
    }

    async def run(self, path: str, **_: Any) -> str:
        return await _git(["status", "--short", "--branch"], path)


class GitDiffTool(BaseTool):
    name = "git_diff"
    description = (
        "Show differences between working tree and index (unstaged changes), "
        "or between commits/branches. Pass `staged=true` to see staged changes. "
        "Pass `target` to diff against a specific commit/branch (e.g. 'HEAD~1', 'main')."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the git repository root"},
            "staged": {"type": "boolean", "description": "If true, show staged (cached) diff", "default": False},
            "target": {"type": "string", "description": "Commit/branch to diff against (optional)"},
            "file": {"type": "string", "description": "Limit diff to this specific file (optional)"},
        },
        "required": ["path"],
    }

    async def run(self, path: str, staged: bool = False, target: str | None = None, file: str | None = None, **_: Any) -> str:
        args = ["diff"]
        if staged:
            args.append("--cached")
        if target:
            args.append(target)
        args += ["--", file] if file else []
        return await _git(args, path)


class GitLogTool(BaseTool):
    name = "git_log"
    description = "Show recent commit history with hashes, authors, dates, and messages."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the git repository root"},
            "n": {"type": "integer", "description": "Number of commits to show (default 10)", "default": 10},
            "oneline": {"type": "boolean", "description": "Compact one-line format", "default": True},
        },
        "required": ["path"],
    }

    async def run(self, path: str, n: int = 10, oneline: bool = True, **_: Any) -> str:
        args = ["log", f"-{n}"]
        if oneline:
            args.append("--oneline")
        else:
            args += ["--pretty=format:%h %ad %an: %s", "--date=short"]
        return await _git(args, path)


class GitAddTool(BaseTool):
    name = "git_add"
    description = (
        "Stage files for the next commit. Pass a list of file paths, or '.' to stage everything."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the git repository root"},
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Files to stage. Use ['.'] to stage all changes.",
            },
        },
        "required": ["path", "files"],
    }

    async def run(self, path: str, files: list[str], **_: Any) -> str:
        return await _git(["add", "--"] + files, path)


class GitCommitTool(BaseTool):
    name = "git_commit"
    description = "Create a commit with the staged changes. Requires git_add first."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the git repository root"},
            "message": {"type": "string", "description": "Commit message"},
        },
        "required": ["path", "message"],
    }

    async def run(self, path: str, message: str, **_: Any) -> str:
        return await _git(["commit", "-m", message], path)


class GitCheckoutTool(BaseTool):
    name = "git_checkout"
    description = (
        "Switch to a branch or create a new one. "
        "Pass `create=true` to create the branch before switching."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the git repository root"},
            "branch": {"type": "string", "description": "Branch name to switch to or create"},
            "create": {"type": "boolean", "description": "Create the branch if it doesn't exist", "default": False},
        },
        "required": ["path", "branch"],
    }

    async def run(self, path: str, branch: str, create: bool = False, **_: Any) -> str:
        args = ["checkout", "-b", branch] if create else ["checkout", branch]
        return await _git(args, path)


class GitBranchTool(BaseTool):
    name = "git_branch"
    description = "List local branches (and mark the current one)."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the git repository root"},
        },
        "required": ["path"],
    }

    async def run(self, path: str, **_: Any) -> str:
        return await _git(["branch", "-v"], path)


class GitPullTool(BaseTool):
    name = "git_pull"
    description = "Fetch and merge changes from the remote repository."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the git repository root"},
            "remote": {"type": "string", "description": "Remote name (default: origin)", "default": "origin"},
            "branch": {"type": "string", "description": "Branch to pull (default: current branch)"},
        },
        "required": ["path"],
    }

    async def run(self, path: str, remote: str = "origin", branch: str | None = None, **_: Any) -> str:
        args = ["pull", remote]
        if branch:
            args.append(branch)
        return await _git(args, path, timeout=60)


class GitPushTool(BaseTool):
    name = "git_push"
    description = "Push local commits to the remote repository."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the git repository root"},
            "remote": {"type": "string", "description": "Remote name (default: origin)", "default": "origin"},
            "branch": {"type": "string", "description": "Branch to push (default: current branch)"},
            "set_upstream": {"type": "boolean", "description": "Set upstream tracking (-u flag)", "default": False},
        },
        "required": ["path"],
    }

    async def run(self, path: str, remote: str = "origin", branch: str | None = None, set_upstream: bool = False, **_: Any) -> str:
        args = ["push"]
        if set_upstream:
            args.append("-u")
        args.append(remote)
        if branch:
            args.append(branch)
        return await _git(args, path, timeout=60)


GIT_TOOLS: list[BaseTool] = [
    GitStatusTool(),
    GitDiffTool(),
    GitLogTool(),
    GitAddTool(),
    GitCommitTool(),
    GitCheckoutTool(),
    GitBranchTool(),
    GitPullTool(),
    GitPushTool(),
]
