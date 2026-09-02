"""
GitHub Copilot model adapter.

Uses the GitHub OAuth token stored in DB to:
  1. Exchange for a short-lived Copilot session token (valid ~30 min)
  2. Call the Copilot API (OpenAI-compatible) at https://api.githubcopilot.com

The agent loop treats this adapter as non-Anthropic (see `is_anthropic` in
agent/loop.py), so it receives OpenAI-format tool schemas and OpenAI-format
messages. Content blocks may still arrive in Anthropic format when the user
attaches images or PDFs, so they go through the same converter as
openai_compat.py.
"""
from __future__ import annotations

import json
import time
from typing import AsyncIterator

import httpx

from backend.models.base import BaseModelAdapter, StreamEvent
from backend.models.openai_compat import _convert_content_for_openai


COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
# NOTE: unverified against a live Copilot subscription. If requests come back
# 404, drop the "/v1" segment — GitHub serves the OpenAI-compatible endpoint at
# https://api.githubcopilot.com/chat/completions.
COPILOT_API_BASE  = "https://api.githubcopilot.com/v1"

_COPILOT_HEADERS = {
    "Editor-Version":        "vscode/1.85.0",
    "Editor-Plugin-Version": "copilot/1.138.0",
    "User-Agent":            "GithubCopilot/1.138.0",
    "Openai-Intent":         "conversation-panel",
}


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    """Normalise tool schemas to OpenAI format.

    The loop hands us OpenAI schemas already ({"type": "function", ...}), but
    accept Anthropic schemas too so the adapter keeps working if it is ever
    called from an Anthropic-shaped path.
    """
    normalised: list[dict] = []
    for t in tools:
        if "function" in t:
            normalised.append(t)
            continue
        normalised.append({
            "type": "function",
            "function": {
                "name":        t.get("name", ""),
                "description": t.get("description", ""),
                "parameters":  t.get("input_schema") or t.get("parameters") or {},
            },
        })
    return normalised


class CopilotAdapter(BaseModelAdapter):
    """Adapter for GitHub Copilot API (OpenAI-compatible)."""

    def __init__(self, model_name: str, github_token: str):
        # Models are registered as "copilot/<id>"; the API expects the bare id.
        self.model_name    = model_name.split("/", 1)[1] if model_name.startswith("copilot/") else model_name
        self._github_token = github_token
        self.temperature: float = 0.3

        # Session token cache
        self._session_token: str = ""
        self._session_expires: float = 0.0

    async def _get_session_token(self) -> str:
        """Return a valid Copilot session token, refreshing if expired."""
        if self._session_token and time.time() < self._session_expires - 60:
            return self._session_token

        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                COPILOT_TOKEN_URL,
                headers={
                    "Authorization": f"Bearer {self._github_token}",
                    "Accept": "application/json",
                    **_COPILOT_HEADERS,
                },
            )
            if r.status_code != 200:
                raise RuntimeError(f"Copilot token refresh failed ({r.status_code}): {r.text}")

            data = r.json()
            self._session_token   = data["token"]
            self._session_expires = data.get("expires_at", time.time() + 1700)

        return self._session_token

    def _build_messages(self, messages: list[dict], system: str) -> list[dict]:
        out: list[dict] = []
        if system:
            out.append({"role": "system", "content": system})

        for msg in messages:
            if msg["role"] == "tool":
                out.append({
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id", msg.get("tool_use_id", "")),
                    "content": str(msg["content"]),
                })
            elif msg["role"] == "assistant" and msg.get("tool_calls"):
                out.append({
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": msg["tool_calls"],
                })
            else:
                out.append({
                    "role": msg["role"],
                    "content": _convert_content_for_openai(msg["content"]),
                })
        return out

    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
    ) -> AsyncIterator[StreamEvent]:
        try:
            session_token = await self._get_session_token()
        except Exception as exc:
            yield StreamEvent(type="error", data={"message": str(exc)})
            return

        payload: dict = {
            "model":       self.model_name,
            "temperature": self.temperature,
            "stream":      True,
            "messages":    self._build_messages(messages, system),
        }
        if tools:
            payload["tools"] = _to_openai_tools(tools)

        headers = {
            "Authorization": f"Bearer {session_token}",
            "Content-Type":  "application/json",
            "Accept":        "text/event-stream",
            **_COPILOT_HEADERS,
        }

        # Accumulate tool call state across chunks
        tool_calls_buf: dict[int, dict] = {}
        emitted_done = False

        def _flush_tool_calls() -> list[StreamEvent]:
            events: list[StreamEvent] = []
            for tc in tool_calls_buf.values():
                if not tc["name"]:
                    continue
                try:
                    tc_input = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    tc_input = {}
                events.append(StreamEvent(
                    type="tool_call",
                    data={"id": tc["id"], "name": tc["name"], "input": tc_input},
                ))
            tool_calls_buf.clear()
            return events

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST",
                    f"{COPILOT_API_BASE}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        yield StreamEvent(type="error", data={
                            "message": f"Copilot API error ({response.status_code}): "
                                       f"{body.decode(errors='replace')[:500]}",
                        })
                        return

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload_str = line[6:].strip()
                        if payload_str == "[DONE]":
                            break

                        try:
                            chunk = json.loads(payload_str)
                        except json.JSONDecodeError:
                            continue

                        # Usage-only chunk — no choices
                        usage = chunk.get("usage")
                        if usage:
                            yield StreamEvent(type="usage", data={
                                "input_tokens":  usage.get("prompt_tokens", 0),
                                "output_tokens": usage.get("completion_tokens", 0),
                            })

                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        delta  = choice.get("delta", {})

                        content = delta.get("content")
                        if content:
                            yield StreamEvent(type="text_delta", data={"text": content})

                        for tc in delta.get("tool_calls", []):
                            idx = tc.get("index", 0)
                            slot = tool_calls_buf.setdefault(
                                idx, {"id": "", "name": "", "arguments": ""}
                            )
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                            # Arguments stream in fragments across chunks — the
                            # first fragment arrives with the name, so it has to
                            # be accumulated here too, not only on later chunks.
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]

                        finish = choice.get("finish_reason")
                        if finish:
                            for event in _flush_tool_calls():
                                yield event
                            yield StreamEvent(type="done", data={"stop_reason": finish})
                            emitted_done = True

            if not emitted_done:
                for event in _flush_tool_calls():
                    yield event
                yield StreamEvent(type="done", data={"stop_reason": "stop"})

        except Exception as exc:
            yield StreamEvent(type="error", data={"message": str(exc)})
