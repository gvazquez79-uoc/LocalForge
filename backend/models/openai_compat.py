"""
OpenAI-compatible adapter.
Works with Ollama (http://localhost:11434/v1), OpenAI, and any compatible endpoint.
Compatible with openai SDK v2.x.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

from backend.models.base import BaseModelAdapter, StreamEvent


class OpenAICompatAdapter(BaseModelAdapter):
    def __init__(self, model_name: str, base_url: str, api_key: str = "ollama"):
        self.model_name = model_name
        self._base_url = base_url
        self._api_key = api_key

    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
    ) -> AsyncIterator[StreamEvent]:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            yield StreamEvent(type="error", data={"message": "openai package not installed"})
            return

        client = AsyncOpenAI(base_url=self._base_url, api_key=self._api_key)

        # Build message list with system prompt prepended
        openai_messages: list[dict] = [{"role": "system", "content": system}]
        for msg in messages:
            if msg["role"] == "tool":
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": msg.get("tool_use_id", msg.get("tool_call_id", "")),
                    "content": str(msg["content"]),
                })
            else:
                content = msg["content"]
                # Flatten list content (Anthropic format) to string for OpenAI
                if isinstance(content, list):
                    text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                    content = "\n".join(text_parts)
                openai_messages.append({"role": msg["role"], "content": content})

        kwargs: dict = {
            "model": self.model_name,
            "messages": openai_messages,
            "stream": True,
        }
        # Only add tools if the model likely supports them
        if tools:
            kwargs["tools"] = tools

        try:
            # Accumulate tool call argument deltas across chunks
            tool_calls_acc: dict[int, dict] = {}
            emitted_done = False

            # openai v2.x: create() with stream=True returns AsyncStream[ChatCompletionChunk]
            # If the model doesn't support tools, retry once without them
            try:
                stream = await client.chat.completions.create(**kwargs)
            except Exception as e:
                if "does not support tools" in str(e).lower() and "tools" in kwargs:
                    kwargs.pop("tools")
                    stream = await client.chat.completions.create(**kwargs)
                else:
                    raise

            async for chunk in stream:
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                # Text content
                if delta.content:
                    yield StreamEvent(type="text_delta", data={"text": delta.content})

                # Tool call deltas — accumulate across chunks
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc_delta.id:
                            tool_calls_acc[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_acc[idx]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments

                # When finish_reason arrives, emit pending tool calls
                if choice.finish_reason == "tool_calls":
                    for tc in tool_calls_acc.values():
                        try:
                            tool_input = json.loads(tc["arguments"]) if tc["arguments"] else {}
                        except json.JSONDecodeError:
                            tool_input = {}
                        yield StreamEvent(
                            type="tool_call",
                            data={"id": tc["id"], "name": tc["name"], "input": tool_input},
                        )
                    tool_calls_acc = {}
                    yield StreamEvent(type="done", data={"stop_reason": "tool_calls"})
                    emitted_done = True

                elif choice.finish_reason in ("stop", "length", "end_turn"):
                    # Flush any accumulated tool calls (some models send them before finish)
                    for tc in tool_calls_acc.values():
                        try:
                            tool_input = json.loads(tc["arguments"]) if tc["arguments"] else {}
                        except json.JSONDecodeError:
                            tool_input = {}
                        if tc["name"]:
                            yield StreamEvent(
                                type="tool_call",
                                data={"id": tc["id"], "name": tc["name"], "input": tool_input},
                            )
                    tool_calls_acc = {}
                    yield StreamEvent(type="done", data={"stop_reason": choice.finish_reason})
                    emitted_done = True

            if not emitted_done:
                yield StreamEvent(type="done", data={"stop_reason": "stop"})

        except Exception as e:
            yield StreamEvent(type="error", data={"message": str(e)})
