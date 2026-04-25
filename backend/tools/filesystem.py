"""
Filesystem tools: read, write, list, search files.
Respects allowed_paths from config, plus an optional per-conversation
working_directory injected via contextvars (set by the agent loop).
"""
from __future__ import annotations

import glob as glob_module
import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from backend.config import get_config
from backend.tools.base import BaseTool

# Per-async-task working directory (set by loop.py when a conversation has one).
# Using ContextVar ensures concurrent conversations don't interfere.
_conv_working_dir: ContextVar[Path | None] = ContextVar("_conv_working_dir", default=None)


def _is_under(child: Path, parent: Path) -> bool:
    """Check if child is under parent, case-insensitively (Windows-safe)."""
    # Normalize: lowercase + unified separators
    child_str = os.path.normcase(str(child)).rstrip(os.sep + "/") + os.sep
    parent_str = os.path.normcase(str(parent)).rstrip(os.sep + "/") + os.sep
    return child_str.startswith(parent_str)


# Directories to skip when doing recursive content search
_EXCLUDED_DIRS: frozenset[str] = frozenset({
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", ".nuxt", ".svelte-kit", "target",
    ".cache", ".parcel-cache", "coverage", ".pytest_cache", ".mypy_cache",
    ".tox", ".eggs", "*.egg-info",
})


def _resolve_and_check(path: str) -> Path:
    """Resolve path and verify it's inside an allowed directory."""
    resolved = Path(path).expanduser().resolve()
    allowed = get_config().resolve_allowed_paths()
    # Per-conversation working directory takes priority
    wd = _conv_working_dir.get()
    if wd:
        allowed = [wd] + allowed
    for allowed_path in allowed:
        if _is_under(resolved, allowed_path):
            return resolved
    raise PermissionError(
        f"Access denied: '{resolved}' is outside allowed paths {[str(p) for p in allowed]}"
    )


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read the contents of a file. Returns the text content."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or ~ path to the file"},
            "encoding": {"type": "string", "description": "File encoding (default: utf-8)", "default": "utf-8"},
        },
        "required": ["path"],
    }

    async def run(self, path: str, encoding: str = "utf-8", **_: Any) -> str:
        resolved = _resolve_and_check(path)
        cfg = get_config().tools.filesystem
        max_bytes = cfg.max_file_size_mb * 1024 * 1024

        if not resolved.exists():
            return f"Error: file not found: {resolved}"
        if not resolved.is_file():
            return f"Error: not a file: {resolved}"
        if resolved.stat().st_size > max_bytes:
            return f"Error: file too large (max {cfg.max_file_size_mb} MB)"

        try:
            return resolved.read_text(encoding=encoding)
        except UnicodeDecodeError:
            return f"Error: cannot decode file as {encoding}. It may be a binary file."


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write content to a file. Creates the file if it doesn't exist."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or ~ path to the file"},
            "content": {"type": "string", "description": "Content to write"},
            "mode": {
                "type": "string",
                "enum": ["overwrite", "append"],
                "description": "Write mode (default: overwrite)",
                "default": "overwrite",
            },
        },
        "required": ["path", "content"],
    }

    async def run(self, path: str, content: str, mode: str = "overwrite", **_: Any) -> str:
        resolved = _resolve_and_check(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append":
            with open(resolved, "a", encoding="utf-8") as f:
                f.write(content)
        else:
            resolved.write_text(content, encoding="utf-8")
        action = "appended to" if mode == "append" else "written to"
        return f"Success: {len(content)} characters {action} {resolved}"


class ListDirectoryTool(BaseTool):
    name = "list_directory"
    description = "List the contents of a directory with file sizes and types."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or ~ path to the directory"},
            "show_hidden": {"type": "boolean", "description": "Show hidden files (default: false)", "default": False},
        },
        "required": ["path"],
    }

    async def run(self, path: str, show_hidden: bool = False, **_: Any) -> str:
        resolved = _resolve_and_check(path)

        if not resolved.exists():
            return f"Error: directory not found: {resolved}"
        if not resolved.is_dir():
            return f"Error: not a directory: {resolved}"

        entries = []
        for entry in sorted(resolved.iterdir()):
            if not show_hidden and entry.name.startswith("."):
                continue
            if entry.is_dir():
                entries.append(f"[DIR]  {entry.name}/")
            else:
                size = entry.stat().st_size
                size_str = f"{size:,} bytes" if size < 1024 else f"{size/1024:.1f} KB"
                entries.append(f"[FILE] {entry.name} ({size_str})")

        if not entries:
            return f"Empty directory: {resolved}"
        return f"Contents of {resolved}:\n" + "\n".join(entries)


class SearchFilesTool(BaseTool):
    name = "search_files"
    description = "Search for files matching a glob pattern, or grep for text content within files."
    parameters = {
        "type": "object",
        "properties": {
            "directory": {"type": "string", "description": "Directory to search in"},
            "pattern": {"type": "string", "description": "Glob pattern (e.g. '**/*.py') or text to search"},
            "search_content": {
                "type": "boolean",
                "description": "If true, search file contents for the pattern (grep mode). Default: false (glob mode).",
                "default": False,
            },
            "max_results": {"type": "integer", "description": "Maximum number of results (default: 20)", "default": 20},
        },
        "required": ["directory", "pattern"],
    }

    async def run(
        self,
        directory: str,
        pattern: str,
        search_content: bool = False,
        max_results: int = 20,
        **_: Any,
    ) -> str:
        resolved_dir = _resolve_and_check(directory)

        if not search_content:
            # Glob mode
            matches = list(resolved_dir.glob(pattern))[:max_results]
            if not matches:
                return f"No files found matching '{pattern}' in {resolved_dir}"
            return f"Found {len(matches)} file(s):\n" + "\n".join(str(m) for m in matches)
        else:
            # Grep mode — search text in files, skipping noisy dirs
            results = []
            for filepath in resolved_dir.rglob("*"):
                if not filepath.is_file():
                    continue
                # Skip files inside excluded directories
                if any(part in _EXCLUDED_DIRS for part in filepath.relative_to(resolved_dir).parts):
                    continue
                try:
                    text = filepath.read_text(encoding="utf-8", errors="ignore")
                    for i, line in enumerate(text.splitlines(), 1):
                        if pattern.lower() in line.lower():
                            results.append(f"{filepath}:{i}: {line.strip()}")
                            if len(results) >= max_results:
                                break
                except Exception:
                    continue
                if len(results) >= max_results:
                    break

            if not results:
                return f"No matches for '{pattern}' in {resolved_dir}"
            return "\n".join(results)


class EditFileTool(BaseTool):
    name = "edit_file"
    description = (
        "Replace an exact string in a file with new content. "
        "Prefer this over write_file for targeted edits — it only changes the part you specify. "
        "The old_string must match exactly, including whitespace and indentation. "
        "Use read_file first if you need to see the current content."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or ~ path to the file"},
            "old_string": {"type": "string", "description": "Exact string to find (must be unique in the file)"},
            "new_string": {"type": "string", "description": "Replacement string"},
            "replace_all": {
                "type": "boolean",
                "description": "Replace all occurrences instead of just the first (default: false)",
                "default": False,
            },
        },
        "required": ["path", "old_string", "new_string"],
    }

    async def run(self, path: str, old_string: str, new_string: str, replace_all: bool = False, **_: Any) -> str:
        resolved = _resolve_and_check(path)
        if not resolved.exists():
            return f"Error: file not found: {resolved}"
        if not resolved.is_file():
            return f"Error: not a file: {resolved}"
        if not old_string:
            return "Error: old_string cannot be empty"

        content = resolved.read_text(encoding="utf-8")
        count = content.count(old_string)

        if count == 0:
            return f"Error: old_string not found in {resolved}"
        if count > 1 and not replace_all:
            return (
                f"Error: old_string appears {count} times in {resolved}. "
                "Add more surrounding context to make it unique, or set replace_all=true."
            )

        new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)
        resolved.write_text(new_content, encoding="utf-8")
        replaced = count if replace_all else 1
        return f"Success: replaced {replaced} occurrence(s) in {resolved}"


class DeleteFileTool(BaseTool):
    name = "delete_file"
    description = "Delete a file. Use with caution — this is irreversible."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or ~ path to the file to delete"},
        },
        "required": ["path"],
    }

    async def run(self, path: str, **_: Any) -> str:
        resolved = _resolve_and_check(path)
        if not resolved.exists():
            return f"Error: file not found: {resolved}"
        if resolved.is_dir():
            return f"Error: '{resolved}' is a directory. Use a directory removal tool instead."
        resolved.unlink()
        return f"Deleted: {resolved}"


# Registry of all filesystem tools
class GlobTool(BaseTool):
    name = "glob"
    description = (
        "Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.tsx', '*.json'). "
        "Returns a list of matching file paths sorted by modification time (newest first). "
        "Use this to quickly locate files by name pattern across a project."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern, e.g. '**/*.py' or 'src/**/*.ts'",
            },
            "path": {
                "type": "string",
                "description": "Root directory to search in. Defaults to working directory or first allowed path.",
            },
        },
        "required": ["pattern"],
    }

    async def run(self, pattern: str, path: str | None = None) -> str:
        import fnmatch

        # Determine root directory
        wd = _conv_working_dir.get()
        if path:
            root = _resolve_and_check(path)
        elif wd:
            root = wd
        else:
            allowed = get_config().resolve_allowed_paths()
            if not allowed:
                return "Error: no working directory or allowed path configured."
            root = allowed[0]

        # Use Python's glob with recursive support
        full_pattern = str(root / pattern) if not os.path.isabs(pattern) else pattern
        matches = glob_module.glob(full_pattern, recursive=True)

        # Filter out excluded dirs and verify permissions
        results = []
        for match in matches:
            p = Path(match)
            # Skip excluded directories anywhere in the path
            if any(part in _EXCLUDED_DIRS for part in p.parts):
                continue
            try:
                _resolve_and_check(str(p))
                results.append(p)
            except PermissionError:
                continue

        if not results:
            return f"No files found matching '{pattern}' in {root}"

        # Sort by modification time, newest first
        results.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

        lines = [str(p) for p in results[:500]]  # cap at 500
        summary = f"{len(results)} file(s) found"
        if len(results) > 500:
            summary += " (showing first 500)"
        return summary + ":\n" + "\n".join(lines)


class GrepTool(BaseTool):
    name = "grep"
    description = (
        "Search for a regex pattern in file contents. Returns matching lines with file path and line number. "
        "Use this to find where a function, variable, or string is used across a codebase. "
        "Supports recursive search with optional file glob filter."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for, e.g. 'def my_function' or 'import.*react'",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search in. Defaults to working directory.",
            },
            "glob": {
                "type": "string",
                "description": "Glob filter for filenames, e.g. '*.py' or '*.{ts,tsx}'",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Case sensitive search. Default true.",
            },
            "context_lines": {
                "type": "integer",
                "description": "Number of lines of context to show around each match (0-5). Default 0.",
            },
        },
        "required": ["pattern"],
    }

    async def run(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        case_sensitive: bool = True,
        context_lines: int = 0,
    ) -> str:
        import re
        import asyncio

        # Determine root
        wd = _conv_working_dir.get()
        if path:
            root = _resolve_and_check(path)
        elif wd:
            root = wd
        else:
            allowed = get_config().resolve_allowed_paths()
            if not allowed:
                return "Error: no working directory or allowed path configured."
            root = allowed[0]

        # Try ripgrep first (fast), fall back to Python (always available)
        try:
            rg_args = ["rg", "--line-number", "--no-heading", "--color=never"]
            if not case_sensitive:
                rg_args.append("--ignore-case")
            if context_lines > 0:
                rg_args += [f"--context={min(context_lines, 5)}"]
            if glob:
                rg_args += ["--glob", glob]
            rg_args += ["--", pattern, str(root)]

            proc = await asyncio.create_subprocess_exec(
                *rg_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            output = stdout.decode("utf-8", errors="replace").strip()
            if output:
                lines = output.split("\n")
                if len(lines) > 300:
                    output = "\n".join(lines[:300]) + f"\n… ({len(lines) - 300} more lines)"
                return output or "No matches found."
            if proc.returncode == 0 or proc.returncode == 1:
                return "No matches found."
        except (FileNotFoundError, asyncio.TimeoutError):
            pass  # ripgrep not available, fall back

        # Python fallback
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            compiled = re.compile(pattern, flags)
        except re.error as e:
            return f"Invalid regex: {e}"

        root_path = root if root.is_dir() else root.parent
        results = []
        max_results = 300

        def _collect_files(base: Path) -> list[Path]:
            files = []
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS]
                for fname in filenames:
                    if glob:
                        import fnmatch as _fn
                        if not _fn.fnmatch(fname, glob):
                            continue
                    files.append(Path(dirpath) / fname)
            return files

        target_files = [root_path] if root_path.is_file() else _collect_files(root_path)

        for file_path in target_files:
            if len(results) >= max_results:
                break
            try:
                _resolve_and_check(str(file_path))
            except PermissionError:
                continue
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
                file_lines = text.splitlines()
                for i, line in enumerate(file_lines, 1):
                    if compiled.search(line):
                        results.append(f"{file_path}:{i}: {line}")
                        if len(results) >= max_results:
                            break
            except Exception:
                continue

        if not results:
            return "No matches found."
        suffix = f"\n… (showing first {max_results})" if len(results) >= max_results else ""
        return "\n".join(results) + suffix


FILESYSTEM_TOOLS: list[BaseTool] = [
    ReadFileTool(),
    WriteFileTool(),
    EditFileTool(),
    ListDirectoryTool(),
    SearchFilesTool(),
    DeleteFileTool(),
    GlobTool(),
    GrepTool(),
]
