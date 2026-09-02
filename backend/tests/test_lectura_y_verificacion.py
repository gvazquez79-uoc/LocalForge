"""Lectura paginada, puerta de sintaxis, ledger de lecturas y terminal."""
from __future__ import annotations

import asyncio
import sys

import pytest

from backend.tools.filesystem import (
    EditFileTool, ReadFileTool, WriteFileTool,
    _conv_working_dir, _files_read, reset_file_ledger,
)
from backend.tools.terminal import ExecuteCommandTool, _clamp

read = ReadFileTool()
write = WriteFileTool()
edit = EditFileTool()
run_cmd = ExecuteCommandTool()


@pytest.fixture
def wd(tmp_path):
    token = _conv_working_dir.set(tmp_path)
    yield tmp_path
    _conv_working_dir.reset(token)


@pytest.fixture
def ledger():
    token = reset_file_ledger()
    yield
    _files_read.reset(token)


# ── read_file paginado ──────────────────────────────────────────────────────

async def test_read_file_numera_las_lineas(wd):
    f = wd / "a.py"
    f.write_text("uno\ndos\n", encoding="utf-8")
    out = await read.run(path=str(f))
    assert "1 | uno" in out and "2 | dos" in out


async def test_read_file_pagina_un_fichero_largo(wd):
    f = wd / "big.py"
    f.write_text("\n".join(f"linea {i}" for i in range(1, 5001)), encoding="utf-8")

    out = await read.run(path=str(f))

    assert "linea 2000" in out
    assert "linea 2001" not in out
    assert "de 5000" in out
    assert "offset=2001" in out            # dice cómo continuar


async def test_read_file_respeta_offset_y_limit(wd):
    f = wd / "b.py"
    f.write_text("\n".join(f"L{i}" for i in range(1, 101)), encoding="utf-8")
    out = await read.run(path=str(f), offset=50, limit=3)
    assert "50 | L50" in out and "52 | L52" in out
    assert "L53" not in out


async def test_read_file_offset_fuera_de_rango_lo_dice(wd):
    f = wd / "c.py"
    f.write_text("uno\n", encoding="utf-8")
    out = await read.run(path=str(f), offset=99)
    assert "fuera de rango" in out


async def test_read_file_recorta_lineas_gigantes(wd):
    f = wd / "min.js"
    f.write_text("x" * 50_000, encoding="utf-8")
    out = await read.run(path=str(f))
    assert len(out) < 10_000
    assert "caracteres)" in out


# ── Puerta de sintaxis ──────────────────────────────────────────────────────

async def test_no_se_persiste_un_python_roto(wd):
    f = wd / "d.py"
    original = "def f():\n    return 1\n"
    f.write_text(original, encoding="utf-8")

    out = await edit.run(path=str(f), old_string="    return 1", new_string="    return (1")

    assert "sintácticamente roto" in out
    assert "SyntaxError" in out
    assert f.read_text(encoding="utf-8") == original, "el fichero debía quedar intacto"


async def test_se_permite_reparar_un_fichero_ya_roto(wd):
    """La puerta es asimétrica: si ya estaba roto, hay que poder arreglarlo."""
    f = wd / "e.py"
    f.write_text("def f(:\n", encoding="utf-8")
    out = await write.run(path=str(f), content="def f():\n    return 1\n")
    assert "sintácticamente roto" not in out
    assert "return 1" in f.read_text(encoding="utf-8")


async def test_json_invalido_se_bloquea(wd):
    f = wd / "p.json"
    f.write_text('{"a": 1}', encoding="utf-8")
    out = await write.run(path=str(f), content='{"a": 1,}')
    assert "JSON inválido" in out
    assert f.read_text(encoding="utf-8") == '{"a": 1}'


async def test_otros_lenguajes_no_se_bloquean(wd):
    f = wd / "f.ts"
    f.write_text("const a = 1;\n", encoding="utf-8")
    out = await write.run(path=str(f), content="const a = (((;\n")
    assert "sintácticamente roto" not in out


# ── Ledger: leer antes de editar ────────────────────────────────────────────

async def test_editar_sin_haber_leido_se_rechaza(wd, ledger):
    f = wd / "g.py"
    f.write_text("a = 1\n", encoding="utf-8")

    out = await edit.run(path=str(f), old_string="a = 1", new_string="a = 2")

    assert "no has leído" in out
    assert f.read_text(encoding="utf-8") == "a = 1\n"


async def test_tras_leer_la_edicion_pasa(wd, ledger):
    f = wd / "h.py"
    f.write_text("a = 1\n", encoding="utf-8")

    await read.run(path=str(f))
    out = await edit.run(path=str(f), old_string="a = 1", new_string="a = 2")

    assert "Editado" in out
    assert f.read_text(encoding="utf-8") == "a = 2\n"


async def test_escribir_un_fichero_cuenta_como_haberlo_leido(wd, ledger):
    f = wd / "i.py"
    await write.run(path=str(f), content="a = 1\n")
    out = await edit.run(path=str(f), old_string="a = 1", new_string="a = 2")
    assert "Editado" in out


# ── Terminal ────────────────────────────────────────────────────────────────

async def test_execute_command_corre_en_el_working_dir_no_en_el_home(wd):
    """Antes el default del schema era "~", así que un comando sin working_dir
    se ejecutaba en C:\\Users\\<usuario>."""
    marker = wd / "marcador.txt"
    marker.write_text("aqui", encoding="utf-8")

    listing = "dir /b" if sys.platform == "win32" else "ls"
    out = await run_cmd.run(command=listing)

    assert "marcador.txt" in out
    assert str(wd) in out          # el resultado dice en qué cwd corrió


async def test_timeout_mata_el_proceso_de_verdad(wd):
    """No basta con devolver 'timeout': el proceso tiene que morir.

    Antes se abandonaba vivo, así que un servidor arrancado por el agente
    seguía ocupando el puerto y hacía fallar el siguiente comando por una razón
    ajena al código. El testigo es un fichero que el proceso escribiría DESPUÉS
    de dormir: si sigue vivo, aparece.
    """
    testigo = wd / "sigue_vivo.txt"
    script = (
        "import time, pathlib; time.sleep(6); "
        f"pathlib.Path(r'{testigo}').write_text('vivo')"
    )
    out = await run_cmd.run(command=f'"{sys.executable}" -c "{script}"', timeout=2)

    assert "tiempo límite" in out
    assert "segundo plano" in out          # sugiere la alternativa

    await asyncio.sleep(8)                 # más que el sleep del hijo
    assert not testigo.exists(), "el proceso sobrevivió al timeout"


async def test_exit_code_sigue_siendo_parseable(wd):
    """El auto-retry del loop hace regex sobre "Exit code: N" al principio."""
    out = await run_cmd.run(command="exit 3")
    assert out.startswith("Exit code: 3")


def test_la_salida_se_recorta_por_los_extremos():
    big = "INICIO" + "x" * 100_000 + "FINAL"
    out = _clamp(big)
    assert len(out) < 25_000
    assert out.startswith("INICIO") and out.endswith("FINAL")
