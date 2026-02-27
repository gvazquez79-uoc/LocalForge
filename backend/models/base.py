"""
Abstract base model interface.
All adapters must implement `stream_chat`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Any

from pydantic import BaseModel as PydanticModel


class ChatMessage(PydanticModel):
    role: str  # "user" | "assistant" | "tool"
    content: Any  # str or list of content blocks


class StreamEvent(PydanticModel):
    """Events emitted by the agent loop via SSE."""
    type: str  # "text_delta" | "tool_call" | "tool_result" | "done" | "error"
    data: Any = None


class BaseModelAdapter(ABC):
    """Unified interface for all LLM providers."""

    model_name: str

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
    ) -> AsyncIterator[StreamEvent]:
        """
        Yield StreamEvents:
          - text_delta: {"text": "..."}
          - tool_call: {"id": "...", "name": "...", "input": {...}}
          - done: {"stop_reason": "..."}
          - error: {"message": "..."}
        """
