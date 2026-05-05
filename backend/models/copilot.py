"""
GitHub Copilot model adapter.

Uses the GitHub OAuth token stored in DB to:
  1. Exchange for a short-lived Copilot session token (valid ~30 min)
  2. Call the Copilot API (OpenAI-compatible) at https://api.githubcopilot.com
"""
from __future__ import annotations

import time
import httpx
from backend.models.base import BaseAdapter, StreamEvent


COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
COPILOT_API_BASE  = "https://api.githubcopilot.com/v1"

_COPILOT_HEADERS = {
    "Editor-Version":        "vscode/1.85.0",
    "Editor-Plugin-Version": "copilot/1.138.0",
    "User-Agent":            "GithubCopilot/1.138.0",
    "Openai-Intent":         "conversation-panel",
}


class CopilotAdapter(BaseAdapter):
    """Adapter for GitHub Copilot API (OpenAI-compatible)."""

    def __init__(self, model_name: str, github_token: str):
        self.model_name    = model_name
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

    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ):
        session_token = await self._get_session_token()

        # Build request — OpenAI format
        payload: dict = {
            "model":       self.model_name,
            "temperature": self.temperature,
            "stream":      True,
            "messages":    [],
        }

        if system_prompt:
            payload["messages"].append({"role": "system", "content": system_prompt})

        payload["messages"].extend(messages)

        if tools:
            # Convert Anthropic tool schema → OpenAI tool schema
            oai_tools = []
            for t in tools:
                oai_tools.append({
                    "type": "function",
                    "function": {
                        "name":        t["name"],
                        "description": t.get("description", ""),
                        "parameters":  t.get("input_schema") or t.get("parameters", {}),
                    },
                })
            payload["tools"] = oai_tools

        headers = {
            "Authorization": f"Bearer {session_token}",
            "Content-Type":  "application/json",
            "Accept":        "text/event-stream",
            **_COPILOT_HEADERS,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{COPILOT_API_BASE}/chat/completions",
                json=payload,
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    raise RuntimeError(
                        f"Copilot API error ({response.status_code}): {body.decode()}"
                    )

                # Accumulate tool call state across chunks
                tool_calls_buf: dict[int, dict] = {}

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload_str = line[6:].strip()
                    if payload_str == "[DONE]":
                        break

                    import json
                    try:
                        chunk = json.loads(payload_str)
                    except Exception:
                        continue

                    choice = chunk.get("choices", [{}])[0]
                    delta  = choice.get("delta", {})

                    # Text delta
                    content = delta.get("content")
                    if content:
                        yield StreamEvent(type="text_delta", data={"text": content})

                    # Tool call chunks
                    for tc in delta.get("tool_calls", []):
                        idx = tc.get("index", 0)
                        if idx not in tool_calls_buf:
                            tool_calls_buf[idx] = {
                                "id":    tc.get("id", ""),
                                "name":  tc.get("function", {}).get("name", ""),
                                "input": "",
                            }
                        else:
                            if tc.get("id"):
                                tool_calls_buf[idx]["id"] = tc["id"]
                            fn = tc.get("function", {})
                            if fn.get("name"):
                                tool_calls_buf[idx]["name"] = fn["name"]
                            tool_calls_buf[idx]["input"] += fn.get("arguments", "")

                    finish = choice.get("finish_reason")
                    if finish in ("tool_calls", "stop") and tool_calls_buf:
                        for tc in tool_calls_buf.values():
                            try:
                                import json as _json
                                tc_input = _json.loads(tc["input"]) if tc["input"] else {}
                            except Exception:
                                tc_input = {}
                            yield StreamEvent(
                                type="tool_call",
                                data={
                                    "id":    tc["id"],
                                    "name":  tc["name"],
                                    "input": tc_input,
                                },
                            )
                        tool_calls_buf.clear()

                    # Usage
                    usage = chunk.get("usage")
                    if usage:
                        yield StreamEvent(type="usage", data={
                            "input_tokens":  usage.get("prompt_tokens", 0),
                            "output_tokens": usage.get("completion_tokens", 0),
                        })
