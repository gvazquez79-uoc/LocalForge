"""
Terminal tool: execute shell commands with timeout and safety checks.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from backend.config import get_config
from backend.tools.base import BaseTool

# A build log can be tens of thousands of lines. Unclamped it evicts everything
# useful from the context in one tool result.
MAX_OUTPUT_CHARS = 20_000


def _clamp(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Keep the head and the tail — errors live at both ends of a build log.

    Truncating only the head throws away exactly what matters in a vite/webpack
    build, where the banner comes first and the errors come last.
    """
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-(limit // 2):]
    dropped = len(text) - len(head) - len(tail)
    return f"{head}\n\n… [recortadas {dropped} caracteres del centro] …\n\n{tail}"


def _kill_tree_sync(pid: int) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
        else:
            os.killpg(os.getpgid(pid), 9)
    except Exception:
        pass


async def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the process AND its children, without blocking the event loop.

    proc.kill() only signals the shell we spawned. On Windows an `npm run dev`
    leaves node alive holding the port, so the next verification run fails for a
    reason that has nothing to do with the code.

    taskkill is synchronous and can take seconds; running it inline stalled every
    other conversation on the server, so it goes to a thread.
    """
    if proc.returncode is not None:
        return
    try:
        await asyncio.to_thread(_kill_tree_sync, proc.pid)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def _default_working_dir() -> str:
    """The conversation's working directory, not the user's home.

    The schema default used to be "~", so any call that omitted working_dir ran
    in C:\\Users\\<user> — `pytest`, `npm test` and `git status` all silently
    operated on the wrong place.
    """
    try:
        from backend.tools.filesystem import _conv_working_dir
        wd = _conv_working_dir.get()
        if wd:
            return str(wd)
    except Exception:
        pass
    return "~"


class ExecuteCommandTool(BaseTool):
    name = "execute_command"
    description = (
        "Execute a shell command and return its output (stdout + stderr). "
        "Runs in the conversation's working directory unless you pass working_dir. "
        "Use for running tests, build tools, installing packages, scripts."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to execute"},
            "working_dir": {
                "type": "string",
                "description": "Working directory (default: the conversation's working directory)",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: from config)",
            },
        },
        "required": ["command"],
    }

    async def run(self, command: str, working_dir: str | None = None,
                  timeout: int | None = None, **_: Any) -> str:
        cfg = get_config().tools.terminal
        timeout = timeout or cfg.timeout_seconds

        # Safety: check blocked patterns
        for blocked in cfg.blocked_patterns:
            if blocked.lower() in command.lower():
                return f"Error: command blocked for safety: contains '{blocked}'"

        cwd = Path(working_dir or _default_working_dir()).expanduser().resolve()
        if not cwd.exists():
            return f"Error: working directory not found: {cwd}"

        popen_kwargs: dict = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        proc = None
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                **popen_kwargs,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

            output_parts = []
            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace").rstrip())
            if stderr:
                output_parts.append(f"[stderr]\n{stderr.decode('utf-8', errors='replace').rstrip()}")

            exit_code = proc.returncode
            result = "\n".join(output_parts) if output_parts else "(no output)"
            return f"Exit code: {exit_code}\n[cwd: {cwd}]\n{_clamp(result)}"

        except asyncio.TimeoutError:
            # Leaving the process alive kept ports busy and made the NEXT command
            # fail for an unrelated reason.
            return (
                f"Error: el comando ha excedido el tiempo límite de {timeout}s y se ha "
                f"terminado (junto con sus procesos hijos).\n"
                "Si era un servidor o un proceso de larga duración, arráncalo en segundo "
                "plano en vez de esperar a que termine."
            )
        except Exception as e:
            return f"Error executing command: {e}"
        finally:
            # finally, not except: when the user presses Stop the frontend aborts
            # the fetch, Starlette cancels the task and CancelledError is raised —
            # and CancelledError inherits from BaseException, so `except Exception`
            # never saw it and the process was left running.
            if proc is not None and proc.returncode is None:
                await _kill_tree(proc)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except Exception:
                    pass


TERMINAL_TOOLS: list[BaseTool] = [ExecuteCommandTool()]
