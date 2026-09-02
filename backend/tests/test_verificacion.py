"""El bucle de verificación: detección del proyecto y realimentación al modelo."""
from __future__ import annotations

import json
import sys

import pytest

import backend.agent.verify as v
from backend.agent.loop import run_agent
from backend.agent.verify import Stage, _relevant, detect_project_profile, run_verification
from backend.tools.filesystem import _conv_working_dir
from conftest import FakeAdapter, ScriptedTool, collect


@pytest.fixture
def wd(tmp_path):
    token = _conv_working_dir.set(tmp_path)
    yield tmp_path
    _conv_working_dir.reset(token)


def _finge_venv(tmp_path):
    """Estructura de un venv del proyecto (sin intérprete real dentro)."""
    sub = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    exe = tmp_path / ".venv" / sub
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("", encoding="utf-8")
    return exe


def _finge_repo_localforge(tmp_path):
    """Marca el directorio como el propio repo de LocalForge — el único caso en
    el que usar el intérprete del backend es lo correcto."""
    (tmp_path / "backend" / "agent").mkdir(parents=True, exist_ok=True)
    (tmp_path / "backend" / "agent" / "loop.py").write_text("", encoding="utf-8")


def _proyecto_python_con_tests(tmp_path, falla: bool):
    (tmp_path / "requirements.txt").write_text("x\n", encoding="utf-8")
    _finge_repo_localforge(tmp_path)
    tests = tmp_path / "tests"
    tests.mkdir()
    cuerpo = "assert 1 == 2" if falla else "assert True"
    (tests / "test_x.py").write_text(f"def test_x():\n    {cuerpo}\n", encoding="utf-8")


# ── Qué intérprete se usa ───────────────────────────────────────────────────

def test_con_venv_propio_se_usa_el_interprete_del_proyecto(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "_has_module", lambda py, mod: mod == "pytest")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    exe = _finge_venv(tmp_path)

    profile = detect_project_profile(tmp_path)

    assert "python" in profile.kind
    cmd = next(s.command for s in profile.stages if s.name == "pytest")
    assert str(exe) in cmd, "debe usar el intérprete DEL PROYECTO, no el del backend"


def test_sin_entorno_propio_no_se_genera_etapa_pytest(tmp_path):
    """Lanzar los tests del proyecto con el intérprete de LocalForge produce
    ModuleNotFoundError en cascada: fallos que no son del código y que
    empujarían al modelo a 'arreglar' algo que ya funcionaba."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    assert not any(s.name == "pytest" for s in detect_project_profile(tmp_path).stages)


def test_el_propio_repo_si_usa_el_interprete_del_backend(tmp_path):
    """LocalForge es el único proyecto donde el intérprete del backend ES el
    correcto: es justo donde están sus dependencias."""
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    _finge_repo_localforge(tmp_path)

    cmd = next(s.command for s in detect_project_profile(tmp_path).stages if s.name == "pytest")
    assert "-m pytest" in cmd
    assert sys.executable.replace("\\", "/") in cmd.replace("\\", "/")


# ── Detección del perfil ────────────────────────────────────────────────────

def test_proyecto_node_con_tsconfig_genera_typecheck(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"build": "vite build", "lint": "eslint ."}}), encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")

    names = [s.name for s in detect_project_profile(tmp_path).stages]
    assert "typecheck" in names
    assert "npm build" in names      # sin script test, el build es la señal
    assert "lint" in names


def test_lint_no_bloquea_pero_los_tests_si(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest", "lint": "eslint ."}}), encoding="utf-8")
    stages = {s.name: s for s in detect_project_profile(tmp_path).stages}
    assert stages["npm test"].blocking is True
    assert stages["lint"].blocking is False


def test_directorio_vacio_no_genera_etapas(tmp_path):
    profile = detect_project_profile(tmp_path)
    assert profile.stages == []
    assert profile.kind == "desconocido"


# ── Relevancia: no correr el build por haber tocado un .py ──────────────────

def test_editar_python_no_dispara_el_build_de_node():
    assert _relevant(Stage("npm build", "x"), {"a.py"}) is False
    assert _relevant(Stage("pytest", "x"), {"a.py"}) is True


def test_editar_typescript_no_dispara_pytest():
    assert _relevant(Stage("pytest", "x"), {"src/a.tsx"}) is False
    assert _relevant(Stage("typecheck", "x"), {"src/a.tsx"}) is True


# ── La verificación respeta la configuración de seguridad ───────────────────

async def test_terminal_desactivada_no_verifica_nada(tmp_path, monkeypatch):
    """Apagar la terminal es exactamente la petición de 'no ejecutes nada en mi
    máquina'. La verificación no puede ser una puerta trasera a la shell."""
    _proyecto_python_con_tests(tmp_path, falla=True)

    from backend.config import LocalForgeConfig
    cfg = LocalForgeConfig()
    cfg.tools.terminal.enabled = False
    import backend.config as config_mod
    monkeypatch.setattr(config_mod, "get_config", lambda: cfg)

    ok, summary, _ = await run_verification(str(tmp_path), {"a.py"})
    assert ok is True and summary == ""


# ── Ejecución real ──────────────────────────────────────────────────────────

async def test_verificacion_detecta_un_test_que_falla(tmp_path):
    _proyecto_python_con_tests(tmp_path, falla=True)

    ok, summary, fingerprint = await run_verification(str(tmp_path), {"a.py"})

    assert ok is False
    assert "pytest" in summary
    assert fingerprint


async def test_la_huella_es_estable_entre_ejecuciones(tmp_path):
    """Si la huella cambia entre dos ejecuciones idénticas, la protección
    anti-bucle no salta nunca. Duraciones, rutas y timestamps la rompían."""
    _proyecto_python_con_tests(tmp_path, falla=True)

    _, _, f1 = await run_verification(str(tmp_path), {"a.py"})
    _, _, f2 = await run_verification(str(tmp_path), {"a.py"})

    assert f1 == f2 and f1


async def test_verificacion_pasa_cuando_los_tests_pasan(tmp_path):
    _proyecto_python_con_tests(tmp_path, falla=False)

    ok, summary, _ = await run_verification(str(tmp_path), {"a.py"})

    assert ok is True
    assert "Verificación OK" in summary


async def test_sin_etapas_la_verificacion_no_molesta(tmp_path):
    ok, summary, _ = await run_verification(str(tmp_path), {"a.py"})
    assert ok is True and summary == ""


# ── Integración con el loop ─────────────────────────────────────────────────

async def test_el_loop_devuelve_el_fallo_al_modelo(tmp_path, _neutral_agent_env):
    """El agente dice que terminó; la verificación falla; el error se le inyecta."""
    _proyecto_python_con_tests(tmp_path, falla=True)

    writer = ScriptedTool("write_file", result="Creado a.py")
    adapter = FakeAdapter([
        {"tool_calls": [{"name": "write_file", "input": {"path": str(tmp_path / "a.py")}}]},
        {"text": "Ya está, tarea terminada.", "stop": "end_turn"},
        {"text": "Ahora sí.", "stop": "end_turn"},
    ])

    events = await collect(run_agent(
        [{"role": "user", "content": "escribe a.py"}], adapter,
        extra_tools=[writer], working_directory=str(tmp_path),
    ))

    assert any(e.type == "verifying" for e in events), "no se emitió el evento de verificación"
    assert len(adapter.received) >= 3
    ultimo = adapter.received[2][-1]
    assert ultimo["role"] == "user"
    assert "verificación del proyecto falla" in ultimo["content"]
    assert "pytest" in ultimo["content"]


async def test_el_loop_no_verifica_si_no_se_escribio_nada(tmp_path, _neutral_agent_env):
    _proyecto_python_con_tests(tmp_path, falla=True)

    adapter = FakeAdapter([{"text": "Hola, ¿qué tal?", "stop": "end_turn"}])
    events = await collect(run_agent(
        [{"role": "user", "content": "hola"}], adapter, working_directory=str(tmp_path),
    ))
    assert not any(e.type == "verifying" for e in events)


async def test_una_escritura_fallida_no_dispara_verificacion(tmp_path, _neutral_agent_env):
    """_files_written se rellenaba ANTES de ejecutar la tool, así que un
    write_file rechazado disparaba igualmente toda la verificación."""
    _proyecto_python_con_tests(tmp_path, falla=True)

    fallido = ScriptedTool("write_file", result="Error: el directorio no existe")
    adapter = FakeAdapter([
        {"tool_calls": [{"name": "write_file", "input": {"path": str(tmp_path / "x.py")}}]},
        {"text": "no pude", "stop": "end_turn"},
    ])
    events = await collect(run_agent(
        [{"role": "user", "content": "escribe"}], adapter,
        extra_tools=[fallido], working_directory=str(tmp_path),
    ))
    assert not any(e.type == "verifying" for e in events)


async def test_dos_fallos_identicos_cortan_el_bucle(tmp_path, _neutral_agent_env):
    """Si el modelo no arregla nada, no se queman las 40 iteraciones."""
    _proyecto_python_con_tests(tmp_path, falla=True)

    writer = ScriptedTool("write_file", result="ok")
    adapter = FakeAdapter([
        {"tool_calls": [{"name": "write_file", "input": {"path": str(tmp_path / "a.py")}}]},
        {"text": "terminado", "stop": "end_turn"},
        {"tool_calls": [{"name": "write_file", "input": {"path": str(tmp_path / "a.py")}}]},
        {"text": "ahora sí terminado", "stop": "end_turn"},
        {"text": "y ahora", "stop": "end_turn"},
    ])

    events = await collect(run_agent(
        [{"role": "user", "content": "arregla"}], adapter,
        extra_tools=[writer], working_directory=str(tmp_path),
    ))

    texto = "".join(e.data.get("text", "") for e in events if e.type == "text_delta")
    assert "sigue fallando" in texto
    assert len(adapter.received) <= 5
