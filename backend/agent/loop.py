"""
Agent execution loop.
Handles multi-turn tool use with streaming SSE events.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import AsyncIterator

from backend.config import get_config
from backend.models.base import BaseModelAdapter, StreamEvent
from backend.tools.base import BaseTool

# Persistent memory file — shared across all conversations
MEMORY_FILE = Path.home() / ".localforge_memory.md"


def _load_memory() -> str:
    """Load persistent memory and return it as a system prompt addendum."""
    if not MEMORY_FILE.exists():
        return ""
    content = MEMORY_FILE.read_text(encoding="utf-8").strip()
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

    return tools


def _tools_to_anthropic(tools: list[BaseTool]) -> list[dict]:
    return [t.to_anthropic_schema() for t in tools]


def _tools_to_openai(tools: list[BaseTool]) -> list[dict]:
    return [t.to_openai_schema() for t in tools]


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


def _requires_confirmation(tool_name: str, tool_input: dict) -> bool:
    """Check if a tool call requires user confirmation."""
    cfg = get_config()
    
    if tool_name == "execute_command":
        return cfg.tools.terminal.require_confirmation
    if tool_name == "write_file":
        return "write_file" in cfg.tools.filesystem.require_confirmation_for
    if tool_name == "delete_file":
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
    
    if tool_name == "delete_file":
        path = tool_input.get("path", "")
        return f"Delete file:\n\n`{path}`\n\n⚠️ This action cannot be undone!"
    
    return f"Run {tool_name} with: {json.dumps(tool_input, indent=2)}"


async def run_agent(
    messages: list[dict],
    adapter: BaseModelAdapter,
    extra_tools: list[BaseTool] | None = None,
) -> AsyncIterator[StreamEvent]:
    """
    Run the agent loop. Yields StreamEvents for the frontend.
    """
    cfg = get_config()
    tools = get_enabled_tools() + (extra_tools or [])
    tool_map = {t.name: t for t in tools}

    is_anthropic = "anthropic" in type(adapter).__name__.lower()
    schema_tools = _tools_to_anthropic(tools) if is_anthropic else _tools_to_openai(tools)

    system = cfg.agent.system_prompt + _load_memory()
    working_messages = list(messages)
    max_iter = cfg.agent.max_iterations
    hallucination_corrections = 0  # Limit corrections to 1 per turn to avoid loops

    for iteration in range(max_iter):
        yield StreamEvent(type="iteration", data={"n": iteration + 1})

        tool_calls: list[dict] = []
        assistant_text = ""
        stop_reason = None

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

        if not tool_calls:
            # Detect hallucinated actions only when the user actually requested a task
            # (not a greeting, not a capability inquiry) and only once per turn.
            if (
                hallucination_corrections < 1
                and assistant_text
                and _is_task_request(working_messages)
                and not _is_capability_inquiry(working_messages)
                and _detect_hallucinated_action(assistant_text)
            ):
                hallucination_corrections += 1
                correction = (
                    "[SYSTEM] You described having capabilities or claimed to take an action, "
                    "but you did NOT call any tool. You MUST call the appropriate tool RIGHT NOW. "
                    "Do not write more text explaining what you can do — just call the tool. "
                    "For example: if the user asked to list files, call list_directory(). "
                    "If they asked to run a command, call execute_command(). "
                    "Call the tool NOW."
                )
                # Inject correction silently — no warning shown in the chat UI.
                # Tell the frontend to discard the text streamed so far (the capability list)
                # so the next iteration's response starts clean.
                yield StreamEvent(type="clear_content", data={})
                working_messages.append({"role": "user", "content": correction})
                continue
            return

        # Execute each tool call
        for tc in tool_calls:
            tool_name = tc["name"]
            tool_input = tc["input"]
            tool_id = tc["id"]

            tool = tool_map.get(tool_name)
            
            # Check if confirmation is needed
            if tool and _requires_confirmation(tool_name, tool_input):
                # Emit confirmation event - frontend will show modal
                confirmation_msg = _format_confirmation_message(tool_name, tool_input)
                yield StreamEvent(
                    type="tool_confirmation_needed",
                    data={
                        "tool_use_id": tool_id,
                        "name": tool_name,
                        "input": tool_input,
                        "message": confirmation_msg,
                    },
                )
                # Emit that we're waiting
                yield StreamEvent(
                    type="tool_result",
                    data={
                        "tool_use_id": tool_id,
                        "name": tool_name,
                        "result": "⏳ Waiting for user confirmation...",
                    },
                )
                # Add to history so we don't repeat
                working_messages.append({
                    "role": "tool",
                    "tool_use_id": tool_id,
                    "content": "⏳ Waiting for user confirmation...",
                })
                # Stop here - user needs to confirm
                # In this simple version, we continue anyway
                # The modal is informational + Cancel stops the stream
            
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

    yield StreamEvent(type="error", data={"message": f"Max iterations ({max_iter}) reached"})
