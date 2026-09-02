"""Invariantes del turno: cómo debe quedar el historial que se manda al modelo.

Cada test de aquí corresponde a un bug real que estuvo en producción.
"""
from __future__ import annotations

import json

import pytest

from backend.agent.loop import _messages_char_count, _parse_inline_tool_calls, run_agent
from backend.models.openai_compat import _convert_content_for_openai
from backend.tools.base import validate_tool_input
from conftest import FakeAdapter, FakeAnthropicAdapter, ScriptedTool, collect


# ── 1. La corrección [SISTEMA] nunca se cuela entre dos tool_result ──────────

async def _run_two_tools_first_fails(adapter_cls):
    """Turno con 2 tool calls donde la PRIMERA es un comando que falla."""
    failing = ScriptedTool(
        "execute_command",
        result="Exit code: 1\nboom",
        parameters={"type": "object", "properties": {"command": {"type": "string"}},
                    "required": ["command"]},
    )
    reading = ScriptedTool("read_file", result="contenido")

    adapter = adapter_cls([
        {"tool_calls": [
            {"name": "execute_command", "input": {"command": "false"}},
            {"name": "read_file", "input": {"path": "a.txt"}},
        ]},
        {"text": "corregido", "stop": "end_turn"},
    ])

    await collect(run_agent(
        [{"role": "user", "content": "haz dos cosas"}],
        adapter,
        extra_tools=[failing, reading],
    ))
    # El historial de la 2ª iteración es lo que de verdad se envía al modelo.
    return adapter.received[1]


@pytest.mark.parametrize("adapter_cls", [FakeAdapter, FakeAnthropicAdapter])
async def test_tool_results_quedan_consecutivos(adapter_cls):
    history = await _run_two_tools_first_fails(adapter_cls)

    roles = [m["role"] for m in history]
    tool_positions = [i for i, r in enumerate(roles) if r == "tool"]

    assert len(tool_positions) == 2, f"esperaba 2 tool_result, roles={roles}"
    assert tool_positions[1] == tool_positions[0] + 1, (
        f"un mensaje se coló entre los dos tool_result: {roles}"
    )
    # Y el aviso llega DESPUÉS, no en medio.
    assert roles[tool_positions[1] + 1] == "user"
    assert "[SISTEMA]" in history[tool_positions[1] + 1]["content"]


async def test_aviso_de_fallo_se_inyecta_una_sola_vez():
    """Dos comandos fallidos en el mismo turno no producen dos avisos."""
    failing = ScriptedTool(
        "execute_command",
        result="Exit code: 2\nboom",
        parameters={"type": "object", "properties": {"command": {"type": "string"}},
                    "required": ["command"]},
    )
    adapter = FakeAdapter([
        {"tool_calls": [
            {"name": "execute_command", "input": {"command": "a"}},
            {"name": "execute_command", "input": {"command": "b"}},
        ]},
        {"text": "ya", "stop": "end_turn"},
    ])
    await collect(run_agent([{"role": "user", "content": "x"}], adapter,
                            extra_tools=[failing]))
    history = adapter.received[1]
    avisos = [m for m in history if m["role"] == "user" and "[SISTEMA]" in str(m["content"])]
    assert len(avisos) == 1, f"esperaba 1 aviso, hay {len(avisos)}"


# ── 2. Validación de argumentos contra el schema de la tool ──────────────────

def test_parametro_inventado_no_ejecuta_la_tool():
    tool = ScriptedTool("read_file")
    msg = validate_tool_input(tool, {"file_path": "a.txt"})
    assert msg is not None
    assert "file_path" in msg          # nombra el parámetro sobrante
    assert "path" in msg               # y dice cuál era el correcto
    assert tool.calls == []            # no se ejecutó


def test_required_ausente_se_detecta():
    tool = ScriptedTool("write_file", parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    })
    msg = validate_tool_input(tool, {"path": "a.txt"})
    assert msg is not None and "content" in msg


def test_tipo_incorrecto_se_detecta():
    tool = ScriptedTool("git_log", parameters={
        "type": "object", "properties": {"n": {"type": "integer"}}, "required": [],
    })
    assert validate_tool_input(tool, {"n": "diez"}) is not None
    assert validate_tool_input(tool, {"n": True}) is not None   # bool no es int
    assert validate_tool_input(tool, {"n": 10}) is None


def test_llamada_valida_pasa():
    assert validate_tool_input(ScriptedTool("read_file"), {"path": "a.txt"}) is None


async def test_el_loop_devuelve_el_error_de_validacion_como_tool_result():
    tool = ScriptedTool("read_file")
    adapter = FakeAdapter([
        {"tool_calls": [{"name": "read_file", "input": {"file_path": "a.txt"}}]},
        {"text": "vale", "stop": "end_turn"},
    ])
    events = await collect(run_agent([{"role": "user", "content": "lee"}], adapter,
                                     extra_tools=[tool]))
    results = [e for e in events if e.type == "tool_result"]
    assert len(results) == 1
    assert "llamada inválida" in results[0].data["result"]
    assert tool.calls == [], "la tool no debía ejecutarse con argumentos inválidos"


async def test_tool_desconocida_lista_las_disponibles():
    tool = ScriptedTool("read_file")
    adapter = FakeAdapter([
        {"tool_calls": [{"name": "no_existe", "input": {}}]},
        {"text": "vale", "stop": "end_turn"},
    ])
    events = await collect(run_agent([{"role": "user", "content": "x"}], adapter,
                                     extra_tools=[tool]))
    result = [e for e in events if e.type == "tool_result"][0].data["result"]
    assert "no existe" in result and "read_file" in result


# ── 3. El parser inline preserva la indentación y no colapsa por nombre ─────

def test_parser_inline_preserva_indentacion():
    txt = ("<function=edit_file>"
           "<parameter=path>a.py</parameter>"
           "<parameter=old_string>\n    if x:\n        y()\n</parameter>"
           "</function>")
    calls = _parse_inline_tool_calls(txt)
    assert len(calls) == 1
    assert calls[0]["input"]["old_string"] == "    if x:\n        y()"


def test_parser_inline_permite_varias_llamadas_a_la_misma_tool():
    txt = "".join(
        f"<function=edit_file><parameter=path>f{i}.py</parameter>"
        f"<parameter=old_string>a{i}</parameter></function>"
        for i in range(3)
    )
    calls = _parse_inline_tool_calls(txt)
    assert [c["input"]["path"] for c in calls] == ["f0.py", "f1.py", "f2.py"]


def test_parser_inline_colapsa_duplicados_exactos():
    txt = "<function=git_status><parameter=path>.</parameter></function>" * 2
    assert len(_parse_inline_tool_calls(txt)) == 1


def test_parser_inline_sigue_coercionando_tipos():
    txt = ("<function=git_log><parameter=path>.</parameter>"
           "<parameter=n>10</parameter><parameter=oneline>true</parameter></function>")
    args = _parse_inline_tool_calls(txt)[0]["input"]
    assert args["n"] == 10 and args["oneline"] is True


# ── 4. El camino OpenAI-compat conserva tool_calls y no escribe "None" ──────

def test_content_none_no_se_serializa_como_la_palabra_None():
    assert _convert_content_for_openai(None) == ""


async def test_rebuild_openai_conserva_tool_calls(monkeypatch):
    """Atraviesa el adaptador REAL con un SDK falso.

    La versión anterior de este test replicaba el bucle de reconstrucción dentro
    del propio test, así que habría pasado igual con el bug puesto: no ejecutaba
    ni una línea de openai_compat.py.
    """
    import sys
    import types

    capturado: list[dict] = []

    class _Completions:
        async def create(self, **kwargs):
            capturado.append(kwargs)
            async def _stream():
                return
                yield  # pragma: no cover
            return _stream()

    class _Chat:
        completions = _Completions()

    class _Client:
        def __init__(self, **kw):
            self.chat = _Chat()

    fake = types.ModuleType("openai")
    fake.AsyncOpenAI = _Client
    monkeypatch.setitem(sys.modules, "openai", fake)

    from backend.models.openai_compat import OpenAICompatAdapter

    tool_calls = [{"id": "c1", "type": "function",
                   "function": {"name": "read_file", "arguments": '{"path":"a"}'}}]
    messages = [
        {"role": "user", "content": "lee a"},
        {"role": "assistant", "content": None, "tool_calls": tool_calls},
        {"role": "tool", "tool_call_id": "c1", "content": "contenido"},
    ]

    adapter = OpenAICompatAdapter("m", "http://x/v1", "k")
    async for _ in adapter.stream_chat(messages, [], "sys"):
        pass

    enviados = capturado[0]["messages"]
    assistant = next(m for m in enviados if m["role"] == "assistant")
    assert assistant["tool_calls"] == tool_calls, "se perdieron los tool_calls"
    assert assistant["content"] is None, "content debe ser null, no la cadena 'None'"
    tool_msg = next(m for m in enviados if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "c1"


# ── 5. El contador de contexto ve lo que el agente escribe ──────────────────

def test_contador_cuenta_el_payload_de_tool_use_anthropic():
    big = "X" * 50_000
    msgs = [{"role": "assistant", "content": [
        {"type": "tool_use", "id": "1", "name": "write_file",
         "input": {"path": "a", "content": big}}]}]
    assert _messages_char_count(msgs) > 50_000


def test_contador_cuenta_los_tool_calls_openai():
    big = "X" * 50_000
    msgs = [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "1", "type": "function",
         "function": {"name": "write_file",
                      "arguments": json.dumps({"path": "a", "content": big})}}]}]
    assert _messages_char_count(msgs) > 50_000


def test_contador_cuenta_imagenes_adjuntas():
    msgs = [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": "Y" * 20_000}}]}]
    assert _messages_char_count(msgs) >= 20_000


def test_contador_no_cambia_para_texto_plano():
    assert _messages_char_count([{"role": "user", "content": "hola"}]) == 4
