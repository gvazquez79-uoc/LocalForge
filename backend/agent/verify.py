"""Bucle de verificación: comprobar que lo que el agente escribió funciona.

Hasta ahora, después de que el agente escribiera código no ocurría nada. El
único mecanismo era el auto-retry cuando `execute_command` devolvía un exit code
distinto de cero — es decir, solo si el propio modelo se acordaba de ejecutar
algo. Esto cierra el bucle: al terminar un turno en el que se han escrito
ficheros, se ejecutan las comprobaciones que el proyecto realmente tiene, y si
fallan el resultado vuelve al modelo para que corrija.

El perfil del proyecto se detecta por ficheros marcadores, sin LLM.
"""
from __future__ import annotations

import hashlib
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Techo de la salida que se devuelve al modelo por etapa.
MAX_STAGE_OUTPUT = 4000


@dataclass
class Stage:
    """Una comprobación ejecutable."""
    name: str
    command: str
    # Las etapas "duras" (tests, typecheck) bloquean; las blandas (lint) informan.
    blocking: bool = True


@dataclass
class ProjectProfile:
    kind: str
    stages: list[Stage] = field(default_factory=list)

    def describe(self) -> str:
        if not self.stages:
            return f"{self.kind}: sin comprobaciones detectadas"
        return f"{self.kind}: " + ", ".join(s.name for s in self.stages)


def _project_python(wd: Path) -> tuple[str, Path | None]:
    """El intérprete DEL PROYECTO, no el del backend.

    Un proyecto Python normal tiene su propio venv con sus dependencias. Lanzar
    sus tests con el intérprete que ejecuta LocalForge produce ModuleNotFoundError
    en cascada — fallos que no son del código y que empujarían al modelo a
    "arreglar" algo que funciona.

    Devuelve (comando, ruta_del_intérprete_o_None). None significa que no hemos
    encontrado un entorno del proyecto y estamos cayendo al del backend.
    """
    for rel in (".venv", "venv", "env", ".virtualenv"):
        for sub in ("Scripts/python.exe", "bin/python", "bin/python3"):
            cand = wd / rel / sub
            if cand.exists():
                return f'"{cand}"', cand
    return f'"{sys.executable}"', None


def _has_module(python_cmd: str, mod: str) -> bool:
    """¿Tiene ESE intérprete el módulo?

    Antes se consultaba `importlib.util.find_spec` sobre el proceso del backend
    y luego se ejecutaba otro intérprete distinto, así que la comprobación y la
    ejecución hablaban de entornos diferentes.
    """
    import subprocess
    try:
        r = subprocess.run(
            f'{python_cmd} -c "import {mod}"',
            shell=True, capture_output=True, timeout=25,
        )
        return r.returncode == 0
    except Exception:
        return False


# Señales de que la comprobación no se pudo EJECUTAR, frente a que el código
# esté mal. Reportar esto al modelo como "tus tests fallan" es mentirle.
_ENV_BROKEN = (
    "ModuleNotFoundError",
    "No module named",
    "ImportError while loading conftest",
    "is not recognized as an internal or external command",
    "command not found",
    "ENOENT",
)


def _npm_scripts(pkg: Path) -> dict:
    import json
    try:
        return json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}
    except Exception:
        return {}


def detect_project_profile(working_dir: str | Path) -> ProjectProfile:
    """Deducir qué se puede ejecutar para comprobar este proyecto."""
    wd = Path(working_dir).expanduser()
    if not wd.is_dir():
        return ProjectProfile(kind="desconocido")

    stages: list[Stage] = []
    kinds: list[str] = []
    py, venv = _project_python(wd)

    # ── Python ──
    has_py_marker = any((wd / f).exists() for f in
                        ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg"))
    test_dirs = [d for d in ("tests", "test", "backend/tests") if (wd / d).is_dir()]
    if has_py_marker or test_dirs:
        kinds.append("python")
        # Sin venv propio, el intérprete es el del backend: solo tiene sentido
        # si el proyecto ES LocalForge. En cualquier otro caso los tests
        # fallarían por dependencias ausentes, no por el código.
        own_repo = (wd / "backend" / "agent" / "loop.py").exists()
        usable = venv is not None or own_repo
        if test_dirs and usable and _has_module(py, "pytest"):
            stages.append(Stage("pytest", f"{py} -m pytest {test_dirs[0]} -q"))
        if usable and _has_module(py, "ruff"):
            stages.append(Stage("ruff", f"{py} -m ruff check .", blocking=False))

    # ── Node / TypeScript ──
    pkg = wd / "package.json"
    if pkg.exists():
        kinds.append("node")
        scripts = _npm_scripts(pkg)
        if (wd / "tsconfig.json").exists():
            stages.append(Stage("typecheck", "npx tsc --noEmit"))
        if "test" in scripts:
            stages.append(Stage("npm test", "npm test --silent"))
        elif "build" in scripts:
            # Sin tests, el build es la única señal de que sigue compilando.
            stages.append(Stage("npm build", "npm run build"))
        if "lint" in scripts:
            stages.append(Stage("lint", "npm run lint --silent", blocking=False))

    # ── Rust / Go ──
    if (wd / "Cargo.toml").exists():
        kinds.append("rust")
        stages.append(Stage("cargo test", "cargo test --quiet"))
    if (wd / "go.mod").exists():
        kinds.append("go")
        stages.append(Stage("go test", "go test ./..."))

    return ProjectProfile(kind="+".join(kinds) or "desconocido", stages=stages)


def _relevant(stage: Stage, touched: set[str]) -> bool:
    """¿Merece la pena esta etapa dado lo que se ha tocado?

    Correr `npm run build` porque el agente editó un .py es tiempo tirado y
    ruido en el contexto.
    """
    if not touched:
        return True
    py_touched = any(p.endswith(".py") for p in touched)
    web_touched = any(p.endswith((".ts", ".tsx", ".js", ".jsx", ".json", ".css")) for p in touched)
    if stage.name in ("pytest", "ruff"):
        return py_touched
    if stage.name in ("typecheck", "npm test", "npm build", "lint"):
        return web_touched
    return True


# Ruido que cambia entre dos ejecuciones idénticas y no dice nada del fallo.
_VOLATILE = [
    # Fechas y horas: un test que imprime datetime.now() daba una huella distinta
    # en cada ejecución, así que la detección de bucle no saltaba nunca.
    re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"),
    re.compile(r"\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b"),
    re.compile(r"\bin \d+\.\d+s\b"),                 # "1 failed in 0.03s"
    re.compile(r"\b\d+\.\d+\s*(s|ms|seconds?)\b"),   # duraciones sueltas
    re.compile(r"0x[0-9a-fA-F]+"),                   # direcciones de memoria
    re.compile(r"[A-Za-z]:\\[^\s:]+|/tmp/[^\s:]+"),  # rutas temporales
    re.compile(r"\[cwd: [^\]]*\]"),
]


def _fingerprint(summary: str) -> str:
    """Identificar el FALLO, no la ejecución.

    La huella se compara entre intentos para detectar que el modelo da vueltas
    sin arreglar nada. Si incluye la duración de pytest o una ruta temporal,
    dos ejecuciones del mismo fallo dan huellas distintas y la detección nunca
    salta — que es exactamente lo que pasaba.
    """
    text = summary[:4000]
    for pattern in _VOLATILE:
        text = pattern.sub("·", text)
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


async def run_verification(
    working_dir: str,
    touched_files: set[str] | None = None,
    timeout: int = 300,
) -> tuple[bool, str, str]:
    """Ejecutar las comprobaciones del proyecto.

    Devuelve (ok, resumen, huella). La huella identifica el fallo concreto para
    que el loop pueda detectar que está reintentando lo mismo sin avanzar.
    """
    import time

    from backend.config import get_config
    from backend.tools.terminal import ExecuteCommandTool, _clamp

    # La verificación ejecuta shell. Si el usuario ha apagado la terminal, lo ha
    # hecho precisamente para que el agente no ejecute nada en su máquina — no
    # tener aquí esta comprobación convertía este bucle en una puerta trasera.
    if not get_config().tools.terminal.enabled:
        logger.info("[verify] terminal desactivada: no se verifica")
        return True, "", ""

    profile = detect_project_profile(working_dir)
    stages = [s for s in profile.stages if _relevant(s, touched_files or set())]
    if not stages:
        return True, "", ""

    runner = ExecuteCommandTool()
    failures: list[str] = []
    passed: list[str] = []
    skipped: list[str] = []

    # Presupuesto global: el timeout era POR ETAPA, así que un monorepo con siete
    # etapas podía estar más de una hora dentro de un solo await sin emitir nada.
    deadline = time.monotonic() + timeout

    for stage in stages:
        remaining = int(deadline - time.monotonic())
        if remaining <= 5:
            skipped.append(stage.name)
            continue

        logger.info("[verify] %s: %s", stage.name, stage.command)
        out = await runner.run(command=stage.command, working_dir=working_dir,
                               timeout=remaining)

        first = out.split("\n", 1)[0]
        if first.startswith("Exit code: 0"):
            passed.append(stage.name)
            continue

        # "No se pudo ejecutar" no es "tu código está mal". Reportar un timeout
        # o un entorno incompleto como fallo de tests hace que el modelo se
        # ponga a modificar código correcto.
        not_run = not first.startswith("Exit code:")
        env_broken = any(sig in out for sig in _ENV_BROKEN)
        if not_run or env_broken:
            reason = "tiempo límite" if not_run else "entorno incompleto"
            logger.warning("[verify] %s no verificable (%s)", stage.name, reason)
            skipped.append(f"{stage.name} ({reason})")
            continue

        if not stage.blocking:
            passed.append(f"{stage.name} (avisos)")
            continue

        failures.append(f"### {stage.name} — FALLA\n$ {stage.command}\n"
                        f"{_clamp(out, MAX_STAGE_OUTPUT)}")

    if not failures:
        parts = []
        if passed:
            parts.append("Verificación OK: " + ", ".join(passed))
        if skipped:
            parts.append("sin comprobar: " + ", ".join(skipped))
        return True, " · ".join(parts), ""

    summary = "\n\n".join(failures)
    if skipped:
        summary += "\n\n(sin comprobar: " + ", ".join(skipped) + ")"
    return False, summary, _fingerprint(summary)
