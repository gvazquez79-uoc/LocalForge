"""
Base tool interface. Each tool exposes a JSON schema for the model
and an async `run` method.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    name: str
    description: str
    parameters: dict  # JSON Schema object

    @abstractmethod
    async def run(self, **kwargs: Any) -> str:
        """Execute the tool and return a string result."""

    def to_anthropic_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
