"""
Filesystem tools: read, write, list, search files.
Respects allowed_paths from config, plus an optional per-conversation
working_directory injected via contextvars (set by the agent loop).
"""
from __future__ import annotations

import difflib
import glob as glob_module
import os
import shutil
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from backend.config import get_config
from backend.tools.base import BaseTool

_BOM = "﻿"

# read_file pagination: a 5.000-line file dumped whole is most of a small model's
# context window, and the agent only ever needs a region of it.
MAX_READ_LINES = 2000
MAX_LINE_CHARS = 2000


def _clip_line(line: str) -> str:
    if len(line) <= MAX_LINE_CHARS:
        return line
    return line[:MAX_LINE_CHARS] + f"… (+{len(line) - MAX_LINE_CHARS} caracteres)"


# ── Ledger of files read in this conversation ────────────────────────────────
# edit_file requires an exact old_string. A model that edits a file it never read
# is guessing at the text, which is the single most common way an edit fails and
# the agent falls back to rewriting the whole file with write_file.
_files_read: ContextVar[set | None] = ContextVar("_files_read", default=None)


def note_file_read(p: Path) -> None:
    seen = _files_read.get()
    if seen is not None:
        seen.add(os.path.normcase(str(p)))


def was_file_read(p: Path) -> bool:
    seen = _files_read.get()
    if seen is None:
        return True          # ledger not active (Telegram, tests) — don't block
    return os.path.normcase(str(p)) in seen


def reset_file_ledger():
    """Called by the agent loop at the start of a run. Returns the token."""
    return _files_read.set(set())


# ── Syntax gate ──────────────────────────────────────────────────────────────

def _syntax_error(path: Path, text: str) -> str | None:
    """Return a description if `text` is broken source, else None.

    Only Python is checked with a real parser (compile() is free and exact);
    for JSON we use json.loads. Everything else passes.
    """
    suffix = path.suffix.lower()
    if suffix == ".py":
        try:
            compile(text, str(path), "exec")
        except SyntaxError as e:
            return f"SyntaxError línea {e.lineno}, columna {e.offset}: {e.msg}"
        except ValueError as e:
            return f"Fuente inválida: {e}"
    elif suffix == ".json":
        import json as _json
        try:
            _json.loads(text or "{}")
        except ValueError as e:
            return f"JSON inválido: {e}"
    return None


def _syntax_gate(path: Path, before: str, after: str, partial: bool = False) -> str | None:
    """Asymmetric gate: block a write that BREAKS a file that used to parse.

    Asymmetric on purpose. If the file was already broken (or is new), the agent
    must be able to write it — that is often exactly the repair. What must never
    happen is persisting a file that parsed before and doesn't now.

    `partial` (mode="append") skips the gate entirely: building a file in chunks
    goes through intermediate states that don't parse, and blocking those made
    append useless for source files.
    """
    if partial or not before.strip():
        return None
    err = _syntax_error(path, after)
    if not err:
        return None
    if _syntax_error(path, before) is not None:
        return None          # ya estaba roto: dejar escribir
    return (
        f"Error: la escritura dejaría {path.name} sintácticamente roto y se ha "
        f"cancelado. El fichero NO se ha modificado.\n{err}\n"
        "Revisa el fragmento (¿indentación?, ¿paréntesis sin cerrar?, ¿contenido "
        "truncado?) y vuelve a intentarlo."
    )


def _read_source(p: Path) -> tuple[str, str, bool]:
    """Read a text file and report how it was encoded on disk.

    Returns (text_normalised_to_LF, dominant_eol, had_bom).

    Path.read_text() applies universal newlines, and Path.write_text() then
    translates "\\n" back to os.linesep. On Windows that silently rewrote every
    LF file as CRLF — a one-line edit produced a whole-file diff. Reading and
    writing bytes ourselves keeps the file exactly as the project has it.
    """
    raw = p.read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig" if had_bom else "utf-8")
    crlf = text.count("\r\n")
    lf_only = text.count("\n") - crlf
    eol = "\r\n" if crlf > lf_only else "\n"
    return text.replace("\r\n", "\n"), eol, had_bom


def _write_source(p: Path, text: str, eol: str, had_bom: bool) -> None:
    """Write back with the file's original line endings and BOM, atomically."""
    body = text.replace("\n", eol) if eol != "\n" else text
    if had_bom and not body.startswith(_BOM):
        body = _BOM + body
    data = body.encode("utf-8")

    # os.replace() swaps in a brand-new inode: without copying the metadata an
    # edit to deploy.sh silently drops its 0755 bit, and a symlink is replaced by
    # a regular file instead of following through to the target.
    target = p.resolve() if p.is_symlink() else p
    tmp = target.with_name(target.name + ".localforge-tmp")
    try:
        tmp.write_bytes(data)
        if target.exists():
            try:
                shutil.copystat(target, tmp)
            except OSError:
                pass          # sistemas de ficheros sin permisos (FAT, algunos SMB)
        os.replace(tmp, target)
    except Exception:
        # Nunca dejar el temporal tirado en el árbol del proyecto.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _unified_diff(before: str, after: str, path: Path, context: int = 2) -> str:
    """Compact unified diff, so the model sees what it actually changed."""
    lines = list(difflib.unified_diff(
        before.splitlines(keepends=False),
        after.splitlines(keepends=False),
        fromfile=f"a/{path.name}", tofile=f"b/{path.name}",
        n=context, lineterm="",
    ))
    if not lines:
        return ""
    if len(lines) > 60:
        lines = lines[:60] + [f"... ({len(lines) - 60} líneas más)"]
    return "\n".join(lines)


def _match_failure_report(content: str, old_string: str, path: Path) -> str:
    """Explain WHY old_string didn't match, instead of just saying it didn't.

    A bare "old_string not found" is a dead end: the model has no way to tell
    whether the text is absent, indented differently, or has trailing spaces —
    so it usually gives up and rewrites the whole file with write_file. This
    tries the near-misses and reports the one that would have worked.
    """
    hints: list[str] = []

    stripped_trailing = "\n".join(l.rstrip() for l in content.split("\n"))
    if stripped_trailing.count(old_string) > 0:
        hints.append(
            "el fichero tiene espacios al final de línea que tu old_string no incluye"
        )

    if old_string.strip() and old_string.strip() in content:
        hints.append(
            "el texto existe pero con distinta indentación o espacios alrededor; "
            "copia la línea EXACTA tal y como la devuelve read_file"
        )

    collapsed = " ".join(old_string.split())
    if collapsed and collapsed in " ".join(content.split()):
        hints.append("el texto existe pero repartido en líneas distintas")

    # Closest actual region of the file, so the model can see the real text.
    first_line = next((l for l in old_string.split("\n") if l.strip()), "")
    closest = ""
    if first_line:
        file_lines = content.split("\n")
        matches = difflib.get_close_matches(first_line, file_lines, n=1, cutoff=0.6)
        if matches:
            idx = file_lines.index(matches[0])
            window = file_lines[max(0, idx - 2): idx + 3]
            numbered = "\n".join(
                f"{max(0, idx - 2) + i + 1:>5} | {l}" for i, l in enumerate(window)
            )
            closest = f"\nLo más parecido que hay en el fichero:\n{numbered}"

    msg = f"Error: old_string no encontrado en {path}."
    if hints:
        msg += " Causa probable: " + "; ".join(hints) + "."
    else:
        msg += " El texto no aparece en el fichero."
    msg += closest
    msg += "\nUsa read_file sobre este fichero y copia el fragmento literalmente."
    return msg

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
    description = (
        "Read the contents of a file, with line numbers. Supports text files and PDFs. "
        "Long files are paginated: use `offset` and `limit` to read further chunks. "
        "For PDFs, use the `pages` parameter (e.g. '1-5' or '3')."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or ~ path to the file"},
            "encoding": {"type": "string", "description": "File encoding (default: utf-8)", "default": "utf-8"},
            "offset": {"type": "integer", "description": "First line to read, 1-based (default: 1)"},
            "limit": {"type": "integer", "description": f"Maximum lines to return (default: {MAX_READ_LINES})"},
            "pages": {"type": "string", "description": "Page range for PDFs, e.g. '1-5' or '3'. Omit to read all pages."},
        },
        "required": ["path"],
    }

    async def run(self, path: str, encoding: str = "utf-8", pages: str | None = None,
                  offset: int | None = None, limit: int | None = None, **_: Any) -> str:
        resolved = _resolve_and_check(path)
        cfg = get_config().tools.filesystem
        max_bytes = cfg.max_file_size_mb * 1024 * 1024

        if not resolved.exists():
            return f"Error: file not found: {resolved}"
        if not resolved.is_file():
            return f"Error: not a file: {resolved}"
        if resolved.stat().st_size > max_bytes:
            return f"Error: file too large (max {cfg.max_file_size_mb} MB)"

        # PDF extraction
        if resolved.suffix.lower() == ".pdf":
            return _read_pdf(resolved, pages)

        try:
            if encoding.lower().replace("-", "") in ("utf8", "utf8sig"):
                # utf-8-sig quita el BOM si lo hay. Sin esto, la primera línea que
                # ve el modelo empieza por ﻿ y su old_string nunca casa con
                # lo que lee edit_file, que sí lo descarta.
                text = resolved.read_text(encoding="utf-8-sig")
            else:
                text = resolved.read_text(encoding=encoding)
        except UnicodeDecodeError:
            return f"Error: cannot decode file as {encoding}. It may be a binary file."

        # Record the read so edit_file can tell whether the model looked first.
        note_file_read(resolved)

        lines = text.replace("\r\n", "\n").split("\n")
        # A trailing newline produces a phantom empty last line.
        if lines and lines[-1] == "":
            lines.pop()
        total = len(lines)

        start = max(1, offset or 1)
        count = limit if (limit and limit > 0) else MAX_READ_LINES
        chunk = lines[start - 1: start - 1 + count]

        if not chunk:
            return f"(el fichero tiene {total} líneas; la línea {start} está fuera de rango)"

        # Line numbers let the model quote back an exact region for edit_file.
        width = len(str(start + len(chunk) - 1))
        body = "\n".join(
            f"{start + i:>{width}} | {_clip_line(l)}" for i, l in enumerate(chunk)
        )

        end = start + len(chunk) - 1
        if total > end:
            body += (
                f"\n\n[mostradas las líneas {start}-{end} de {total}. "
                f"Continúa con read_file(path=..., offset={end + 1})]"
            )
        elif start > 1:
            body += f"\n\n[líneas {start}-{end} de {total}]"
        return body


def _read_pdf(path: Path, pages: str | None = None) -> str:
    """Extract text from a PDF file using pypdf."""
    try:
        import pypdf
    except ImportError:
        try:
            import PyPDF2 as pypdf  # type: ignore
        except ImportError:
            return (
                "Error: no hay librería PDF instalada. "
                "Instala con: pip install pypdf"
            )

    try:
        reader = pypdf.PdfReader(str(path))
        total_pages = len(reader.pages)

        # Parse page range
        page_indices: list[int] = []
        if pages:
            for part in pages.split(","):
                part = part.strip()
                if "-" in part:
                    start, end = part.split("-", 1)
                    page_indices.extend(range(int(start) - 1, min(int(end), total_pages)))
                else:
                    idx = int(part) - 1
                    if 0 <= idx < total_pages:
                        page_indices.append(idx)
        else:
            page_indices = list(range(total_pages))

        extracted = []
        for i in page_indices:
            text = reader.pages[i].extract_text() or ""
            extracted.append(f"--- Página {i + 1} ---\n{text.strip()}")

        if not extracted:
            return f"Error: no se encontraron páginas válidas en {path.name}"

        header = f"PDF: {path.name} ({total_pages} páginas totales)"
        if pages:
            header += f" | Páginas leídas: {pages}"
        return f"{header}\n\n" + "\n\n".join(extracted)

    except Exception as e:
        return f"Error leyendo PDF {path.name}: {e}"


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

        # Creating the whole parent chain silently turns a typo in the path
        # ("src/componets/x.ts") into a brand-new tree plus a "Success". Only
        # create ONE missing level, and say so.
        created_dir = False
        if not resolved.parent.exists():
            if not resolved.parent.parent.exists():
                return (
                    f"Error: el directorio {resolved.parent} no existe y su padre tampoco. "
                    "Comprueba la ruta (¿una errata?) o crea el árbol explícitamente con "
                    "execute_command."
                )
            resolved.parent.mkdir()
            created_dir = True

        existed = resolved.exists()
        before, eol, had_bom = "", "\n", False
        if existed:
            try:
                before, eol, had_bom = _read_source(resolved)
            except UnicodeDecodeError:
                # El fichero que hay no es UTF-8 (cp1252, binario, un .png…).
                # En overwrite da igual: lo vamos a reemplazar entero. En append
                # NO, porque escribiríamos sobre él perdiendo su contenido.
                if mode == "append":
                    return (
                        f"Error: {resolved} existe y no es UTF-8 válido, así que no se puede "
                        "añadir contenido sin corromperlo. Usa mode='overwrite' si de verdad "
                        "quieres reemplazarlo."
                    )
                before, eol, had_bom = "", "\n", False

        if mode == "append":
            after = before + content.replace("\r\n", "\n")
        else:
            after = content.replace("\r\n", "\n")

        broken = _syntax_gate(resolved, before, after, partial=(mode == "append"))
        if broken:
            return broken

        _write_source(resolved, after, eol, had_bom)
        note_file_read(resolved)

        notes = []
        if created_dir:
            notes.append(f"creado el directorio {resolved.parent}")
        if existed and mode != "append":
            diff = _unified_diff(before, after, resolved)
            if diff:
                notes.append("cambios:\n" + diff)
            elif before == after:
                notes.append("el contenido es idéntico al que ya había")

        action = "Añadido a" if mode == "append" else ("Sobrescrito" if existed else "Creado")
        head = f"{action} {resolved} ({len(content)} caracteres)"
        return head + ("\n" + "\n".join(notes) if notes else "")


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

        if old_string == new_string:
            return "Error: old_string y new_string son idénticos — la edición no haría nada."
        if not was_file_read(resolved):
            return (
                f"Error: no has leído {resolved} en esta conversación. edit_file exige el texto "
                "EXACTO, así que hay que verlo antes de editarlo. Llama a "
                f"read_file(path=\"{resolved}\") y vuelve a intentarlo."
            )

        content, eol, had_bom = _read_source(resolved)
        # The model never sees CRLF (read_file normalises too), so match on LF.
        needle = old_string.replace("\r\n", "\n")
        replacement = new_string.replace("\r\n", "\n")
        count = content.count(needle)

        if count == 0:
            return _match_failure_report(content, needle, resolved)
        if count > 1 and not replace_all:
            # Show where they are, so the next attempt can disambiguate.
            positions = []
            start = 0
            for _ in range(min(count, 5)):
                idx = content.find(needle, start)
                positions.append(str(content.count("\n", 0, idx) + 1))
                start = idx + 1
            return (
                f"Error: old_string aparece {count} veces en {resolved} "
                f"(líneas {', '.join(positions)}). Añade contexto alrededor para hacerlo "
                "único, o usa replace_all=true si quieres cambiarlas todas."
            )

        new_content = (content.replace(needle, replacement) if replace_all
                       else content.replace(needle, replacement, 1))

        broken = _syntax_gate(resolved, content, new_content)
        if broken:
            return broken

        _write_source(resolved, new_content, eol, had_bom)
        note_file_read(resolved)   # el contenido en disco es el que acabamos de escribir

        replaced = count if replace_all else 1
        diff = _unified_diff(content, new_content, resolved)
        header = f"Editado {resolved} ({replaced} reemplazo(s))"
        return f"{header}\n{diff}" if diff else header


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
            return f"Error: '{resolved}' is a directory. Use delete_directory to remove directories."
        resolved.unlink()
        return f"Deleted: {resolved}"


class DeleteDirectoryTool(BaseTool):
    name = "delete_directory"
    description = (
        "Delete a directory and all its contents recursively. "
        "Use with caution — this is irreversible."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or ~ path to the directory to delete",
            },
        },
        "required": ["path"],
    }

    async def run(self, path: str, **_: Any) -> str:
        import shutil
        resolved = _resolve_and_check(path)
        if not resolved.exists():
            return f"Error: path not found: {resolved}"
        if not resolved.is_dir():
            return f"Error: '{resolved}' is a file. Use delete_file instead."
        shutil.rmtree(resolved)
        return f"Deleted directory: {resolved}"


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
    DeleteDirectoryTool(),
    GlobTool(),
    GrepTool(),
]
