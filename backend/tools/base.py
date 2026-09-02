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


# JSON Schema type name → Python types accepted for it.
_JSON_TYPES: dict[str, tuple] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}


def validate_tool_input(tool: BaseTool, tool_input: dict) -> str | None:
    """Check `tool_input` against the tool's own JSON Schema.

    Returns None when the call is valid, or an actionable message to hand back
    to the model as the tool result. Without this the loop calls
    `tool.run(**tool_input)` directly and a hallucinated parameter surfaces as
    `TypeError: run() got an unexpected keyword argument 'file_path'`, which
    models read as "the tool is broken" instead of "fix the argument".
    """
    if not isinstance(tool_input, dict):
        return (
            f"Error: los argumentos de `{tool.name}` deben ser un objeto JSON, "
            f"se recibió {type(tool_input).__name__}."
        )

    schema = tool.parameters or {}
    props: dict = schema.get("properties") or {}
    required: list = schema.get("required") or []
    accepted = sorted(props.keys())

    missing = [k for k in required if k not in tool_input]
    unknown = [k for k in tool_input if k not in props] if props else []

    problems: list[str] = []
    if missing:
        problems.append(
            "faltan parámetros obligatorios: " + ", ".join(f"`{k}`" for k in missing)
        )
    if unknown:
        problems.append(
            "parámetros no reconocidos: " + ", ".join(f"`{k}`" for k in unknown)
        )

    # Primitive type checks only — enough to catch the common mistakes without
    # pulling in a full JSON Schema validator.
    for key, value in tool_input.items():
        spec = props.get(key)
        if not isinstance(spec, dict) or value is None:
            continue
        expected = spec.get("type")
        if not isinstance(expected, str):
            continue
        allowed = _JSON_TYPES.get(expected)
        if not allowed:
            continue
        # bool is a subclass of int in Python — don't let True pass as integer.
        if expected in ("integer", "number") and isinstance(value, bool):
            problems.append(f"`{key}` debe ser {expected}, se recibió boolean")
            continue
        if not isinstance(value, allowed):
            problems.append(
                f"`{key}` debe ser {expected}, se recibió {type(value).__name__}"
            )

    if not problems:
        return None

    return (
        f"Error: llamada inválida a `{tool.name}` — "
        + "; ".join(problems)
        + f". Parámetros aceptados: {', '.join(accepted) or '(ninguno)'}"
        + (f". Obligatorios: {', '.join(required)}" if required else "")
        + ". Corrige la llamada y vuelve a intentarlo."
    )
