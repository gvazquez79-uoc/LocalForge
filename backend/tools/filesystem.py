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
        file_mode = "a" if mode == "append" else "w"
        resolved.write_text(content, encoding="utf-8") if file_mode == "w" else open(resolved, "a").write(content)
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
            # Grep mode — search text in *.txt, *.py, *.md, etc.
            results = []
            for filepath in resolved_dir.rglob("*"):
                if not filepath.is_file():
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
    ListDirectoryTool(),
    SearchFilesTool(),
    DeleteFileTool(),
]
