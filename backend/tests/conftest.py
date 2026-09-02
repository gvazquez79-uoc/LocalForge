"""Fixtures compartidas del banco de invariantes del agente.

El objetivo de este directorio no es cobertura: es fijar los contratos que se
han roto en silencio alguna vez —el emparejamiento tool_use/tool_result, la
validación de argumentos, la preservación de la indentación— para que no
vuelvan a romperse sin que nadie se entere.

Ejecutar:  py -3 -m pytest backend/tests/
"""
from __future__ import annotations

import pytest

from backend.models.base import BaseModelAdapter, StreamEvent
from backend.tools.base import BaseTool


class FakeAdapter(BaseModelAdapter):
    """Adaptador programable: devuelve turnos predefinidos, uno por iteración.

    Cada turno es un dict {text?: str, tool_calls?: [{name, input}], stop?: str}.
    Guarda en `received` la lista de mensajes con la que se le llamó en cada
    iteración, que es lo que permite comprobar cómo quedó el historial.
    """

    def __init__(self, turns: list[dict], name: str = "fake-model"):
        self.model_name = name
        self.temperature = 0.0
        self._turns = list(turns)
        self.received: list[list[dict]] = []

    async def stream_chat(self, messages, tools, system):
        self.received.append([dict(m) for m in messages])
        turn = self._turns.pop(0) if self._turns else {"text": "listo", "stop": "end_turn"}

        if turn.get("text"):
            yield StreamEvent(type="text_delta", data={"text": turn["text"]})

        calls = turn.get("tool_calls") or []
        for i, c in enumerate(calls):
            yield StreamEvent(type="tool_call", data={
                "id": c.get("id") or f"call_{len(self.received)}_{i}",
                "name": c["name"],
                "input": c.get("input") or {},
            })

        yield StreamEvent(type="done", data={
            "stop_reason": turn.get("stop") or ("tool_calls" if calls else "end_turn"),
        })


class FakeAnthropicAdapter(FakeAdapter):
    """Mismo comportamiento, pero el loop lo tratará como Anthropic.

    La detección es `"anthropic" in type(adapter).__name__.lower()`, así que el
    nombre de la clase es lo que decide el formato del historial.
    """


class ScriptedTool(BaseTool):
    """Tool con resultado fijo y registro de invocaciones."""

    def __init__(self, name: str, result: str = "ok", parameters: dict | None = None):
        self.name = name
        self.description = f"tool de prueba {name}"
        self.parameters = parameters or {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
        self._result = result
        self.calls: list[dict] = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._result


@pytest.fixture(autouse=True)
def _neutral_agent_env(monkeypatch, tmp_path):
    """Aísla el loop del entorno real: sin memoria persistente, sin tools de
    verdad, sin instrucciones de proyecto y con un límite de iteraciones bajo."""
    import backend.agent.loop as loop
    from backend.config import LocalForgeConfig

    cfg = LocalForgeConfig()
    cfg.agent.max_iterations = 6
    cfg.agent.compact_threshold = 10_000_000   # nunca compactar en los tests
    monkeypatch.setattr(loop, "get_config", lambda: cfg)
    monkeypatch.setattr(loop, "get_enabled_tools", lambda: [])
    monkeypatch.setattr(loop, "_load_memory", lambda: "")
    monkeypatch.setattr(loop, "_load_project_instructions", lambda wd: "")
    # El loop importa has_permission de forma perezosa dentro de la función, así
    # que hay que parchearlo en su módulo de origen, no en loop.
    import backend.db.permissions_store as perms
    monkeypatch.setattr(perms, "has_permission", _always_granted)
    return cfg


async def _always_granted(project_path, permission_type):
    return True


async def collect(gen) -> list[StreamEvent]:
    """Consume un async generator de StreamEvents."""
    return [ev async for ev in gen]
