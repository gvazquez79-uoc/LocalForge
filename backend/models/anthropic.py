"""
Anthropic (Claude) model adapter.
Uses the official anthropic SDK with streaming tool use.
"""
from __future__ import annotations

from typing import AsyncIterator, Any

from backend.models.base import BaseModelAdapter, StreamEvent


class AnthropicAdapter(BaseModelAdapter):
    def __init__(self, model_name: str, api_key: str):
        self.model_name = model_name
        self._api_key = api_key

    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
    ) -> AsyncIterator[StreamEvent]:
        try:
            import anthropic
        except ImportError:
            yield StreamEvent(type="error", data={"message": "anthropic package not installed"})
            return

        client = anthropic.AsyncAnthropic(api_key=self._api_key)

        # Convert messages to Anthropic format
        anthropic_messages = _to_anthropic_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": 8096,
            "system": system,
            "messages": anthropic_messages,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            async with client.messages.stream(**kwargs) as stream:
                current_tool_id = None
                current_tool_name = None
                current_tool_input_json = ""

                async for event in stream:
                    event_type = type(event).__name__

                    if event_type == "RawContentBlockStartEvent":
                        block = event.content_block
                        if block.type == "tool_use":
                            current_tool_id = block.id
                            current_tool_name = block.name
                            current_tool_input_json = ""

                    elif event_type == "RawContentBlockDeltaEvent":
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield StreamEvent(type="text_delta", data={"text": delta.text})
                        elif delta.type == "input_json_delta":
                            current_tool_input_json += delta.partial_json

                    elif event_type == "RawContentBlockStopEvent":
                        if current_tool_name is not None:
                            import json
                            try:
                                tool_input = json.loads(current_tool_input_json) if current_tool_input_json else {}
                            except json.JSONDecodeError:
                                tool_input = {}
                            yield StreamEvent(
                                type="tool_call",
                                data={
                                    "id": current_tool_id,
                                    "name": current_tool_name,
                                    "input": tool_input,
                                },
                            )
                            current_tool_id = None
                            current_tool_name = None
                            current_tool_input_json = ""

                    elif event_type == "RawMessageStopEvent":
                        final = await stream.get_final_message()
                        yield StreamEvent(type="done", data={"stop_reason": final.stop_reason})

        except anthropic.AuthenticationError:
            yield StreamEvent(type="error", data={"message": "Invalid Anthropic API key"})
        except anthropic.APIConnectionError as e:
            yield StreamEvent(type="error", data={"message": f"Connection error: {e}"})
        except Exception as e:
            yield StreamEvent(type="error", data={"message": str(e)})


def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Convert internal message format to Anthropic API format."""
    result = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "tool":
            # Tool result — becomes a user message with tool_result blocks
            result.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_use_id", ""),
                    "content": str(content),
                }],
            })
        elif isinstance(content, list):
            result.append({"role": role, "content": content})
        else:
            result.append({"role": role, "content": str(content)})

    return result
