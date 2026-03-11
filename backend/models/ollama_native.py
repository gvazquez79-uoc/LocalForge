"""
Ollama native adapter — uses /api/chat directly instead of the OpenAI-compat layer.

This avoids a known issue where Ollama's /v1/chat/completions endpoint returns
empty message content for some models (e.g. gemma3:12b) despite the model working
correctly via /api/chat.

Tool calling is supported for models that handle it (the ollama library auto-detects).
For models that don't support tools, we fall back gracefully with no tools.
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from backend.models.base import BaseModelAdapter, StreamEvent

logger = logging.getLogger(__name__)


def _convert_messages_to_ollama(messages: list[dict], system: str) -> list[dict]:
    """Convert OpenAI-format messages + system prompt to Ollama /api/chat format."""
    result: list[dict] = []

    if system:
        result.append({"role": "system", "content": system})

    for msg in messages:
        role = msg["role"]
        content = msg.get("content")

        # Skip messages with no content (e.g. assistant tool-call-only turns from Claude)
        if role == "assistant" and not content and not msg.get("tool_calls"):
            continue

        # Handle assistant messages with tool_calls in OpenAI format.
        # This happens after inline tool-call recovery rewrites "icall {...}" text
        # into structured tool_calls. Convert to Ollama's tool_calls schema.
        if role == "assistant" and msg.get("tool_calls"):
            openai_tcs = msg["tool_calls"]
            ollama_tcs = []
            for tc in openai_tcs:
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                ollama_tcs.append({"function": {"name": fn.get("name", ""), "arguments": args}})
            result.append({
                "role": "assistant",
                "content": str(content or ""),
                "tool_calls": ollama_tcs,
            })
            continue

        if role == "tool":
            result.append({
                "role": "tool",
                "content": str(content or ""),
            })
            continue

        if isinstance(content, list):
            images = []
            text_parts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "image":
                    source = block.get("source", {})
                    if source.get("type") == "base64":
                        images.append(source.get("data", ""))
                elif btype == "document":
                    text_parts.append("[PDF adjunto]")
                elif btype == "tool_use":
                    # Anthropic assistant tool_use blocks — skip for Ollama
                    continue
            text = " ".join(text_parts).strip()
            if not text and not images:
                continue
            ollama_msg: dict = {"role": role, "content": text}
            if images:
                ollama_msg["images"] = images
            result.append(ollama_msg)
        else:
            text = str(content or "").strip()
            if not text:
                continue
            result.append({"role": role, "content": text})

    return result


def _openai_tools_to_ollama(tools: list[dict]) -> list[dict]:
    """Convert OpenAI function-calling schema to Ollama tool schema."""
    ollama_tools = []
    for tool in tools:
        if tool.get("type") != "function":
            continue
        fn = tool.get("function", {})
        ollama_tools.append({
            "type": "function",
            "function": {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
            },
        })
    return ollama_tools


class OllamaNativeAdapter(BaseModelAdapter):
    def __init__(self, model_name: str, base_url: str = "http://localhost:11434"):
        self.model_name = model_name
        # Normalise: strip trailing /v1 or /api if user added it
        host = base_url.rstrip("/")
        if host.endswith("/v1"):
            host = host[:-3]
        if host.endswith("/api"):
            host = host[:-4]
        self._host = host

    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
    ) -> AsyncIterator[StreamEvent]:
        logger.info(f"OllamaNativeAdapter.stream_chat called: model={self.model_name} host={self._host}")
        try:
            from ollama import AsyncClient
        except ImportError:
            yield StreamEvent(type="error", data={"message": "ollama package not installed — run: pip install ollama"})
            return

        client = AsyncClient(host=self._host)
        ollama_messages = _convert_messages_to_ollama(messages, system)
        ollama_tools = _openai_tools_to_ollama(tools) if tools else []

        kwargs: dict = {
            "model": self.model_name,
            "messages": ollama_messages,
            "stream": True,
        }
        logger.info(f"Calling ollama with model={self.model_name!r} tools={len(ollama_tools)}")
        if ollama_tools:
            kwargs["tools"] = ollama_tools

        tool_calls_pending: list[dict] = []
        emitted_done = False

        try:
            async for chunk in await client.chat(**kwargs):
                msg = chunk.message

                if msg.content:
                    yield StreamEvent(type="text_delta", data={"text": msg.content})

                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        fn = tc.function
                        tool_input = dict(fn.arguments) if fn.arguments else {}
                        call_id = f"call_{fn.name}_{id(tc)}"
                        tool_calls_pending.append({
                            "id": call_id,
                            "name": fn.name,
                            "input": tool_input,
                        })

                if chunk.done:
                    for tc in tool_calls_pending:
                        yield StreamEvent(type="tool_call", data=tc)
                    stop_reason = "tool_calls" if tool_calls_pending else (chunk.done_reason or "stop")
                    yield StreamEvent(type="done", data={"stop_reason": stop_reason})
                    emitted_done = True
                    break

            if not emitted_done:
                for tc in tool_calls_pending:
                    yield StreamEvent(type="tool_call", data=tc)
                yield StreamEvent(type="done", data={"stop_reason": "tool_calls" if tool_calls_pending else "stop"})

        except Exception as e:
            err = str(e)
            logger.error(f"OllamaNativeAdapter error: {type(e).__name__}: {err!r}")
            # Retry without tools — gemma3 and others return 400 "does not support tools"
            if ollama_tools:
                logger.info("Retrying without tools...")
                kwargs.pop("tools", None)
                try:
                    async for chunk in await client.chat(**kwargs):
                        if chunk.message.content:
                            yield StreamEvent(type="text_delta", data={"text": chunk.message.content})
                        if chunk.done:
                            yield StreamEvent(type="done", data={"stop_reason": chunk.done_reason or "stop"})
                            return
                    yield StreamEvent(type="done", data={"stop_reason": "stop"})
                except Exception as e2:
                    logger.error(f"OllamaNativeAdapter retry error: {type(e2).__name__}: {str(e2)!r}")
                    yield StreamEvent(type="error", data={"message": str(e2)})
            else:
                yield StreamEvent(type="error", data={"message": err})
