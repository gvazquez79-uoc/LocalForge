"""
Terminal tool: execute shell commands with timeout and safety checks.
"""
from __future__ import annotations

import asyncio
import shlex
from typing import Any

from backend.config import get_config
from backend.tools.base import BaseTool


class ExecuteCommandTool(BaseTool):
    name = "execute_command"
    description = (
        "Execute a shell command and return its output (stdout + stderr). "
        "Commands run in the specified working directory. "
        "Use for running scripts, build tools, git commands, etc."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to execute"},
            "working_dir": {
                "type": "string",
                "description": "Working directory for the command (default: home directory)",
                "default": "~",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: from config)",
            },
        },
        "required": ["command"],
    }

    async def run(self, command: str, working_dir: str = "~", timeout: int | None = None, **_: Any) -> str:
        cfg = get_config().tools.terminal
        timeout = timeout or cfg.timeout_seconds

        # Safety: check blocked patterns
        for blocked in cfg.blocked_patterns:
            if blocked.lower() in command.lower():
                return f"Error: command blocked for safety: contains '{blocked}'"

        from pathlib import Path
        cwd = Path(working_dir).expanduser().resolve()
        if not cwd.exists():
            return f"Error: working directory not found: {cwd}"

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

            output_parts = []
            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace").rstrip())
            if stderr:
                output_parts.append(f"[stderr]\n{stderr.decode('utf-8', errors='replace').rstrip()}")

            exit_code = proc.returncode
            result = "\n".join(output_parts) if output_parts else "(no output)"
            return f"Exit code: {exit_code}\n{result}"

        except asyncio.TimeoutError:
            return f"Error: command timed out after {timeout} seconds"
        except Exception as e:
            return f"Error executing command: {e}"


TERMINAL_TOOLS: list[BaseTool] = [ExecuteCommandTool()]
