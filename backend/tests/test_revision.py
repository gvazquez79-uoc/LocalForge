"""Defectos encontrados por la revisión adversarial de los propios cambios.

Cada test de aquí corresponde a un hallazgo confirmado: son las cosas que la
primera versión de esta intervención rompía.
"""
from __future__ import annotations

import os
import sys

import pytest

from backend.agent.loop import _parse_inline_tool_calls, _trim_param_value
from backend.tools.filesystem import (
    EditFileTool, ReadFileTool, WriteFileTool, _conv_working_dir,
)
from backend.tools.terminal import _clamp

read = ReadFileTool()
write = WriteFileTool()
edit = EditFileTool()


@pytest.fixture
def wd(tmp_path):
    token = _conv_working_dir.set(tmp_path)
    yield tmp_path
    _conv_working_dir.reset(token)


# ── Parser inline: indentación de las etiquetas vs del contenido ────────────

def test_un_escalar_indentado_no_arrastra_la_sangria():
    """Los modelos locales indentan las etiquetas. Una ruta con cuatro espacios
    delante no existe en el disco."""
    txt = ("<function=read_file>\n  <parameter=path>\n"
           "    /home/u/proy/app.py\n  </parameter>\n</function>")
    assert _parse_inline_tool_calls(txt)[0]["input"]["path"] == "/home/u/proy/app.py"


def test_un_valor_multilinea_conserva_su_indentacion():
    txt = ("<function=edit_file><parameter=path>a.py</parameter>"
           "<parameter=old_string>\n    if x:\n        y()\n</parameter></function>")
    args = _parse_inline_tool_calls(txt)[0]["input"]
    assert args["old_string"] == "    if x:\n        y()"
    assert args["path"] == "a.py"


def test_los_enteros_indentados_siguen_coercionando():
    txt = ("<function=git_log><parameter=path>.</parameter>"
           "<parameter=n>\n  10\n</parameter></function>")
    assert _parse_inline_tool_calls(txt)[0]["input"]["n"] == 10


# ── Escritura sobre ficheros que no son UTF-8 ───────────────────────────────

async def test_sobrescribir_un_fichero_no_utf8_no_revienta(wd):
    """_read_source lanzaba UnicodeDecodeError y la tool moría con
    'Tool error', cuando antes del cambio esto funcionaba."""
    f = wd / "datos.csv"
    f.write_bytes("año;precio\n".encode("cp1252"))

    out = await write.run(path=str(f), content="a;b\n")

    assert "Error" not in out
    assert f.read_text(encoding="utf-8") == "a;b\n"


async def test_append_sobre_un_fichero_no_utf8_avisa_en_vez_de_truncar(wd):
    """En append no se puede degradar a before='': truncaría el fichero."""
    f = wd / "log.txt"
    original = "línea previa\n".encode("cp1252")
    f.write_bytes(original)

    out = await write.run(path=str(f), content="nueva\n", mode="append")

    assert "no es UTF-8" in out
    assert f.read_bytes() == original, "el fichero no debía tocarse"


# ── La puerta de sintaxis no puede impedir construir por trozos ─────────────

async def test_append_puede_construir_un_py_por_trozos(wd):
    f = wd / "x.py"
    out1 = await write.run(path=str(f), content="def f():\n", mode="append")
    out2 = await write.run(path=str(f), content="    return 1\n", mode="append")

    assert "roto" not in out1 and "roto" not in out2
    assert f.read_text(encoding="utf-8") == "def f():\n    return 1\n"


async def test_un_fichero_vacio_no_cuenta_como_sano(wd):
    """before='' compila, así que la puerta bloqueaba el primer trozo."""
    f = wd / "y.py"
    f.write_text("", encoding="utf-8")
    out = await write.run(path=str(f), content="def f():\n")
    assert "roto" not in out


# ── El BOM no puede desalinear read_file y edit_file ────────────────────────

async def test_con_BOM_el_old_string_de_read_file_casa_en_edit_file(wd):
    f = wd / "z.py"
    f.write_bytes(b"\xef\xbb\xbfimport os\n")

    leido = await read.run(path=str(f))
    assert "\ufeff" not in leido, "read_file no debe devolver el BOM al modelo"

    out = await edit.run(path=str(f), old_string="import os", new_string="import sys")
    assert "Editado" in out
    assert f.read_bytes().startswith(b"\xef\xbb\xbf"), "el BOM debe seguir en disco"


# ── Metadatos del fichero tras la escritura atómica ─────────────────────────

@pytest.mark.skipif(sys.platform == "win32", reason="permisos POSIX")
async def test_editar_conserva_el_bit_de_ejecucion(wd):
    f = wd / "deploy.sh"
    f.write_text("echo uno\n", encoding="utf-8")
    os.chmod(f, 0o755)

    await edit.run(path=str(f), old_string="uno", new_string="dos")

    assert os.stat(f).st_mode & 0o777 == 0o755


async def test_no_queda_ningun_fichero_temporal(wd):
    f = wd / "a.py"
    f.write_text("a = 1\n", encoding="utf-8")
    await edit.run(path=str(f), old_string="a = 1", new_string="a = 2")
    assert not list(wd.glob("*.localforge-tmp"))


# ── Recorte de salida por los dos extremos ──────────────────────────────────

def test_el_recorte_conserva_el_final_donde_estan_los_errores():
    """Un build de vite pone el banner al principio y los errores al final:
    recortar solo por la cabeza tiraba justo lo que importa."""
    texto = "BANNER" + "x" * 50_000 + "ERROR: build failed"
    out = _clamp(texto, 4000)
    assert out.endswith("ERROR: build failed")
    assert out.startswith("BANNER")
    assert len(out) < 5000


# ── La huella de verificación aguanta timestamps ────────────────────────────

def test_la_huella_ignora_fechas_y_horas():
    from backend.agent.verify import _fingerprint
    a = "### pytest — FALLA\n2026-09-02 18:30:01 ERROR algo\nassert 1 == 2"
    b = "### pytest — FALLA\n2026-09-02 19:47:55 ERROR algo\nassert 1 == 2"
    assert _fingerprint(a) == _fingerprint(b)


def test_la_huella_sigue_distinguiendo_fallos_distintos():
    from backend.agent.verify import _fingerprint
    a = "### pytest — FALLA\nassert 1 == 2"
    b = "### pytest — FALLA\nassert 3 == 4"
    assert _fingerprint(a) != _fingerprint(b)
