"""
Agent execution loop.
Handles multi-turn tool use with streaming SSE events.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

from backend.config import get_config
from backend.models.base import BaseModelAdapter, StreamEvent
from backend.tools.base import BaseTool

def _get_memory_path() -> Path:
    """Return the resolved Path for the persistent memory file.
    If DATA_DIR is set (Docker volume), stores the file there instead of ~.
    """
    import os
    data_dir = os.getenv("DATA_DIR", "")
    if data_dir:
        return Path(data_dir) / "localforge_memory.md"
    return Path(get_config().agent.memory_file).expanduser()


def _messages_char_count(messages: list[dict]) -> int:
    """Estimate total character count of all messages."""
    total = 0
    for m in messages:
        content = m.get("content") or ""
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += len(str(block.get("text", "") or block.get("content", "")))
    return total


def _truncate_old_tool_results(
    messages: list[dict],
    keep_recent: int = 8,
    max_old_result_chars: int = 300,
) -> tuple[list[dict], int]:
    """
    Truncate tool result content in old messages to reduce context size.
    The most recent `keep_recent` messages are left untouched.
    Returns (new_messages, chars_saved).
    """
    if len(messages) <= keep_recent:
        return messages, 0

    cutoff = len(messages) - keep_recent
    chars_saved = 0
    new_messages = []

    for i, msg in enumerate(messages):
        if i >= cutoff:
            # Recent messages — keep intact
            new_messages.append(msg)
            continue

        role = msg.get("role", "")
        content = msg.get("content", "")

        # Truncate tool results (role="tool" with string content)
        if role == "tool" and isinstance(content, str) and len(content) > max_old_result_chars:
            original_len = len(content)
            truncated = content[:max_old_result_chars]
            chars_saved += original_len - max_old_result_chars
            new_messages.append({
                **msg,
                "content": f"{truncated}\n… [truncado — {original_len - max_old_result_chars} chars omitidos]",
            })
            continue

        # Truncate text blocks inside assistant content lists (read results, etc.)
        if role == "assistant" and isinstance(content, list):
            new_blocks = []
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "text"
                    and len(block.get("text", "")) > max_old_result_chars
                ):
                    original_len = len(block["text"])
                    chars_saved += original_len - max_old_result_chars
                    new_blocks.append({
                        **block,
                        "text": block["text"][:max_old_result_chars] + f"\n… [truncado]",
                    })
                else:
                    new_blocks.append(block)
            new_messages.append({**msg, "content": new_blocks})
            continue

        new_messages.append(msg)

    return new_messages, chars_saved


def _load_project_instructions(working_directory: str) -> str:
    """Load LOCALFORGE.md (or CLAUDE.md fallback) from the project root."""
    wd = Path(working_directory).expanduser()
    for filename in ("LOCALFORGE.md", "localforge.md", "CLAUDE.md", ".claude.md"):
        candidate = wd / filename
        if candidate.exists():
            try:
                content = candidate.read_text(encoding="utf-8").strip()
                if content:
                    return (
                        f"\n\n---\n"
                        f"**INSTRUCCIONES DEL PROYECTO** (`{filename}`):\n\n"
                        f"{content}\n"
                        f"---"
                    )
            except Exception:
                pass
    return ""


def _load_memory() -> str:
    """Load persistent memory and return it as a system prompt addendum."""
    memory_file = _get_memory_path()
    if not memory_file.exists():
        return ""
    content = memory_file.read_text(encoding="utf-8").strip()
    if not content:
        return ""
    return (
        "\n\n---\n"
        "**MEMORIA PERSISTENTE** (información guardada en sesiones anteriores — "
        "úsala como contexto adicional):\n\n"
        f"{content}\n"
        "---"
    )


def get_enabled_tools() -> list[BaseTool]:
    """Return the list of tools enabled in config."""
    cfg = get_config()
    tools: list[BaseTool] = []

    if cfg.tools.filesystem.enabled:
        from backend.tools.filesystem import FILESYSTEM_TOOLS
        tools.extend(FILESYSTEM_TOOLS)

    if cfg.tools.terminal.enabled:
        from backend.tools.terminal import TERMINAL_TOOLS
        tools.extend(TERMINAL_TOOLS)

    if cfg.tools.web_search.enabled:
        from backend.tools.web_search import WEB_SEARCH_TOOLS
        tools.extend(WEB_SEARCH_TOOLS)
        from backend.tools.web_fetch import WEB_FETCH_TOOLS
        tools.extend(WEB_FETCH_TOOLS)

    if cfg.tools.video.enabled:
        from backend.tools.video import VIDEO_TOOLS
        tools.extend(VIDEO_TOOLS)

    if cfg.tools.replicate.enabled:
        from backend.tools.replicate_tools import REPLICATE_TOOLS
        tools.extend(REPLICATE_TOOLS)

    return tools


def _tools_to_anthropic(tools: list[BaseTool]) -> list[dict]:
    return [t.to_anthropic_schema() for t in tools]


def _tools_to_openai(tools: list[BaseTool]) -> list[dict]:
    return [t.to_openai_schema() for t in tools]


# ── Inline tool call parser ───────────────────────────────────────────────────
# Some local models output tool calls as plain text instead of using the
# structured OpenAI function-call API.  Supported formats:
#
#   Format A — JSON wrapper (Qwen2.5, etc.):
#     icall {"name": "list_directory", "arguments": {"path": "..."}}
#     <tool_call>{"name": "...", "arguments": {...}}</tool_call>
#     <functioncall>{"name": "...", "arguments": {...}}</functioncall>
#
#   Format B — XML parameter syntax (qwen3-coder, etc.):
#     <function=list_directory>
#     <parameter=path>G:\Docker\laultimagencia</parameter>
#     </function>
#     (closing tags are optional — the parser handles truncated output too)

_INLINE_TOOL_PREFIXES = re.compile(
    r'(?:icall|<tool_call>|<functioncall>)\s*',
    re.IGNORECASE,
)

# Matches <function=TOOL_NAME> with optional whitespace / closing >
_FUNCTION_TAG = re.compile(r'<function=([a-zA-Z_][a-zA-Z0-9_]*)>', re.IGNORECASE)
# Matches <parameter=NAME>VALUE</parameter>  OR  <parameter=NAME> VALUE (no closing)
_PARAM_TAG = re.compile(
    r'<parameter=([a-zA-Z_][a-zA-Z0-9_]*)>(.*?)(?:</parameter>|(?=<(?:parameter|/function)|$))',
    re.DOTALL | re.IGNORECASE,
)


def _extract_json_object(text: str, start: int) -> str | None:
    """Return the JSON object that begins at `start`, or None if parsing fails."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if esc:
            esc = False
            continue
        if c == "\\" and in_str:
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _parse_inline_tool_calls(text: str) -> list[dict]:
    """Extract tool calls embedded as text and return them in the same dict
    format as the adapter's 'tool_call' events: {id, name, input}."""
    results: list[dict] = []
    seen: set[str] = set()

    # ── Format A: JSON-based prefixes ────────────────────────────────────────
    for match in _INLINE_TOOL_PREFIXES.finditer(text):
        raw = _extract_json_object(text, match.end())
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        name = obj.get("name") or obj.get("function")
        args = obj.get("arguments") or obj.get("parameters") or obj.get("input") or {}
        if not name or name in seen:
            continue
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        seen.add(name)
        results.append({"id": f"inline_{uuid.uuid4().hex[:8]}", "name": name, "input": args})

    # ── Format B: <function=NAME> <parameter=P>V</parameter> ─────────────────
    for fn_match in _FUNCTION_TAG.finditer(text):
        name = fn_match.group(1)
        if name in seen:
            continue
        # Collect everything after <function=NAME> until </function> or end
        after = text[fn_match.end():]
        end_tag = re.search(r'</function>', after, re.IGNORECASE)
        block = after[: end_tag.start()] if end_tag else after
        # Parse <parameter=NAME>VALUE</parameter> pairs within the block
        args: dict = {}
        for p_match in _PARAM_TAG.finditer(block):
            param_name = p_match.group(1)
            param_value = p_match.group(2).strip()
            args[param_name] = param_value
        if not args and not end_tag:
            # Incomplete stream — skip to avoid phantom calls
            continue
        seen.add(name)
        results.append({"id": f"inline_{uuid.uuid4().hex[:8]}", "name": name, "input": args})

    return results


# Phrases that indicate the model claims to have done something without a tool call,
# OR that it promises access/capability without actually calling a tool.
_HALLUCINATION_PATTERNS = [
    # Claims of past actions (ES)
    "acabo de guardar",
    "he guardado",
    "ya guardé",
    "se ha guardado",
    "guardado en memoria",
    "lo he guardado",
    "acabo de ejecutar",
    "he ejecutado",
    "ya ejecuté",
    "acabo de escribir",
    "acabo de realizar",
    "he realizado",
    "acabo de leer",
    "he leído",
    "acabo de hacer",
    "he hecho",
    "listo, he ",
    "perfecto, acabo",
    # Claims of past actions (EN)
    "i have saved",
    "i've saved",
    "i have written",
    "i've written",
    "i have executed",
    "i've executed",
    "i have read",
    "i've read",
    "i have listed",
    "i've listed",
    # Promising capability without doing it (ES) — triggers when no tool was called
    "soy un modelo local",
    "ejecuto directamente en tu",
    "tengo acceso a tu sistema",
    "tengo acceso a tus archivos",
    "tengo acceso al sistema",
    "puedo listar los archivos",
    "puedo listar tus archivos",
    "puedo ver los archivos",
    "puedo ejecutar comandos",
    "puedo leer tus archivos",
    "puedo acceder a tu",
    # Self-introduction + capability menu (only triggers when user sent a task request)
    "soy localforge",
    "analizar archivos y directorios",
    "ejecutar comandos en terminal",
    "buscar información en internet",
    "recuerda que puedo",
    "nota: si quieres continuar",
    "si quieres continuar con algo",
    "solo dime \"si\"",
    "solo dime 'si'",
    "especializado en tareas técnicas",
    "asistente de ia especializado",
    # Promising capability without doing it (EN)
    "i have access to your",
    "i can list the files",
    "i can list your files",
    "i can read your files",
    "i can see your files",
    "i can access your",
    "i can execute commands",
    "i run directly on",
    "i'm a local",
    # Self-introduction + capability menu (EN)
    "i'm localforge",
    "i am localforge",
    "analyze files and directories",
    "execute terminal commands",
    "remember, i can",
    "just say \"yes\"",
    "just say 'yes'",
    # Lazy data analysis — model claims to "analyze" without citing real values
    "he analizado la información",
    "he analizado los datos",
    "basándome en los nombres de las columnas",
    "con base en los nombres de las columnas",
    "según los nombres de las columnas",
    "a partir de los nombres de las columnas",
    "posibles insights que se podrían",
    "posibles análisis que se podrían",
    "lo que podría contener el dataset",
    # False completion claims — model says "done" without calling any tool (ES)
    "listo.",
    "listo!",
    "¡listo!",
    "listo, ahora",
    "listo. ahora",
    "ya está.",
    "ya está!",
    "¡ya está!",
    "ya lo he añadido",
    "ya lo he implementado",
    "ya lo he creado",
    "ya lo he modificado",
    "ya lo he actualizado",
    "ya lo he corregido",
    "ya está añadido",
    "ya está implementado",
    "ya está creado",
    "ya está hecho",
    "he añadido el",
    "he implementado el",
    "he creado el",
    "he modificado el",
    "he actualizado el",
    "he corregido el",
    "queda así:",
    "quedaría así:",
    "el código queda",
    "déjame hacerlo ahora",
    "dejame hacerlo ahora",
    "voy a añadirlo ahora",
    "lo añado ahora",
    "lo implemento ahora",
    # False completion claims (EN)
    "done.",
    "done!",
    "all done",
    "it's done",
    "i've added",
    "i've implemented",
    "i've created",
    "i've updated",
    "i've fixed",
    "i have added",
    "i have implemented",
    "i have created",
    "i have updated",
    "here's the updated",
    "here is the updated",
    "here's the modified",
    "the code now looks",
    "let me do it now",
    # "Let me..." announcements without tool call (ES)
    "déjame ver",
    "dejame ver",
    "déjame revisar",
    "dejame revisar",
    "déjame comprobar",
    "déjame leer",
    "déjame explorar",
    "permíteme ver",
    "permíteme revisar",
    "primero voy a ver",
    "primero veré",
    "empezaré por",
    "comenzaré por",
    "vamos a ver",
    "vamos a revisar",
    # Future-tense announcements without tool call (ES) — "going to do X" but didn't
    "voy a revisar",
    "voy a leer",
    "voy a modificar",
    "voy a editar",
    "voy a escribir",
    "voy a crear",
    "voy a ejecutar",
    "voy a buscar",
    "voy a listar",
    "voy a analizar",
    "voy a verificar",
    "voy a comprobar",
    "voy a añadir",
    "voy a agregar",
    "voy a actualizar",
    "voy a cambiar",
    "voy a abrir",
    "te voy a mostrar",
    "te voy a dar",
    "procedo a revisar",
    "procedo a leer",
    "procedo a modificar",
    "procedo a ejecutar",
    "a continuación voy",
    "a continuación revisaré",
    "a continuación leeré",
    "revisaré el archivo",
    "leeré el archivo",
    "modificaré el archivo",
    "editaré el archivo",
    # Future-tense announcements without tool call (EN)
    "i'm going to review",
    "i'm going to read",
    "i'm going to modify",
    "i'm going to edit",
    "i'm going to write",
    "i'm going to create",
    "i'm going to execute",
    "i'm going to search",
    "i'm going to list",
    "i'm going to analyze",
    "i will review",
    "i will read",
    "i will modify",
    "i will edit",
    "i will write",
    "i will create",
    "i'll review",
    "i'll read",
    "i'll modify",
    "i'll add",
    "let me review",
    "let me read",
    "let me modify",
    "let me check",
    "let me look at",
    # Presenting invented results as if they came from a tool (ES)
    "aquí están los archivos",
    "aquí está la lista de archivos",
    "aquí tienes los archivos",
    "aquí está la lista de los archivos",
    "aquí están las carpetas",
    "aquí están los ficheros",
    "aquí está el contenido del directorio",
    "aquí están los contenidos",
    "el directorio contiene los siguientes",
    "en el directorio se encuentran",
    "en el directorio hay",
    "estos son los archivos",
    "estos son los ficheros",
    "los archivos del proyecto son",
    "los archivos en el directorio",
    "las carpetas del proyecto son",
    "la estructura del proyecto",
    "la estructura de archivos",
    "la estructura es la siguiente",
    "aquí está la estructura",
    "contenido de la carpeta",
    "contenido del directorio",
    "lista de archivos",
    "lista de carpetas",
    "lista de ficheros",
    # Presenting invented results as if they came from a tool (EN)
    "here are the files",
    "here are the folders",
    "here is the directory",
    "here is the content",
    "the directory contains",
    "the project structure",
    "the file structure",
    "these are the files",
    "files in the directory",
    "list of files",
    # False refusals — model claims it cannot access files/filesystem when it has tools (ES)
    "no puedo ver ni acceder",
    "no puedo acceder a los archivos",
    "no puedo ver los archivos",
    "no tengo acceso al sistema de archivos",
    "no tengo acceso directo a",
    "no tengo capacidad de acceder",
    "no tengo acceso a tu sistema",
    "no puedo leer archivos",
    "no puedo listar",
    "no tengo herramientas para acceder",
    "no puedo ejecutar comandos",
    "no tengo acceso a archivos",
    "no me es posible acceder",
    "lamentablemente no puedo acceder",
    "lo siento, pero no puedo acceder",
    "lo siento, no puedo acceder",
    "lo siento, pero no tengo",
    # False refusals (EN)
    "i cannot access your file",
    "i can't access your file",
    "i don't have access to your file",
    "i do not have access to your file",
    "i cannot read files",
    "i can't read files",
    "i cannot list files",
    "i can't list files",
    "i don't have file system access",
    "i do not have file system access",
    "i cannot execute commands",
    "i can't execute commands",
    "unfortunately i cannot access",
    "sorry, i cannot access",
    "sorry, i don't have",
]


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks (reasoning tokens from qwen3 and similar models)."""
    return _THINK_RE.sub("", text).strip()


def _detect_hallucinated_action(text: str) -> bool:
    """Return True if the model claims to have taken an action without calling a tool.
    Thinking tokens (<think>...</think>) are stripped first to avoid false positives."""
    lower = strip_thinking(text).lower()
    return any(pattern in lower for pattern in _HALLUCINATION_PATTERNS)


# Action verbs that indicate the user is requesting something to be done
_TASK_VERBS_ES = [
    "lista", "listar", "muestra", "mostrar", "abre", "abrir", "lee", "leer",
    "ejecuta", "ejecutar", "corre", "busca", "buscar", "crea", "crear",
    "escribe", "escribir", "borra", "borrar", "elimina", "descarga", "descubrir",
    "encuentra", "analiza", "dame", "dime", "haz ", "hazme", "pon ", "instala",
    "configura", "cambia", "comprueba", "revisa", "explica", "genera",
]
_TASK_VERBS_EN = [
    "list ", "show ", "open ", "read ", "execute", "run ", "search", "create",
    "write", "delete", "remove", "download", "find ", "analyze", "explain",
    "give me", "tell me", "make ", "install", "configure", "check ", "generate",
    "get ", "fetch", "scan",
]


def _last_user_message(messages: list[dict]) -> str:
    """Extract the text of the last real user message (skip injected [SYSTEM] corrections)."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            if content.startswith("[SYSTEM]"):
                continue
            return content.lower()
        if isinstance(content, list):
            text = " ".join(
                b.get("text", "") for b in content if isinstance(b, dict)
            ).lower()
            if text.startswith("[system]"):
                continue
            return text
    return ""


def _is_task_request(messages: list[dict]) -> bool:
    """Return True if the last user message looks like an actionable task (not a greeting)."""
    text = _last_user_message(messages)
    if not text:
        return False
    return any(v in text for v in _TASK_VERBS_ES + _TASK_VERBS_EN)


# Patterns that indicate the user is asking ABOUT capabilities, not requesting a task.
# These take precedence over _is_task_request so "Explícame qué puedes hacer" does NOT
# trigger hallucination detection on a legitimate capabilities description.
_CAPABILITY_INQUIRY_ES = [
    "qué puedes", "que puedes", "qué puedes hacer", "que puedes hacer",
    "para qué sirves", "para que sirves", "cómo puedes ayudarme", "como puedes ayudarme",
    "qué eres", "que eres", "cuáles son tus", "cuales son tus",
    "qué herramientas", "que herramientas", "tus capacidades", "tus funciones",
    "qué funciones", "que funciones", "qué herramientas tienes", "que herramientas tienes",
]
_CAPABILITY_INQUIRY_EN = [
    "what can you", "what do you", "what are you", "what are your",
    "what tools", "your capabilities", "your tools", "what's your", "what is your",
    "how can you help", "how can you",
]


def _is_capability_inquiry(messages: list[dict]) -> bool:
    """Return True if the user is asking ABOUT capabilities (not requesting a task to be done).
    Prevents false-positive hallucination detection on legitimate capability descriptions."""
    text = _last_user_message(messages)
    if not text:
        return False
    return any(p in text for p in _CAPABILITY_INQUIRY_ES + _CAPABILITY_INQUIRY_EN)


_MULTI_FILE_KEYWORDS = [
    # Spanish
    "proyecto completo", "stack completo", "estructura completa", "todos los archivos",
    "crea los archivos", "genera los archivos", "crea el proyecto", "genera el proyecto",
    "aplicación completa", "app completa", "sistema completo", "backend completo",
    "frontend completo", "múltiples archivos", "varios archivos",
    "requirements.txt", "dockerfile", "docker-compose",
    "main.py", "app.py", "index.js", "index.ts", "package.json",
    # English
    "complete project", "full project", "full stack", "all files",
    "create the files", "generate the files", "create the project", "complete application",
    "multiple files", "several files",
]


def _user_wants_multiple_files(messages: list[dict]) -> bool:
    """Return True if the original user request implies creating multiple files."""
    text = _last_user_message(messages)
    if not text:
        return False
    return any(kw in text for kw in _MULTI_FILE_KEYWORDS)


def _permission_type_for_tool(tool_name: str) -> str | None:
    """Map tool name to permission category."""
    if tool_name == "execute_command":
        return "execute_command"
    if tool_name in ("write_file", "edit_file"):
        return "write_file"
    if tool_name in ("delete_file", "delete_directory"):
        return "delete_file"
    return None


def _requires_confirmation(tool_name: str, tool_input: dict) -> bool:
    """Check if a tool call requires user confirmation (ignoring saved project perms)."""
    cfg = get_config()

    if tool_name == "execute_command":
        return cfg.tools.terminal.require_confirmation
    if tool_name in ("write_file", "edit_file"):
        return "write_file" in cfg.tools.filesystem.require_confirmation_for
    if tool_name in ("delete_file", "delete_directory"):
        return "delete_file" in cfg.tools.filesystem.require_confirmation_for

    return False


def _format_confirmation_message(tool_name: str, tool_input: dict) -> str:
    """Create a human-readable message for the confirmation dialog."""
    if tool_name == "execute_command":
        cmd = tool_input.get("command", "")
        cwd = tool_input.get("working_dir", "~")
        return f"Execute command:\n\n`{cmd}`\n\nin {cwd}"
    
    if tool_name == "write_file":
        path = tool_input.get("path", "")
        mode = tool_input.get("mode", "overwrite")
        content_preview = tool_input.get("content", "")[:100]
        return f"Write to file:\n\n`{path}`\n\nMode: {mode}\n\nPreview:\n```\n{content_preview}...\n```"

    if tool_name == "edit_file":
        path = tool_input.get("path", "")
        old = tool_input.get("old_string", "")[:80]
        new = tool_input.get("new_string", "")[:80]
        return f"Edit file:\n\n`{path}`\n\n--- remove:\n```\n{old}\n```\n+++ add:\n```\n{new}\n```"

    if tool_name == "delete_file":
        path = tool_input.get("path", "")
        return f"Delete file:\n\n`{path}`\n\n⚠️ This action cannot be undone!"
    
    return f"Run {tool_name} with: {json.dumps(tool_input, indent=2)}"


async def run_agent(
    messages: list[dict],
    adapter: BaseModelAdapter,
    extra_tools: list[BaseTool] | None = None,
    request_approval: Callable[[str], Awaitable[bool]] | None = None,
    working_directory: str | None = None,
) -> AsyncIterator[StreamEvent]:
    """
    Run the agent loop. Yields StreamEvents for the frontend.
    """
    cfg = get_config()
    tools = get_enabled_tools() + (extra_tools or [])
    tool_map = {t.name: t for t in tools}

    # Set the per-conversation working directory so filesystem tools allow it
    if working_directory:
        from backend.tools.filesystem import _conv_working_dir
        from pathlib import Path as _Path
        _wd_resolved = _Path(working_directory).expanduser().resolve()
        _wd_token = _conv_working_dir.set(_wd_resolved)
    else:
        _wd_token = None

    is_anthropic = "anthropic" in type(adapter).__name__.lower()
    schema_tools = _tools_to_anthropic(tools) if is_anthropic else _tools_to_openai(tools)

    # Use per-model system prompt / temperature if defined
    model_name = getattr(adapter, "model", None) or getattr(adapter, "model_name", None)
    per_model_prompt: str | None = None
    if model_name:
        matched = next((m for m in cfg.models if m.name == model_name), None)
        if matched:
            if matched.system_prompt:
                per_model_prompt = matched.system_prompt
            if matched.temperature is not None:
                adapter.temperature = matched.temperature
    system = (per_model_prompt or cfg.agent.system_prompt) + _load_memory()
    if working_directory:
        system += f"\n\n**Directorio de proyecto activo:** `{working_directory}`\nTrabaja dentro de este directorio salvo que el usuario indique otra ruta."
        project_instructions = _load_project_instructions(working_directory)
        if project_instructions:
            system += project_instructions

    working_messages = list(messages)

    # ── Auto-inject project tree on first message ──────────────────────────
    # If this is the start of a conversation (1 user message) and there's a
    # working directory, append the directory tree to the system prompt so
    # the model already knows the project structure from the first message.
    if working_directory and len(working_messages) == 1:
        try:
            from backend.tools.filesystem import ListDirectoryTool
            _tree = await ListDirectoryTool().run(path=working_directory)
            system += (
                f"\n\n**Estructura actual del proyecto** (listado automático al inicio):\n"
                f"```\n{_tree}\n```\n"
                f"Ya conoces los archivos del proyecto — no necesitas llamar a list_directory() "
                f"salvo que quieras ver subdirectorios específicos o refrescar tras cambios."
            )
        except Exception:
            pass  # If listing fails, continue without context
    max_iter = cfg.agent.max_iterations
    hallucination_corrections = 0
    total_input_tokens = 0
    total_output_tokens = 0

    # Track write operations across iterations to detect mid-task stops
    write_calls_this_run: int = 0
    write_calls_last_iter: int = 0

    # Truncation threshold — configurable via Settings > Agent > compact_threshold
    COMPACT_THRESHOLD = get_config().agent.compact_threshold

    import logging as _logging
    _loop_log = _logging.getLogger("backend.agent.loop")

    for iteration in range(max_iter):
        yield StreamEvent(type="iteration", data={"n": iteration + 1})

        # ── Auto-truncation ────────────────────────────────────────────────
        # When the conversation grows too large, truncate old tool results
        # (the biggest contributors to context bloat) — no extra API call needed.
        char_count = _messages_char_count(working_messages)
        if char_count > COMPACT_THRESHOLD:
            working_messages, saved = _truncate_old_tool_results(working_messages)
            if saved > 0:
                _loop_log.info(f"[loop] Truncated old tool results, saved {saved} chars")
                yield StreamEvent(type="compacting", data={"saved_chars": saved})


        _loop_log.info(f"[loop] iter={iteration+1} msgs={len(working_messages)}")

        tool_calls: list[dict] = []
        assistant_text = ""
        stop_reason = None
        write_calls_last_iter = 0
        tools_ran_previous_iter = iteration > 0 and any(
            m.get("role") == "tool" for m in working_messages[-6:]
        )

        async for event in adapter.stream_chat(working_messages, schema_tools, system):
            if event.type == "text_delta":
                assistant_text += event.data["text"]
                yield event

            elif event.type == "tool_call":
                tool_calls.append(event.data)
                yield event

            elif event.type == "done":
                stop_reason = event.data.get("stop_reason")
                yield event

            elif event.type == "usage":
                total_input_tokens += event.data.get("input_tokens", 0)
                total_output_tokens += event.data.get("output_tokens", 0)
                # Don't forward per-iteration events; emit one total at the end

            elif event.type == "error":
                yield event
                return

        # Append assistant turn to history
        if is_anthropic:
            content_blocks = []
            if assistant_text:
                content_blocks.append({"type": "text", "text": assistant_text})
            for tc in tool_calls:
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                })
            working_messages.append({"role": "assistant", "content": content_blocks})
        else:
            assistant_msg: dict = {"role": "assistant", "content": assistant_text or None}
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["input"]),
                        },
                    }
                    for tc in tool_calls
                ]
            working_messages.append(assistant_msg)

        _loop_log.info(f"[loop] iter={iteration+1} tool_calls={[t['name'] for t in tool_calls]} text_len={len(assistant_text)} stop={stop_reason}")

        if not tool_calls:
            # ── Inline tool call recovery ──────────────────────────────────
            # Some local models (e.g. Qwen via Ollama) write tool calls as
            # plain text ("icall {...}") instead of using the structured API.
            # Detect and execute them transparently.
            if assistant_text and not is_anthropic:
                inline = _parse_inline_tool_calls(assistant_text)
                if inline:
                    # Rewrite the last assistant message to use the tool_calls
                    # format so the model history stays coherent.
                    working_messages.pop()
                    assistant_msg_inline: dict = {"role": "assistant", "content": None}
                    assistant_msg_inline["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["input"]),
                            },
                        }
                        for tc in inline
                    ]
                    working_messages.append(assistant_msg_inline)
                    # Clear the raw text from the UI so the user sees only the
                    # actual tool result, not the raw "icall {...}" text.
                    yield StreamEvent(type="clear_content", data={})
                    # Emit tool_call events so the frontend shows the tool blocks.
                    for tc in inline:
                        yield StreamEvent(type="tool_call", data=tc)
                    tool_calls = inline
                    # Fall through to tool execution below

            if not tool_calls:
                # Detect hallucinated actions only when the user actually requested a task
                # (not a greeting, not a capability inquiry) and only once per turn.
                if (
                    hallucination_corrections < 2
                    and assistant_text
                    and not tools_ran_previous_iter  # legit summary after tool use
                    and not _is_capability_inquiry(working_messages)
                    and _detect_hallucinated_action(assistant_text)
                ):
                    hallucination_corrections += 1
                    correction = (
                        "[SISTEMA] PROHIBIDO. Has dicho que hiciste algo ('Listo', 'Ya está', 'He añadido...') "
                        "o has anunciado lo que ibas a hacer, pero NO has llamado a ninguna herramienta. "
                        "Las palabras NO ejecutan código. SOLO las herramientas ejecutan acciones reales. "
                        "LLAMA A LA HERRAMIENTA AHORA — sin texto previo, sin explicaciones, sin 'Listo'. "
                        "Herramientas: write_file(), edit_file(), read_file(), list_directory(), "
                        "execute_command(), web_search(), glob(), grep(). "
                        "Responde en español. Actúa directamente."
                    )
                    # Inject correction silently — no warning shown in the chat UI.
                    # Tell the frontend to discard the text streamed so far (the capability list)
                    # so the next iteration's response starts clean.
                    yield StreamEvent(type="clear_content", data={})
                    working_messages.append({"role": "user", "content": correction})
                    continue
                # ── Mid-task continuation ──────────────────────────────────
                # Only inject if: multiple files written this run AND the model
                # stopped cleanly (end_turn) AND it wrote something last iter.
                # Avoids firing on single-file edits or normal conversation.
                if write_calls_last_iter > 0 and write_calls_this_run > 1 and stop_reason == "end_turn":
                    working_messages.append({
                        "role": "user",
                        "content": (
                            "[SISTEMA] Has creado algunos archivos pero la tarea puede no estar completa. "
                            "Si quedan archivos por crear, continúa llamando a write_file() ahora mismo. "
                            "Si ya terminaste todos los archivos, responde con un resumen breve de lo creado."
                        ),
                    })
                    continue

                if total_input_tokens or total_output_tokens:
                    yield StreamEvent(type="usage", data={
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                    })
                if _wd_token is not None:
                    _conv_working_dir.reset(_wd_token)
                return

        # Execute each tool call
        for tc in tool_calls:
            tool_name = tc["name"]
            tool_input = tc["input"]
            tool_id = tc["id"]

            tool = tool_map.get(tool_name)
            
            # Check if confirmation is needed
            perm_type = _permission_type_for_tool(tool_name)
            already_granted = False
            if perm_type and working_directory:
                try:
                    from backend.db.permissions_store import has_permission
                    already_granted = await has_permission(working_directory, perm_type)
                except Exception:
                    already_granted = False

            if tool and _requires_confirmation(tool_name, tool_input) and not already_granted:
                confirmation_msg = _format_confirmation_message(tool_name, tool_input)
                yield StreamEvent(
                    type="tool_confirmation_needed",
                    data={
                        "tool_use_id": tool_id,
                        "name": tool_name,
                        "input": tool_input,
                        "message": confirmation_msg,
                        "permission_type": perm_type,
                        "project_path": working_directory,
                    },
                )
                # Pause until user approves or rejects (or timeout)
                approved = await request_approval(tool_id) if request_approval else True
                if not approved:
                    result = "Ejecución cancelada por el usuario."
                    yield StreamEvent(
                        type="tool_result",
                        data={"tool_use_id": tool_id, "name": tool_name, "result": result},
                    )
                    if is_anthropic:
                        working_messages.append({"role": "tool", "tool_use_id": tool_id, "content": result})
                    else:
                        working_messages.append({"role": "tool", "tool_call_id": tool_id, "content": result})
                    continue

            # Track write operations so we can detect mid-task stops
            if tool_name in ("write_file", "edit_file", "create_directory"):
                write_calls_this_run += 1
                write_calls_last_iter += 1

            # Execute the tool
            if tool is None:
                result = f"Error: unknown tool '{tool_name}'"
            else:
                try:
                    result = await tool.run(**tool_input)
                except PermissionError as e:
                    result = f"Permission denied: {e}"
                except Exception as e:
                    result = f"Tool error: {e}"

            yield StreamEvent(
                type="tool_result",
                data={"tool_use_id": tool_id, "name": tool_name, "result": result},
            )

            # Auto-retry on command error — if execute_command fails (exit code ≠ 0),
            # inject a correction so the model fixes the problem automatically.
            if tool_name == "execute_command" and isinstance(result, str) and (
                "exit code" in result and "exit code 0" not in result
                or result.startswith("Error:")
                or "error:" in result.lower()[:200]
            ):
                _loop_log.info(f"[loop] Command failed, injecting auto-retry correction")
                # We'll append this after the tool result message below
                _command_failed = True
            else:
                _command_failed = False

            if is_anthropic:
                working_messages.append({
                    "role": "tool",
                    "tool_use_id": tool_id,
                    "content": result,
                })
            else:
                working_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": result,
                })

            # Inject auto-retry correction after saving failed command result
            if _command_failed:
                working_messages.append({
                    "role": "user",
                    "content": (
                        "[SISTEMA] El comando ha fallado. Analiza el error anterior y corrígelo "
                        "inmediatamente — ajusta el comando, instala dependencias faltantes o "
                        "arregla el código según corresponda. No preguntes, actúa directamente."
                    ),
                })

    if _wd_token is not None:
        _conv_working_dir.reset(_wd_token)
    yield StreamEvent(type="error", data={"message": f"Max iterations ({max_iter}) reached"})
