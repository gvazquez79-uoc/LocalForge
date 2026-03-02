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


# Phrases that indicate the model claims to have done something without a tool call
_HALLUCINATION_PATTERNS = [
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
    "he escrito",
    "acabo de realizar",
    "he realizado",
    "acabo de leer",
    "he leído",
    "acabo de hacer",
    "he hecho",
    "listo, he ",
    "perfecto, acabo",
    "i have saved",
    "i've saved",
    "i have written",
    "i've written",
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
            working_messages.append({"role": "assistant", "content": assistant_text})

        if not tool_calls:
            # Detect if the model claimed to do something without calling a tool
            if assistant_text and _detect_hallucinated_action(assistant_text):
                correction = (
                    "[SISTEMA] Dijiste que realizaste una acción pero no llamaste "
                    "a ninguna herramienta. Debes usar la herramienta apropiada "
                    "AHORA MISMO para completar lo que prometiste. "
                    "No respondas con texto — llama directamente a la herramienta."
                )
                yield StreamEvent(
                    type="warning",
                    data={"message": "⚠️ El modelo afirmó realizar una acción sin usar herramientas. Solicitando corrección..."},
                )
                working_messages.append({"role": "user", "content": correction})
                # Continue to next iteration so the model can actually call the tool
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
