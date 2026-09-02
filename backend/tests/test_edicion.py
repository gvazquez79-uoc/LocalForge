"""Invariantes de la escritura y la edición de ficheros.

El fallo caro de un agente de programación no es "no encontré el texto": es
corromper el fichero, o dejar al modelo sin información para reintentar.
"""
from __future__ import annotations

import pytest

from backend.tools.filesystem import EditFileTool, WriteFileTool, _conv_working_dir


@pytest.fixture
def wd(tmp_path, monkeypatch):
    """Directorio de trabajo permitido, para saltar el sandbox de rutas."""
    token = _conv_working_dir.set(tmp_path)
    yield tmp_path
    _conv_working_dir.reset(token)


edit = EditFileTool()
write = WriteFileTool()


# ── Preservación de finales de línea ────────────────────────────────────────

async def test_editar_un_fichero_LF_no_lo_convierte_a_CRLF(wd):
    """El bug silencioso más caro: en Windows, write_text traducía \\n a \\r\\n,
    así que una edición de una línea reescribía el fichero entero."""
    f = wd / "a.py"
    f.write_bytes(b"uno\ndos\ntres\n")

    await edit.run(path=str(f), old_string="dos", new_string="DOS")

    raw = f.read_bytes()
    assert b"\r\n" not in raw, "se colaron CRLF en un fichero LF"
    assert raw == b"uno\nDOS\ntres\n"


async def test_editar_un_fichero_CRLF_lo_mantiene_CRLF(wd):
    f = wd / "b.py"
    f.write_bytes(b"uno\r\ndos\r\ntres\r\n")

    await edit.run(path=str(f), old_string="dos", new_string="DOS")

    raw = f.read_bytes()
    assert raw == b"uno\r\nDOS\r\ntres\r\n"
    assert raw.count(b"\r\n") == 3


async def test_el_BOM_sobrevive_a_una_edicion(wd):
    f = wd / "c.py"
    f.write_bytes(b"\xef\xbb\xbfuno\ndos\n")

    await edit.run(path=str(f), old_string="dos", new_string="DOS")

    assert f.read_bytes().startswith(b"\xef\xbb\xbf")


async def test_write_file_conserva_el_EOL_del_fichero_existente(wd):
    f = wd / "d.txt"
    f.write_bytes(b"viejo\r\n")
    await write.run(path=str(f), content="nuevo\notro\n")
    assert f.read_bytes() == b"nuevo\r\notro\r\n"


# ── Diagnóstico cuando old_string no casa ───────────────────────────────────

async def test_fallo_de_match_explica_la_indentacion(wd):
    """El modelo manda el fragmento con la indentación equivocada — el caso
    más común cuando reconstruye código de memoria en vez de leerlo."""
    f = wd / "e.py"
    f.write_text("def f():\n    return 1\n", encoding="utf-8")

    out = await edit.run(
        path=str(f),
        old_string="        return 1",   # 8 espacios; el fichero tiene 4
        new_string="        return 2",
    )

    assert "no encontrado" in out
    assert "indentación" in out           # nombra la causa probable
    assert "return 1" in out              # y enseña el texto real del fichero
    assert "|" in out                     # con números de línea
    # y no ha tocado el fichero
    assert f.read_text(encoding="utf-8") == "def f():\n    return 1\n"


async def test_fallo_de_match_detecta_espacios_finales(wd):
    f = wd / "f.py"
    f.write_text("alpha   \nbeta\n", encoding="utf-8")

    out = await edit.run(path=str(f), old_string="alpha\nbeta", new_string="x")
    assert "espacios al final" in out


async def test_ambiguedad_dice_en_que_lineas(wd):
    f = wd / "g.py"
    f.write_text("x = 1\ny = 2\nx = 1\n", encoding="utf-8")

    out = await edit.run(path=str(f), old_string="x = 1", new_string="x = 9")
    assert "2 veces" in out
    assert "líneas 1, 3" in out
    # y no ha tocado nada
    assert f.read_text(encoding="utf-8") == "x = 1\ny = 2\nx = 1\n"


async def test_edicion_nula_se_rechaza(wd):
    f = wd / "h.py"
    f.write_text("a\n", encoding="utf-8")
    out = await edit.run(path=str(f), old_string="a", new_string="a")
    assert "idénticos" in out


# ── Evidencia del cambio, no "Success" ──────────────────────────────────────

async def test_edit_devuelve_un_diff(wd):
    f = wd / "i.py"
    f.write_text("uno\ndos\ntres\n", encoding="utf-8")

    out = await edit.run(path=str(f), old_string="dos", new_string="DOS")

    assert "-dos" in out and "+DOS" in out


async def test_sobrescribir_devuelve_un_diff(wd):
    f = wd / "j.py"
    f.write_text("viejo\n", encoding="utf-8")
    out = await write.run(path=str(f), content="nuevo\n")
    assert "-viejo" in out and "+nuevo" in out


async def test_crear_fichero_nuevo_lo_dice(wd):
    out = await write.run(path=str(wd / "k.py"), content="hola\n")
    assert "Creado" in out


# ── write_file deja de crear árboles por una errata ─────────────────────────

async def test_write_no_crea_un_arbol_entero_por_un_typo(wd):
    out = await write.run(path=str(wd / "src" / "componets" / "x.ts"), content="a")
    assert "no existe" in out
    assert not (wd / "src").exists()


async def test_write_crea_un_solo_nivel_y_lo_dice(wd):
    (wd / "src").mkdir()
    out = await write.run(path=str(wd / "src" / "components" / "x.ts"), content="a")
    assert "creado el directorio" in out
    assert (wd / "src" / "components" / "x.ts").read_text(encoding="utf-8") == "a"
