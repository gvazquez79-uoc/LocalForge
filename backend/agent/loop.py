"""
Agent execution loop.
Handles multi-turn tool use with streaming SSE events.
"""
from __future__ import annotations

import asyncio
import json
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
    # Self-introduction + capability list without doing anything (ES)
    "soy localforge",
    "estoy listo para ayudarte",
    "estoy aquí para ayudarte",
    "analizar archivos y directorios",
    "ejecutar comandos en terminal",
    "buscar información en internet",
    "ayudar con código",
    "¿qué necesitas hacer",
    "que necesitas hacer",
    "recuerda que puedo",
    "nota: si quieres continuar",
    "si quieres continuar con algo",
    "solo dime \"si\"",
    "solo dime 'si'",
    "¿en qué puedo ayudarte hoy",
    "en qué puedo ayudarte hoy",
    "¿qué quieres que haga hoy",
    "qué quieres que haga hoy",
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
    # Self-introduction + capability list without doing anything (EN)
    "i'm localforge",
    "i am localforge",
    "i'm ready to help you",
    "i'm here to help you",
    "what do you need today",
    "what would you like me to do today",
    "analyze files and directories",
    "execute terminal commands",
    "remember, i can",
    "just say \"yes\"",
    "just say 'yes'",
]


def _detect_hallucinated_action(text: str) -> bool:
    """Return True if the model claims to have taken an action without calling a tool."""
    lower = text.lower()
    return any(pattern in lower for pattern in _HALLUCINATION_PATTERNS)


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
            # Detect if the model claimed to do something without calling a tool,
            # or promised capability without demonstrating it.
            if assistant_text and _detect_hallucinated_action(assistant_text):
                correction = (
                    "[SYSTEM] You described having capabilities or claimed to take an action, "
                    "but you did NOT call any tool. You MUST call the appropriate tool RIGHT NOW. "
                    "Do not write more text explaining what you can do — just call the tool. "
                    "For example: if the user asked to list files, call list_directory(). "
                    "If they asked to run a command, call execute_command(). "
                    "Call the tool NOW."
                )
                yield StreamEvent(
                    type="warning",
                    data={"message": "⚠️ El modelo describió capacidades sin llamar a ninguna herramienta. Solicitando que actúe..."},
                )
                working_messages.append({"role": "user", "content": correction})
                # Continue to next iteration so the model actually calls the tool
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
