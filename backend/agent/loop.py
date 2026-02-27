"""
Agent execution loop.
Handles multi-turn tool use with streaming SSE events.

Flow:
  user message → model (with tools) → tool_calls?
    → execute tools → append results → model again
    → repeat until stop or max_iterations
"""
from __future__ import annotations

import json
from typing import AsyncIterator

from backend.config import get_config
from backend.models.base import BaseModelAdapter, StreamEvent
from backend.tools.base import BaseTool


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


async def run_agent(
    messages: list[dict],
    adapter: BaseModelAdapter,
    extra_tools: list[BaseTool] | None = None,
) -> AsyncIterator[StreamEvent]:
    """
    Run the agent loop. Yields StreamEvents for the frontend.

    Special event types:
      - text_delta:    partial assistant text
      - tool_call:     model wants to call a tool
      - tool_result:   tool execution result
      - iteration:     new loop iteration started
      - done:          final stop
      - error:         something went wrong
    """
    cfg = get_config()
    tools = get_enabled_tools() + (extra_tools or [])
    tool_map = {t.name: t for t in tools}

    is_anthropic = "anthropic" in type(adapter).__name__.lower()
    schema_tools = _tools_to_anthropic(tools) if is_anthropic else _tools_to_openai(tools)

    system = cfg.agent.system_prompt
    working_messages = list(messages)
    max_iter = cfg.agent.max_iterations

    for iteration in range(max_iter):
        yield StreamEvent(type="iteration", data={"n": iteration + 1})

        # Collect full assistant response for this turn
        tool_calls: list[dict] = []
        assistant_text = ""
        stop_reason = None

        async for event in adapter.stream_chat(working_messages, schema_tools, system):
            if event.type == "text_delta":
                assistant_text += event.data["text"]
                yield event  # pass through to frontend

            elif event.type == "tool_call":
                tool_calls.append(event.data)
                yield event  # frontend shows tool call

            elif event.type == "done":
                stop_reason = event.data.get("stop_reason")
                yield event

            elif event.type == "error":
                yield event
                return

        # Append assistant turn to history
        if is_anthropic:
            # Build Anthropic content blocks
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

        # If no tool calls, we're done
        if not tool_calls:
            return

        # Execute each tool call
        for tc in tool_calls:
            tool_name = tc["name"]
            tool_input = tc["input"]
            tool_id = tc["id"]

            tool = tool_map.get(tool_name)
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

            # Append tool result to message history
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
