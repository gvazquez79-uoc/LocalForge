"""
Filesystem tools: read, write, list, search files.
Respects allowed_paths from config.
"""
from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Any

from backend.config import get_config
from backend.tools.base import BaseTool


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
FILESYSTEM_TOOLS: list[BaseTool] = [
    ReadFileTool(),
    WriteFileTool(),
    EditFileTool(),
    ListDirectoryTool(),
    SearchFilesTool(),
    DeleteFileTool(),
]
