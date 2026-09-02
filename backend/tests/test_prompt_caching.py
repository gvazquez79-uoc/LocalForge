"""Forma de la petición a Anthropic: puntos de caché y contadores.

NOTA: estos tests comprueban que la petición SALE bien formada. Que la caché
realmente acierte solo se puede medir contra la API real mirando
`cache_read_input_tokens` — no se ha podido comprobar (cuenta sin créditos).
El invalidador típico no da error: simplemente devuelve cache_read=0.
"""
from __future__ import annotations

import sys
import types

import pytest

from backend.models.anthropic import AnthropicAdapter


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5
    cache_read_input_tokens = 900
    cache_creation_input_tokens = 0


class _FakeFinal:
    stop_reason = "end_turn"
    content: list = []
    usage = _FakeUsage()


class _FakeStream:
    def __init__(self, captured, kwargs):
        captured.append(kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    @property
    def text_stream(self):
        async def gen():
            yield "OK"
        return gen()

    async def get_final_message(self):
        return _FakeFinal()


@pytest.fixture
def captured(monkeypatch):
    """Sustituye el SDK de Anthropic por un doble que captura los kwargs."""
    calls: list[dict] = []

    class _Messages:
        def stream(self, **kwargs):
            return _FakeStream(calls, kwargs)

    class _Client:
        def __init__(self, api_key=None):
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.AsyncAnthropic = _Client
    for name in ("AuthenticationError", "BadRequestError", "RateLimitError",
                 "NotFoundError", "APIConnectionError"):
        setattr(fake, name, type(name, (Exception,), {}))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return calls


TOOLS = [
    {"name": "read_file", "description": "lee", "input_schema": {"type": "object"}},
    {"name": "write_file", "description": "escribe", "input_schema": {"type": "object"}},
]


async def _run(adapter, tools=TOOLS, system="prompt de sistema"):
    return [ev async for ev in adapter.stream_chat(
        [{"role": "user", "content": "hola"}], tools, system)]


async def test_el_system_prompt_lleva_punto_de_cache(captured):
    await _run(AnthropicAdapter("claude-x", "sk-test"))
    system = captured[0]["system"]
    assert isinstance(system, list), "el system debe ir en bloques para poder cachearlo"
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[0]["text"] == "prompt de sistema"


async def test_solo_la_ultima_tool_lleva_el_punto_de_cache(captured):
    """El breakpoint cachea todo lo anterior; ponerlo en cada tool malgasta
    puntos de caché (el máximo son 4)."""
    await _run(AnthropicAdapter("claude-x", "sk-test"))
    tools = captured[0]["tools"]
    assert "cache_control" not in tools[0]
    assert tools[-1]["cache_control"] == {"type": "ephemeral"}


async def test_no_se_mutan_las_tools_del_llamante(captured):
    """El loop reutiliza la misma lista de schemas en cada iteración: mutarla
    aquí iría acumulando cache_control y cambiando el prefijo cada vez."""
    tools = [dict(t) for t in TOOLS]
    await _run(AnthropicAdapter("claude-x", "sk-test"), tools=tools)
    assert all("cache_control" not in t for t in tools)


async def test_sin_tools_no_revienta(captured):
    await _run(AnthropicAdapter("claude-x", "sk-test"), tools=[])
    assert "tools" not in captured[0]


async def test_el_prefijo_es_identico_entre_llamadas(captured):
    """Si el prefijo cambia entre iteraciones, la caché nunca acierta y no hay
    ningún error que lo delate."""
    adapter = AnthropicAdapter("claude-x", "sk-test")
    await _run(adapter)
    await _run(adapter)
    assert captured[0]["system"] == captured[1]["system"]
    assert captured[0]["tools"] == captured[1]["tools"]


async def test_los_contadores_de_cache_llegan_al_evento_usage(captured):
    events = await _run(AnthropicAdapter("claude-x", "sk-test"))
    usage = next(e for e in events if e.type == "usage")
    assert usage.data["cache_read_tokens"] == 900
    assert usage.data["cache_write_tokens"] == 0
    assert usage.data["input_tokens"] == 10
