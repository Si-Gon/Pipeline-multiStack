#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_agents_v2.py
================
Pipeline multi-agente (Explorer → Coder → Tester → (Tests? → Debugger) → SDD-Updater)
agnóstico de stack: backend (Maven/Gradle/Prueba.java/pytest/go/dotnet) y frontend
(HTML/JS/CSS, npm/pnpm/yarn con test o build step).

Mejoras respecto a run_agents.py (v1):
- Detección robusta de fin de agente: marcador HTML-comment canónico
  `<!-- AGENT_DONE: <agent> -->` que el agente escribe al final del
  `.opencode-context.md`, combinado con returncode==0. Si discrepancia →
  1 reintento limpio y mensajería clara en el orquestador (no "se queda en
  el aire" como ocurría en v1 al finalizar el Coder).
- Auto-detección de stack (no hay stacks hardcodeados): Maven, Gradle,
  Prueba.java standalone, pytest, npm/pnpm/yarn, go test, dotnet test,
  HTML/JS vanilla → Playwright headless como verificación de frontend.
- Bucle Coder–Tester–Debugger con guard real: el Debugger solo se invoca
  si hay `error_log` no vacío Y un runner detectado. Proyectos frontend sin
  runner terminan con "manual validation note" en lugar de false-success.
- Backup ALWAYS de `.opencode-context.md` a
  `./pipeline-artifacts/context-history/<ts>.bak` al iniciar el pipeline,
  independiente de si el usuario decide borrarlo o no.
- Log persistente por pipeline en `./pipeline-artifacts/pipeline-<ts>.log`
  con timestamp, agente y snippet de errores puntuales.
- Formato de objetivo: el contexto previo (.opencode-context.md existente)
  va PRIMERO, luego el bloque `=== OBJETIVO DEL USUARIO ===`. Las prioridades
  de contexto ya NO se mezclan con la tarea del usuario.
- Soporte `--objective-file PATH` para objetivos largos / specs grandes
  (ver P10). `--resume` salta el prompt de borrar contexto.
- Marker canónico `<!-- AGENT_DONE: <agent> -->` inyectado automáticamente
  en el prompt enviado a cada agente, así el orquestador no depende del
  free-form del modelo.

Uso
---
    # Objetivo como argumento (corto)
    python run_agents_v2.py <ruta_del_proyecto> "objetivo corto"

    # Objetivo desde archivo (specs largas, recomendado para specs como
    # mi-spec.md). Daría lo mismo que pegar el texto en argv, pero evita
    # problemas de quoting con caracteres especiales y nuevas líneas.
    python run_agents_v2.py <ruta_del_proyecto> --objective-file mi-spec.md

    # Retomar tras caída sin re-preguntar por borrar contexto
    python run_agents_v2.py <ruta_del_proyecto> "objetivo" --resume

Portabilidad (nota de compatibilidad)
--------------------------------------
Por defecto asume Windows y `OPENCODE_BIN` apunta a:
    ~\AppData\Roaming\npm\opencode.cmd

Para macOS / Linux, define la variable de entorno antes de ejecutar:
    # bash/zsh
    export OPENCODE_BIN="opencode"
    # PowerShell
    $env:OPENCODE_BIN = "opencode"
Y, en sistemas Unix, usa `opencode` (sin `.cmd`/`.ps1`) que el `PATH`
resuelva. El script lo llama con `subprocess.run([...], ...)` por lo que no
usa `shell=True`; sólo goza de la resolución de `which opencode`.
"""

import os
import re
import sys
import time
import glob
import json
import shutil
import logging
import argparse
import subprocess
import threading
from pathlib import Path

# Windows: el stdout por defecto usa cp1252, lo cual revienta al imprimir
# acentos (ej. en help strings o logs). Forzamos UTF-8.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ─── CONFIGURACIÓN DE MODELOS ─────────────────────────────────────────────────
# Configurar para otro entorno vía env vars o editando aquí abajo.
MODEL_FAST   = "opencode-go/deepseek-v4-flash"
MODEL_CODING = "opencode-go/qwen3.7-plus"
MODEL_DEBUG  = "opencode-go/kimi-k2.7-code"
MODEL_LOCAL  = "ollama/qwen3-coder:30b"   # modelo local vía Ollama (daemon 11434)

AGENT_MODELS = {
    "explorer":    MODEL_FAST,
    "coder":       MODEL_CODING,
    "tester":      MODEL_CODING,
    "debugger":    MODEL_DEBUG,
    "sdd-updater": MODEL_FAST,
}

# ─── BUDGET DE CONTEXTO INYECTADO ─────────────────────────────────────────
# Presupuesto máximo de tokens para el bloque "CONTEXTO INYECTADO" por agente.
# Es una RED DE SEGURIDAD. Default = ~9K: el contexto inyectado del coder puede
# superar 6K tokens en proyectos medianos, y el de tester/debugger ronda 1.5-2K.
# 9K está cómodamente por encima de lo normal → NO recorta tu flujo típico;
# solo actúa si el inyectado crece sin control (resume de specs largas /
# contexto acumulado). Ajustar --budget-inject si es necesario.
DEFAULT_CONTEXT_BUDGET_TOKENS = 9000
# Cuando se recorta, cuántas líneas usar para los resúmenes de bloques viejos.
BUDGET_EVICT_MAX_LINES = 8

# ─── PRECIOS DE MODELO ─────────────────────────────────────────────────────
# Costo estimado por millón de tokens (USD), entrada/salida. Son estimaciones
# razonables de los modelos opencode-go/deepseek/qwen/kimi; se pueden override
# con env vars: OC_PRICE_IN_<NOMBRE>=X.X, OC_PRICE_OUT_<NOMBRE>=X.X  (por M tok)
# Los precios se usan SOLO para reportar la factura estimada de la corrida.
MODEL_PRICING = {
    # (in $/M tok, out $/M tok)
    MODEL_FAST:   (0.25, 1.00),   # deepseek-v4-flash (económico)
    MODEL_CODING: (1.20, 2.40),   # qwen3.7-plus
    MODEL_DEBUG:  (1.00, 2.00),   # kimi-k2.7-code
    MODEL_LOCAL:  (0.00, 0.00),   # ollama local — gratis
}
# Fallback para cualquier modelo no listado.
DEFAULT_PRICING = (0.50, 1.50)

# ─── EXIT CODES POR FASE ───────────────────────────────────────────────────
# 0 = éxito completo. Cada fase fallida devuelve un código distinto para que un
# wrapper pueda relanzar DIRECTAMENTE al paso que falló (resume granular).
PHASE_EXIT_CODES = {
    "explorer":    2,
    "coder":       3,
    "tester":      4,
    "debugger":    5,
    "sdd-updater": 6,
}
STATUS_FILE = "pipeline-status.json"

# ─── CONSTANTES DEL SISTEMA ───────────────────────────────────────────────────
# IMPORTANTE (Windows): usar el .exe directo del wrapper opencode.cmd para
# evitar el rc=1 spurio que genera el .cmd por imprimir logs ANSI en stderr.
_USER_HOME = os.path.expanduser("~")
_DEFAULT_WIN_EXE = os.path.join(
    _USER_HOME, "AppData", "Roaming", "npm",
    "node_modules", "opencode-ai", "bin", "opencode.exe",
)
_DEFAULT_WIN_CMD = os.path.join(_USER_HOME, "AppData", "Roaming", "npm", "opencode.cmd")
_DEFAULT_UNIX_BIN = "opencode"

def _resolve_opencode_bin() -> str:
    """Resuelve el binario de opencode a usar, en este orden:
        1) OPENCODE_BIN explícito en env
        2) En Windows: el .exe directo si existe, sino el .cmd
        3) En Unix: 'opencode' (resuelto por PATH)
    """
    explicit = os.environ.get("OPENCODE_BIN")
    if explicit:
        return explicit
    if os.name == "nt":
        if os.path.exists(_DEFAULT_WIN_EXE):
            return _DEFAULT_WIN_EXE
        return _DEFAULT_WIN_CMD
    return _DEFAULT_UNIX_BIN

OPENCODE_BIN = _resolve_opencode_bin()
MAX_DEBUG_LOOPS     = 3
AGENT_TIMEOUT_SEC   = 20 * 60  # default para todos los agentes
# Timeout por-agente override: el coder suele hacer trabajos pesados (varias
# ediciones, specs completas) — 40min es más razonable para proyectos medianos.
# Override también vía env var: OC_AGENT_TIMEOUT_CODER=3600
def _agent_timeout(agent: str) -> int:
    env_key = f"OC_AGENT_TIMEOUT_{agent.upper().replace('-', '_')}"
    if env_key in os.environ:
        try: return int(os.environ[env_key])
        except ValueError: pass
    overrides = {
        # El coder suele hacer trabajos pesados (varias ediciones, specs 1:1)
        # — 40min es más razonable para proyectos medianos.
        "coder": 40 * 60,
    }
    return overrides.get(agent, AGENT_TIMEOUT_SEC)

CONTEXT_FILE        = ".opencode-context.md"
ARTIFACTS_DIR       = "pipeline-artifacts"
CONTEXT_HISTORY_DIR = os.path.join(ARTIFACTS_DIR, "context-history")

# Marker canónico. El orquestador lo escribe textualmente en el prompt del
# agente; se espera que el agente lo copie VERBATIM al final de su sección de
# cierre. Cada agente tiene su propio marker para evitar collisions.
AGENT_DONE_MARKER_TEMPLATE = "<!-- AGENT_DONE: {agent} -->"

# Inyección directa al final del .opencode-context.md tras cada agente: el
# orquestador inserta el marker por sí mismo para no depender de que el LLM
# presente el marker. Esto resuelve el bug P12 con 100% confiabilidad, porque
# aun si el agente no escribe, el orquestador escribe el marker una vez que la
# corrida termina OK (returncode==0).
ALLOW_ORCHESTRATOR_MARKER_INJECTION = True

# Orden del pipeline: usado por strip_foreign_markers (P13) para saber qué
# agentes vienen después del actual y detectar markers escritos
# prematuramente por otro agente.
PIPELINE_ORDER = ["explorer", "coder", "tester", "debugger", "sdd-updater"]

# ─── CATÁLOGO DE AGENTES ESPECIALIZADOS POR STACK ──────────────────────────────
# Convención: <rol>-<stack_runner>.md junto al genérico <rol>.md en el mismo
# directorio de agentes de opencode. Si no existe el especializado, se usa el
# genérico — retrocompatible, no rompe nada si nunca creas ningún archivo
# especializado.
# Ejemplo: si existe "coder-maven.md" en AGENTS_DIR, el pipeline usará ese
# en vez de "coder.md" cuando el stack detectado sea "maven".
# El ROL (explorer/coder/...) es lo único que importa para markers, PIPELINE_ORDER
# y P13 — solo el nombre del .md que se pasa a `--agent` varía según el stack.
_DEFAULT_AGENTS_DIR = os.path.join(os.path.expanduser("~"), ".config", "opencode", "agents")
AGENTS_DIR = os.environ.get("OPENCODE_AGENTS_DIR", _DEFAULT_AGENTS_DIR)

def resolve_agent(role: str, stack_runner: str) -> str:
    """Devuelve el nombre de agente a invocar: `<role>-<stack_runner>` si ese
    .md existe en AGENTS_DIR, si no el `role` genérico tal cual."""
    if not stack_runner or stack_runner == "none":
        return role
    specialized = f"{role}-{stack_runner}"
    if os.path.exists(os.path.join(AGENTS_DIR, f"{specialized}.md")):
        return specialized
    return role

# Formato del bloque que recibe el agente.
CONTEXT_PRIORITY_HEADER = (
    "[PRIORIDAD DE CONTEXTO]: El contexto relevante de corridas previas viene "
    "inyectado en este mensaje bajo 'CONTEXTO INYECTADO'. Úsalo para continuar/"
    "extender lo ya implementado — no repartas la especificación desde cero. "
    "NO leas .opencode-context.md completo salvo que necesites verificar algo "
    "puntual: el contexto inyectado ya contiene lo que necesitas."
)

OBJECTIVE_BLOCK_TEMPLATE = (
    "{context_priority}\n"
    "\n"
    "=== OBJETIVO DEL USUARIO ===\n"
    "{objective}\n"
    "=== FIN OBJETIVO ===\n"
    "{injected_context}\n"
    "\n"
    "[INSTRUCCION OBLIGATORIA DE CIERRE]: Al final de tu trabajo, AGREGA al "
    "final de `.opencode-context.md` una seccion con tu nombre de agente y, "
    "en la ULTIMA linea del archivo, el siguiente marcador escrito VERBATIM "
    "(sin cambios, sin alteraciones):\n"
    "    {agent_done_marker}\n"
    "El orquestador externo lo usa para detectar que terminaste. Sin el, el "
    "pipeline no puede continuar."
)


# ─── LOGGER PERSISTENTE POR PIPELINE ──────────────────────────────────────────
class PipelineLogger:
    """Logger que escribe a stdout y a un archivo por corrida del pipeline.
    El archivo vive en `./pipeline-artifacts/pipeline-<ts>.log` y registra
    timestamp + agente + returncode + snippet de errores (P8)."""

    def __init__(self, project_path: str):
        ts = time.strftime("%Y%m%d-%H%M%S")
        artifacts = os.path.join(project_path, ARTIFACTS_DIR)
        os.makedirs(artifacts, exist_ok=True)
        self.log_path = os.path.join(artifacts, f"pipeline-{ts}.log")

        self.logger = logging.getLogger("pipeline")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()

        fh = logging.FileHandler(self.log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s | %(levelname)-5s | %(message)s",
                                datefmt="%Y-%m-%d %H:%M:%S")
        fh.setFormatter(fmt)
        self.logger.addHandler(fh)

        self.log(f"Logger inicializado en {self.log_path}")

        # ── Contador de costo estimado ────────────────────────────────
        # Acumula por modelo: {model: [in_tok, out_tok]}. El costo real no se
        # mide (opencode no expone tokens por API en este flujo); se ESTIMA a
        # partir del objetivo enviado (input) y del output coleccionado. Es una
        # factura aproximada con MODEL_PRICING, configurable por env.
        self._cost = {}
        self._cost_lock = threading.Lock()

    def log(self, msg: str, level: int = logging.INFO):
        print(f"  [{logging.getLevelName(level)}] {msg}")
        self.logger.log(level, msg)

    def error(self, agent: str, snippet: str):
        """Loguea un error puntual de un agente (P8)."""
        snippet = (snippet or "").strip()
        head = snippet[:800] + ("..." if len(snippet) > 800 else "")
        self.logger.error(
            f"@{agent} FAIL :: snippet:\n{head}\n"
            f"{'─'*60}\n"
        )
        print(f"  [ERROR] @{agent} — ver {self.log_path}")

    def info(self, msg: str):
        self.log(msg, logging.INFO)

    def warn(self, msg: str):
        self.log(msg, logging.WARNING)

    def debug(self, msg: str):
        self.log(msg, logging.DEBUG)

    # ── Contador de costo estimado ─────────────────────────────────────────
    def add_cost(self, model: str, in_tok: int, out_tok: int):
        """Acumula tokens estimados (in/out) por modelo para la factura."""
        if not model:
            return
        with self._cost_lock:
            cur = self._cost.setdefault(model, [0, 0])
            cur[0] += max(0, int(in_tok))
            cur[1] += max(0, int(out_tok))

    def cost_report(self) -> str:
        """Resumen monoespaciado del costo ESTIMADO por modelo (USD)."""
        with self._cost_lock:
            if not self._cost:
                return "[COSTO] sin actividad medible."
        lines = ["[COSTO ESTIMADO] por modelo (USD):"]
        total = 0.0
        for model, (intok, outtok) in sorted(self._cost.items()):
            p_in, p_out = MODEL_PRICING.get(model, DEFAULT_PRICING)
            cost = (intok / 1e6) * p_in + (outtok / 1e6) * p_out
            total += cost
            lines.append(
                f"  {model:42} in~{intok:6} out~{outtok:6} → ${cost:.4f}"
            )
        lines.append(f"  {'TOTAL':42}        → ${total:.4f}")
        return "\n".join(lines)

    def log_cost_report(self):
        rep = self.cost_report()
        self.logger.info(rep.replace("[COSTO ESTIMADO]", "COSTO ESTIMADO"))
        print(rep)


# ─── BACKUP DE CONTEXTO (P7) ──────────────────────────────────────────────────
def backup_context(project_path: str, logger: PipelineLogger) -> str | None:
    """Siempre respalda el .opencode-context.md al iniciar el pipeline,
    independiente de si el usuario decide borrarlo o no. El historial vive
    en `pipeline-artifacts/context-history/` (P7)."""
    src = os.path.join(project_path, CONTEXT_FILE)
    if not os.path.exists(src):
        logger.info("No hay .opencode-context.md previo — nada que respaldar.")
        return None

    os.makedirs(os.path.join(project_path, CONTEXT_HISTORY_DIR), exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(project_path, CONTEXT_HISTORY_DIR,
                       f"{CONTEXT_FILE}.{ts}.bak")
    shutil.copy2(src, dst)
    logger.info(f"Backup de contexto → {dst}")
    return dst


# ─── GESTIÓN DE CONTEXTO ──────────────────────────────────────────────────────
def handle_opencode_context(project_path: str, resume: bool, logger: PipelineLogger):
    """Pregunta al usuario si desea borrar el .opencode-context.md para iniciar
    una tarea limpia. Con --resume se omite la pregunta."""
    ctx = os.path.join(project_path, CONTEXT_FILE)
    if not os.path.exists(ctx):
        return
    if resume:
        logger.info("--resume: conservando .opencode-context.md existente.")
        return

    print("\n[DETECTADO] Se encontró '.opencode-context.md' de una corrida anterior.")
    resp = input("¿Borrar '.opencode-context.md' para esta nueva corrida? (s/N): ").strip().lower()
    if resp in ("s", "si", "y", "yes"):
        try:
            os.remove(ctx)
            logger.info(".opencode-context.md eliminado (backup previo ya creado).")
        except OSError as e:
            logger.warn(f"No se pudo eliminar el archivo: {e}")
    else:
        logger.info("Se conserva el .opencode-context.md existente (modo retomar).")


def has_section(project_path: str, marker: str) -> bool:
    """True si el .opencode-context.md contiene el marker dado (literal)."""
    ctx = os.path.join(project_path, CONTEXT_FILE)
    if not os.path.exists(ctx):
        return False
    try:
        with open(ctx, encoding="utf-8", errors="replace") as f:
            return marker in f.read()
    except OSError:
        return False


def agent_done(agent: str, project_path: str) -> bool:
    """Verifica si el AGENT_DONE_MARKER del agente está presente en el contexto."""
    marker = AGENT_DONE_MARKER_TEMPLATE.format(agent=agent)
    return has_section(project_path, marker)


def inject_done_marker(agent: str, project_path: str, logger: PipelineLogger):
    """Inserta el marker canónico del agente al final del .opencode-context.md.
    Resuelve P12 con 100% confiabilidad: el orquestador garantiza el marker
    una vez que la corrida del agente termina OK (returncode 0), aunque el
    modelo no haya escrito el marker verbatim."""
    if not ALLOW_ORCHESTRATOR_MARKER_INJECTION:
        return
    ctx = os.path.join(project_path, CONTEXT_FILE)
    marker = AGENT_DONE_MARKER_TEMPLATE.format(agent=agent)
    if not os.path.exists(ctx):
        # Crea el archivo si no existe; el agente debería haberlo tocado, pero
        # esto da robustez.
        Path(ctx).write_text(f"\n{marker}\n", encoding="utf-8")
        logger.warn(f"{ctx} no existía — creado por el orquestador con marker @{agent}.")
        return
    try:
        with open(ctx, "a", encoding="utf-8") as f:
            f.write(f"\n{marker}\n")
    except OSError as e:
        logger.error(f"no se pudo inyectar marker @{agent}: {e}")


# ─── P13: LIMPIEZA DE MARKERS ESCRITOS POR OTROS AGENTES ──────────────────────
def strip_foreign_markers(current_agent: str, project_path: str,
                          trusted_initial: set, logger: PipelineLogger):
    """P13: elimina markers de agentes que vienen DESPUÉS de `current_agent`
    en el pipeline si no estaban ya presentes al iniciar esta corrida
    (--resume). Un agente escribiendo el marker de otro que aún no le tocaba
    correr es el bug real detrás de un @coder saltado sin haber ejecutado
    nada: el orquestador confiaba en cualquier marker sin importar quién lo
    escribió ni cuándo."""
    ctx = os.path.join(project_path, CONTEXT_FILE)
    if not os.path.exists(ctx):
        return
    try:
        idx_current = PIPELINE_ORDER.index(current_agent)
    except ValueError:
        return
    text = Path(ctx).read_text(encoding="utf-8", errors="replace")
    changed = False
    for agent in PIPELINE_ORDER[idx_current + 1:]:
        if agent in trusted_initial:
            continue  # ya estaba legítimamente done antes de esta corrida
        marker = AGENT_DONE_MARKER_TEMPLATE.format(agent=agent)
        if marker in text:
            text = text.replace(f"\n{marker}\n", "\n").replace(marker, "")
            changed = True
            logger.warn(f"Marker de @{agent} apareció prematuro tras @{current_agent} — removido (P13).")
    if changed:
        Path(ctx).write_text(text, encoding="utf-8")


# ─── DETECCIÓN DE STACK (P3) ───────────────────────────────────────────────────
def detect_stack(project_path: str) -> dict:
    """Auto-descubre el stack del proyecto. Retorna dict con:
        { "runner": "maven"|"gradle"|"prueba_java"|"pytest"|"npm"|"pnpm"|
                    "yarn"|"go"|"dotnet"|"html_playwright"|"none",
          "test_cmd": [list, of, args] or None,
          "build_cmd": [list, of, args] or None,
          "package_manager": "npm"|"pnpm"|"yarn" or None }
    No ejecuta nada; sólo infiere según archivos presentes."""
    p = Path(project_path)
    stack = {"runner": "none", "test_cmd": None, "build_cmd": None,
             "package_manager": None}

    # Java/Maven
    if (p / "pom.xml").exists():
        mvnw = "mvnw.cmd" if os.name == "nt" else "./mvnw"
        if not (p / mvnw).exists():
            mvnw = "mvn.cmd" if os.name == "nt" else "mvn"
        stack["runner"]   = "maven"
        stack["test_cmd"] = [mvnw, "test", "-q"]
        stack["build_cmd"] = [mvnw, "compile", "-q"]
        return stack

    # Java/Gradle
    if (p / "build.gradle").exists() or (p / "build.gradle.kts").exists():
        gradlew = "gradlew.bat" if os.name == "nt" else "./gradlew"
        stack["runner"]    = "gradle"
        stack["test_cmd"]  = [gradlew, "test", "--quiet"]
        stack["build_cmd"] = [gradlew, "build", "-x", "test", "--quiet"]
        return stack

    # Java standalone (Prueba.java)
    if (p / "Prueba.java").exists():
        stack["runner"]   = "prueba_java"
        stack["test_cmd"] = ["__PRUEBA_JAVA__"]  # marca para runner especial
        return stack

    # Python/pytest
    has_pyproject = (p / "pyproject.toml").exists()
    has_setup_py  = (p / "setup.py").exists()
    has_reqs      = any((p / f).exists() for f in ("requirements.txt", "Pipfile"))
    has_pytest_cfg = has_pyproject and "pytest" in (p / "pyproject.toml").read_text(encoding="utf-8", errors="ignore").lower() if has_pyproject else False
    has_test_files = bool(list(p.glob("test_*.py"))) or bool(list(p.glob("*_test.py"))) or (p / "tests").is_dir()
    if (has_pyproject or has_setup_py or has_reqs) and (has_pytest_cfg or has_test_files):
        stack["runner"]   = "pytest"
        stack["test_cmd"] = ["pytest", "-q"]
        return stack

    # Node/Frontend
    pkg_path = p / "package.json"
    if pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        except Exception:
            pkg = {}
        scripts = (pkg or {}).get("scripts", {}) or {}
        # package manager detection
        if (p / "pnpm-lock.yaml").exists():
            pm = "pnpm"
        elif (p / "yarn.lock").exists():
            pm = "yarn"
        else:
            pm = "npm"
        stack["package_manager"] = pm
        stack["runner"]          = pm
        if "test" in scripts:
            stack["test_cmd"]  = [pm, "run" if pm != "npm" else "run", "test"] if pm != "npm" else ["npm", "test"]
            # npm test == npm run test; pnpm/yarn usan `pnpm test` / `yarn test`
            stack["test_cmd"]  = [pm, "test"]
        if "build" in scripts:
            stack["build_cmd"] = [pm, "run", "build"] if pm != "npm" else ["npm", "run", "build"]
        # si hay test, retornamos runner=test; si no, runtime queda como "npm"
        # y el tester usará build_cmd como fallback de verificación (P4-a)
        return stack

    # Go
    if (p / "go.mod").exists():
        stack["runner"]   = "go"
        stack["test_cmd"] = ["go", "test", "./..."]
        stack["build_cmd"] = ["go", "build", "./..."]
        return stack

    # .NET
    if list(p.glob("*.csproj")) or list(p.glob("*.sln")):
        stack["runner"]    = "dotnet"
        stack["test_cmd"]  = ["dotnet", "test", "--nologo", "-v", "q"]
        stack["build_cmd"] = ["dotnet", "build", "--nologo", "-v", "q"]
        return stack

    # Frontend vanilla (HTML/JS): Playwright headless si hay index.html
    if (p / "index.html").exists():
        stack["runner"]    = "html_playwright"
        stack["test_cmd"]  = ["__PLAYWRIGHT_HEADLESS__"]  # marca
        return stack

    # Nada reconocido
    return stack


# ─── RUNNER DE PRUEBAS AGNÓSTICO (P3+P4) ───────────────────────────────────────
def run_tests(project_path: str, stack: dict, logger: PipelineLogger) -> tuple[bool, str]:
    """Ejecuta la suite detectada. Retorna (exito, error_log).
    P4: frontend sin runner → Playwright headless; si hay package.json con
    `test` o `build`, se corre; si no hay nada reconocido, se advierte y se
    devuelve (True, "") para no bloquear el pipeline."""
    runner = stack["runner"]
    logger.info(f"Stack detectado: {runner}")

    if runner == "none":
        logger.warn("No se detectó runner. Sin verificación automatizada.")
        return True, ""

    cwd = project_path

    # Caso especial: Playwright headless para HTML/JS vanilla (P4-c)
    if runner == "html_playwright":
        return _run_playwright_headless(project_path, logger)

    # Caso especial: Prueba.java standalone (compila *.java y ejecuta Prueba)
    if runner == "prueba_java":
        return _run_prueba_java(project_path, logger)

    test_cmd = stack["test_cmd"]
    if not test_cmd:
        # Si no hay `test` script pero hay build, usamos build_cmd como smoke
        # de verificación (P4-a).
        build_cmd = stack["build_cmd"]
        if build_cmd:
            logger.info("No hay script `test`. Ejecutando `build` como smoke check...")
            return _exec(build_cmd, cwd, logger, label=f"build ({runner})")
        logger.warn("Runner detectado pero sin comando de prueba ni build. Saltando.")
        return True, ""

    return _exec(test_cmd, cwd, logger, label=f"test ({runner})")


def _exec(cmd: list[str], cwd: str, logger: PipelineLogger, label: str) -> tuple[bool, str]:
    """Ejecuta `cmd` en `cwd`, captura stdout+stderr, retorna (exito, log)."""
    logger.info(f"Ejecutando: {' '.join(cmd)}  [{label}]")
    try:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                             shell=False, timeout=AGENT_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT tras {AGENT_TIMEOUT_SEC}s ejecutando `{cmd}`"
    except FileNotFoundError as e:
        return False, f"Comando no encontrado: {e}"
    except Exception as e:
        return False, f"Excepción ejecutando `{cmd}`: {e}"

    out = (res.stdout or "") + "\n" + (res.stderr or "")
    if res.returncode == 0:
        logger.info(f"OK — {label} pasó.")
        return True, ""
    logger.warn(f"FALLÓ — {label} (rc={res.returncode}).")
    return False, out[-2500:]


def _run_prueba_java(project_path: str, logger: PipelineLogger) -> tuple[bool, str]:
    """Compila todos los *.java en el directorio raíz y ejecuta `java Prueba`."""
    logger.info("Compilando *.java y ejecutando Prueba.java...")
    java_files = glob.glob(os.path.join(project_path, "*.java"))
    if not java_files:
        return False, "Prueba.java declarado pero no hay archivos .java"
    comp = _exec(["javac"] + java_files, project_path, logger, label="javac")
    if not comp[0]:
        return comp
    return _exec(["java", "Prueba"], project_path, logger, label="java Prueba")


def _run_playwright_headless(project_path: str, logger: PipelineLogger) -> tuple[bool, str]:
    """El path index.html en un http-server local y verifica que no haya
    errores de consola usando Playwright headless via npx (no requiere
    Python playwright). P4-c.

    Estrategia: crear un dir temporal SÓLO para instalar playwright y
    exponer el bin `playwright` (junto con node_modules/playwright). Desde
    ahí corremos un script .cjs que usa `require('playwright')`. Esto NO
    contamina el proyecto del usuario (no escribe node_modules ni package.json
    en project_path)."""
    index = os.path.join(project_path, "index.html")
    if not os.path.exists(index):
        return False, "index.html no encontrado"

    # Servir el directorio con `npx http-server` en un puerto efímero y
    # esperar a que esté listo. Usamos `npx -y http-server` (instala on-demand).
    logger.info("Levantando http-server local para Playwright headless...")
    try:
        server = subprocess.Popen(
            ["npx", "-y", "http-server", "-p", "0", "--cors", "-c-1", "."],
            cwd=project_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, shell=True, stdin=subprocess.DEVNULL,
        )
    except Exception as e:
        return False, f"No se pudo iniciar http-server: {e}"

    # Esperar a leer el puerto del output. http-server imprime varias URLs con
    # formato `http://127.0.0.1:PORT` (no usa 'localhost') — buscamos el patrón
    # `127.0.0.1:PORT` o `localhost:PORT`.
    port = None
    deadline = time.time() + 30
    while time.time() < deadline:
        line = server.stdout.readline()
        if not line:
            time.sleep(0.3)
            continue
        m = re.search(r"(?:127\.0\.0\.1|localhost):(\d+)", line)
        if m:
            port = m.group(1)
            break
    if not port:
        server.terminate()
        return False, "http-server no reportó puerto a tiempo"

    url = f"http://localhost:{port}/"
    logger.info(f"http-server escuchando en {url}")

    # Verificación con Playwright:
    # 1) Usar `npx -y playwright@latest open --no-shell` no: usamos el bin
    #    `npx -y playwright@latest screenshot <url> <png>` que es headless y
    #    expone el Chromium sin necesitar `require`. Problema: no captura
    #    errores de consola, sólo screenshot. NO nos sirve.
    # 2) Mejor: `npx -y playwright@latest codegen` no es headless.
    # 3) Enfoque definitivo: caché PERSISTENTE en ~/.opencode/playwright-cache/
    # (antes se usaba un workspace efímero en %TEMP%/pipeline-pw-tmp-* que
    # descargaba Playwright en CADA corrida — 30s-6min extra). Ahora
    # reusamos un dir fijo: si ya existe node_modules/playwright, sólo
    # escribimos el script .cjs y corremos. Limpieza: NO borramos el caché
    # (es el punto). Si se corrompe, el usuario puede borrarlo a mano.
    cache_root = os.path.join(os.path.expanduser("~"), ".opencode", "playwright-cache")
    os.makedirs(cache_root, exist_ok=True)
    script_path = os.path.join(cache_root, "check.cjs")
    check_js = r"""
    const { chromium } = require('playwright');
    (async () => {
        const errors = [];
        const browser = await chromium.launch({ headless: true });
        const page = await browser.newPage();
        page.on('console', m => { if (m.type() === 'error') errors.push('CONSOLE: ' + m.text()); });
        page.on('pageerror',     e => errors.push('PAGEERROR: ' + e.message));
        page.on('requestfailed', r => errors.push('REQFAIL: ' + (r.url() || '') + ' ' + (r.failure() && r.failure().errorText || '')));
        try {
            await page.goto(process.argv[2], { waitUntil: 'load', timeout: 30000 });
            await page.waitForTimeout(2500);
        } catch (e) {
            errors.push('NAV: ' + e.message);
        }
        await browser.close();
        if (errors.length) {
            console.error(errors.join('\n'));
            process.exit(1);
        }
    })().catch(e => { console.error('HARNESS: ' + e.message); process.exit(2); });
    """
    try:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(check_js)

        # Verificamos si playwright ya está cacheado. Si node_modules/playwright
        # existe, saltamos npm i. Esto es lo que ahorra los ~30s-6min.
        pw_module = os.path.join(cache_root, "node_modules", "playwright")
        if not os.path.isdir(pw_module):
            logger.info(f"Instalando playwright en caché persistente: {cache_root} (1a vez)")
            # Escribimos package.json a mano (npm init -y rechaza nombres con
            # mayúsculas o que empiecen con punto).
            pkg_json = os.path.join(cache_root, "package.json")
            with open(pkg_json, "w", encoding="utf-8") as f:
                f.write('{"name":"pipeline-pw-check","version":"1.0.0","private":true}')

            # npm i playwright (en el caché persistente). Tarda 30-60s la 1a
            # vez; posteriores corridas saltan este bloque entero.
            npm_install = subprocess.run(
                ["npm", "i", "playwright", "--no-save", "--silent"],
                cwd=cache_root, capture_output=True, text=True, shell=True,
                timeout=180,
            )
            if npm_install.returncode != 0:
                return False, f"npm i playwright falló (rc={npm_install.returncode}):\n{(npm_install.stderr or npm_install.stdout)[-600:]}"
        else:
            logger.info(f"Playwright cacheado en {cache_root} (skip npm i)")

        # Ejecutar el script .cjs con el node local (ya tiene node_modules/playwright)
        logger.info("Ejecutando verificación Playwright headless...")
        res = subprocess.run(
            ["node", script_path, url],
            cwd=cache_root, capture_output=True, text=True,
            shell=True, timeout=90,
        )
    finally:
        # Importante: NO borramos cache_root (es persistente por diseño).
        # Sólo terminamos el http-server efímero y remover el .cjs (que es
        # regenerado en cada corrida; queda sucio en el caché si no).
        try: os.remove(script_path)
        except OSError: pass
        server.terminate()
        try: server.wait(timeout=5)
        except Exception:
            try: server.kill()
            except Exception: pass

    if res.returncode == 0:
        logger.info("Playwright headless: OK (sin errores de consola).")
        return True, ""
    logger.warn("Playwright headless: FALLÓ (errores en consola / navegador).")
    return False, (res.stderr or res.stdout or "")[-2500:]


# ─── CONSTRUCCIÓN DEL OBJETIVO DEL AGENTE (P9) ────────────────────────────────
# P14: Lectura por INYECCIÓN en vez de lectura completa del contexto.
# .opencode-context.md crece con cada agente; leerlo entero en cada paso
# dispara el consumo de tokens y lentifica la interpretación inicial. Ahora
# el orquestador parsea los bloques por agente (delimitados por sus markers
# AGENT_DONE) e inyecta SOLO los relevantes en el mensaje del agente.
# P15: COMPACCIÓN — el bloque del agente inmediatamente anterior se inyecta
# COMPLETO (es la información accionable: mensaje para ti + estado actual),
# los bloques más antiguos se inyectan como RESUMEN EJECUTIVO determinista
# (primeras balas + mensaje para el siguiente agente), sin llamadas LLM.
CONTEXT_INJECTION_HEADER = (
    "\n"
    "--- CONTEXTO INYECTADO (secciones relevantes para ti) ---\n"
    "{blocks}\n"
    "--- FIN CONTEXTO INYECTADO ---\n"
)

# Qué bloques recibe cada agente: (full=[...], summary=[...]).
# "all" = archivo completo (resume inicial / documentación final).
AGENT_CONTEXT_BLOCKS = {
    "explorer":    (["all"], []),             # primero: contexto previo completo (--resume)
    "coder":       (["explorer"], []),        # explorer completo (contexto + "Para @coder")
    "tester":      (["coder"], ["explorer"]), # coder completo + resumen del explorer
    "debugger":    (["tester"], ["coder", "explorer"]),  # tester completo + resúmenes
    "sdd-updater": (["all"], []),             # documenta la corrida completa
}


def parse_context_blocks(project_path: str) -> dict:
    """Divide .opencode-context.md en bloques por agente usando los markers
    AGENT_DONE como delimitadores. Devuelve {agent: texto_del_bloque} (solo
    agentes que ya dejaron su marker). Vacío si no existe el archivo."""
    ctx = os.path.join(project_path, CONTEXT_FILE)
    if not os.path.exists(ctx):
        return {}
    with open(ctx, encoding="utf-8", errors="replace") as f:
        content = f.read()
    blocks, prev_end = {}, 0
    for agent in PIPELINE_ORDER:
        marker = AGENT_DONE_MARKER_TEMPLATE.format(agent=agent)
        idx = content.find(marker, prev_end)
        if idx == -1:
            continue
        end = idx + len(marker)
        blocks[agent] = content[prev_end:end].strip()
        prev_end = end
    return blocks


def summarize_block(agent: str, block: str, max_lines: int = 14) -> str:
    """Resumen ejecutivo DETERMINISTA de un bloque (P15): conserva el
    '## Mensaje para el siguiente agente' completo (información accionable)
    + el cuerpo acotado a max_lines. Sin llamadas LLM: puro recorte textual."""
    lines = block.splitlines()
    msg_idx = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("## Mensaje para el siguiente agente"):
            msg_idx = i
            break
    if msg_idx is not None:
        body = [ln for ln in lines[:msg_idx]
                if not ln.strip().startswith("<!-- AGENT_DONE")]
        msg = lines[msg_idx:]
        return "\n".join(body[:max_lines - 6] + [""] + msg[:6]).strip()
    return "\n".join(ln for ln in lines
                     if not ln.strip().startswith("<!-- AGENT_DONE"))[:max_lines]


def build_injected_context(project_path: str, agent: str) -> str:
    """Devuelve el bloque 'CONTEXTO INYECTADO' para el agente (P14+P15):
    bloques completos del agente anterior + resúmenes ejecutivos de los más
    antiguos. Cadena vacía si no hay contexto previo."""
    blocks = parse_context_blocks(project_path)
    if not blocks:
        return ""
    full_list, summary_list = AGENT_CONTEXT_BLOCKS.get(agent, (["all"], []))
    if full_list == ["all"]:
        selected = "\n\n".join(blocks.values())
    else:
        parts = []
        for a in full_list:
            if a in blocks:
                parts.append(blocks[a])
        for a in summary_list:
            if a in blocks:
                parts.append(
                    f"> [CONTEXTO COMPACTADO — resumen de @{a}]\n"
                    + summarize_block(a, blocks[a])
                )
        selected = "\n\n".join(parts)
    if not selected.strip():
        return ""
    return CONTEXT_INJECTION_HEADER.format(blocks=selected)


def est_tokens(text: str) -> int:
    """Estimación rápida de tokens: ~4 chars/token para mezcla código/texto.
    Solo para métricas — no es un contador exacto."""
    return max(0, len(text) // 4)


def log_token_metrics(logger, agent: str, project_path: str, message: str) -> None:
    """Loguea el consumo estimado de tokens del mensaje del agente y el
    ahorro de la inyección compactada (P14/P15) vs el archivo completo."""
    total = est_tokens(message)
    injected = build_injected_context(project_path, agent)
    inj = est_tokens(injected)
    blocks = parse_context_blocks(project_path)
    full = est_tokens("\n\n".join(blocks.values())) if blocks else 0
    line = f"[TOKENS] @{agent}: mensaje ~{total} tok | contexto inyectado ~{inj} tok"
    if full > 0:
        saved = max(0, full - inj)
        pct = 100 - (100 * inj // full) if full else 0
        line += f" | sin compactar ~{full} tok → ahorro {saved} tok ({pct}%)"
    logger.info(line)
    print(line)


def enforce_context_budget(project_path: str, agent: str, budget: int) -> str:
    """Red de seguridad: si el contexto inyectado que recibiría el
    agente supera `budget` tokens, lo recorta de forma determinista y PRIORIZADA:
    conserva íntegro el bloque del agente anterior (el más relevante) y resume los
    más antiguos a BUDGET_EVICT_MAX_LINES. Devuelve el contexto recortado (lista
    para inyectar) o "" si no aplica. No modifica archivos: solo prepara el texto."""
    blocks = parse_context_blocks(project_path)
    if not blocks:
        return ""
    full_list, summary_list = AGENT_CONTEXT_BLOCKS.get(agent, (["all"], []))
    if full_list == ["all"]:
        selected = "\n\n".join(blocks.values())
    else:
        parts = []
        for a in full_list:
            if a in blocks:
                parts.append(blocks[a])
        for a in summary_list:
            if a in blocks:
                parts.append(
                    f"> [CONTEXTO COMPACTADO — resumen de @{a}]\n"
                    + summarize_block(a, blocks[a])
                )
        selected = "\n\n".join(parts)
    cur = est_tokens(selected)
    if cur <= budget:
        return CONTEXT_INJECTION_HEADER.format(blocks=selected)

    # Excede el presupuesto → recorte por prioridad.
    # 1) Reduce los resúmenes de todos los bloques antiguos a fewer lines.
    evict = []
    for a in PIPELINE_ORDER:
        if a not in blocks or a == agent:
            continue
        evict.append(
            f"> [CONTEXTO COMPACTADO — resumen de @{a}]\n"
            + summarize_block(a, blocks[a], max_lines=BUDGET_EVICT_MAX_LINES)
        )
    trimmed = "\n\n".join(evict) if evict else selected
    # 2) Si aun así no baja del presupuesto, recorta por caracteres al tope.
    if est_tokens(trimmed) > budget:
        trimmed = trimmed[: budget * 4]
        trimmed += "\n[... CONTEXTO RECORTADO POR PRESUPUESTO ...]"
    return CONTEXT_INJECTION_HEADER.format(blocks=trimmed)


def build_agent_objective(project_path: str, agent: str, objective: str,
                          budget: int = 0) -> str:
    """Construye el prompt del agente: contexto primero, luego bloque de
    objetivo del usuario, luego instrucción de cierre con el marker.
    `budget`>0 aplica el recorte de contexto inyectado."""
    ctx = os.path.join(project_path, CONTEXT_FILE)
    has_prior_context = os.path.exists(ctx) and has_section(project_path, "## Contexto del Proyecto")
    context_priority = CONTEXT_PRIORITY_HEADER if has_prior_context else ""
    injected_context = (build_injected_context(project_path, agent) if budget <= 0
                        else enforce_context_budget(project_path, agent, budget))
    agent_done_marker = AGENT_DONE_MARKER_TEMPLATE.format(agent=agent)
    return OBJECTIVE_BLOCK_TEMPLATE.format(
        context_priority=context_priority,
        objective=objective,
        injected_context=injected_context,
        agent_done_marker=agent_done_marker,
    )


# ─── EJECUCIÓN DE AGENTES ─────────────────────────────────────────────────────
def run_agent(agent: str, project_path: str, objective: str, logger: PipelineLogger,
              invoke_as: str | None = None) -> int:
    invoke_as = invoke_as or agent
    model = AGENT_MODELS.get(agent, MODEL_FAST)
    label = f"@{agent}" if invoke_as == agent else f"@{agent} (especializado: {invoke_as})"
    print(f"\n{'─'*60}\n  > Lanzando {label} [{model}]\n{'─'*60}")
    logger.info(f"Lanzando {label} (model={model})")

    # WinError 206: Windows limita argv a ~32K chars y el objetivo (spec +
    # contexto inyectado) lo excede. Fix: escribir el objetivo COMPLETO a un
    # archivo temporal en pipeline-artifacts/ (gitignoreado) y adjuntarlo
    # con `opencode run ... -f <archivo>`.
    obj_dir = os.path.join(project_path, "pipeline-artifacts")
    os.makedirs(obj_dir, exist_ok=True)
    obj_file = os.path.join(obj_dir, f"objetivo-{agent}-{int(time.time())}.md")
    with open(obj_file, "w", encoding="utf-8") as _f:
        _f.write(objective)

    cmd = [
        OPENCODE_BIN, "run",
        "Ejecuta EXACTAMENTE el objetivo completo del archivo adjunto (-f). "
        "No lo resumas ni lo parafrasees: LEE el archivo y ejecuta todo lo que pide, "
        "incluido el contexto inyectado. Trabaja directamente sobre el proyecto.",
        "-f", obj_file,
        "--agent", invoke_as,
        "--model", model,
        "--auto",
        "--dir", project_path,
    ]

    try:
        # Stream en vivo: usamos Popen con PIPE + thread lector
        # que imprime cada línea CON PREFIJO en tiempo real Y la colecciona
        # en buffer interno para diagnóstico de rc spurios. Asi el usuario
        # ve el progreso del agente en terminal (no queda "desfazado" como
        # con capture_output=True), y el log sigue teniendo snippets completos.
        # stdin=DEVNULL: si opencode pide confirmación interactiva, recibe EOF.
        timeout = _agent_timeout(agent)
        proc = subprocess.Popen(
            cmd, cwd=project_path,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            bufsize=1,  # line-buffered
        )

        collected_lines = []
        collected_lock = threading.Lock()

        def _reader():
            """Lee stdout del proc línea por línea. Imprime al usuario
            con prefijo `@<agent> ` y acumula en buffer para el log."""
            try:
                for line in iter(proc.stdout.readline, ""):
                    if not line:
                        break
                    with collected_lock:
                        collected_lines.append(line)
                    # Strip ANSI escapes del prefijo del modelo (los colores
                    # opencode generan códigos \x1b[...m). Los dejamos en
                    # la línea original para que el usuario vea color, pero
                    # sólo imprimimos con prefix `@<agent>|` para distinguir
                    # lo que es del orquestador vs lo que escupe el agente.
                    sys.stdout.write(f"  @{agent}| {line}")
                    sys.stdout.flush()
            except Exception:
                pass  # el proc terminó; el join final recolecta el rc

        reader_thread = threading.Thread(target=_reader, daemon=True)
        reader_thread.start()

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            reader_thread.join(timeout=5)
            logger.error(agent, f"TIMEOUT tras {timeout}s")
            return 1

        reader_thread.join(timeout=5)

        with collected_lock:
            full_output = "".join(collected_lines)

        logger.info(f"@{agent} returncode={proc.returncode}")

        # Mejora 3: registrar costo ESTIMADO (input = objetivo enviado, output =
        # texto coleccionado). Aproximado; opencode no expone tokens por API.
        logger.add_cost(model, est_tokens(objective), est_tokens(full_output))

        if proc.returncode != 0:
            # Snippet para diagnóstico del log: últimas 1200 chars.
            snippet = full_output[-1200:]
            logger.error(agent, f"rc={proc.returncode} (timeout={timeout}s). snippet:\n{snippet}")
        return proc.returncode
    except subprocess.TimeoutExpired:
        logger.error(agent, f"TIMEOUT tras {_agent_timeout(agent)}s")
        return 1
    except KeyboardInterrupt:
        logger.warn("Ejecución interrumpida por el usuario.")
        sys.exit(130)
    except Exception as e:
        logger.error(agent, f"Excepción lanzando @{agent}: {e}")
        return 1


def run_agent_with_verification(agent: str, project_path: str, objective: str,
                                logger: PipelineLogger,
                                invoke_as: str | None = None) -> bool:
    """Lanza un agente y verifica: returncode==0 AND marker presente.
    Si discrepancia, reintenta 1 vez. Si reintento también falla → aborta
    con diagnóstico explícito (resuelve P12).
    Retorna True si el agente se consideró completado con éxito.

    Nota sobre rc spurio en Windows: el wrapper opencode.cmd a veces deja
    rc=1 por imprimir logs ANSI en stderr, aunque el agente terminó bien
    y escribió su marker. Si tras la corrida el marker aparece, aceptamos
    el resultado sin importar el rc (defensa en profundidad).
    """
    rc = run_agent(agent, project_path, objective, logger, invoke_as=invoke_as)

    marker_present = agent_done(agent, project_path)
    rc_ok = (rc == 0)

    if rc_ok and marker_present:
        logger.info(f"@{agent} OK (returncode=0 + marker presente).")
        return True

    # Caso Windows-típico (rc spurio =1): el agente escribió su marker pero
    # el wrapper .cmd reportó rc=1. Confiamos en el marker.
    if marker_present and not rc_ok:
        logger.warn(
            f"@{agent} rc={rc} PERO marker presente. Posible rc spurio del "
            f"wrapper .cmd en Windows. Aceptando el resultado."
        )
        return True

    # rc==0 pero el agente no escribió el marker → Bug P12 (codifica/output
    # truncado, modelo que ignora la instrucción). El orquestador inyecta.
    if rc_ok and not marker_present:
        logger.warn(f"@{agent} rc=0 pero sin marker. Inyectando marker por orquestador (P12 fix).")
        inject_done_marker(agent, project_path, logger)
        return True

    # rc!=0 AND marker no presente → reintento limpio
    logger.warn(f"@{agent} rc={rc} y marker ausente → reintento limpio.")
    rc2 = run_agent(agent, project_path, objective, logger, invoke_as=invoke_as)
    marker2 = agent_done(agent, project_path)
    if rc2 == 0 and marker2:
        logger.info(f"@{agent} OK en reintento.")
        return True
    if marker2 and rc2 != 0:
        # rc spurio del reintento pero marker presente
        logger.warn(f"@{agent} reintento rc={rc2} pero marker presente. Aceptando.")
        return True
    if rc2 == 0 and not marker2:
        logger.warn(f"@{agent} reintento rc=0 sin marker → inyectando por orquestador.")
        inject_done_marker(agent, project_path, logger)
        return True
    # Ambas fallaron
    logger.error(agent, f"Reintento también falló (rc={rc2}, marker="
                        f"{'sí' if marker2 else 'no'}).")
    return False


# ─── MCP MINIMAL (ahorro de tokens por request) ───────────────────────────────
# Los tool schemas de los MCP globales (context7, mdn, playwright, etc.) se
# inyectan en CADA request del agente: miles de tokens de prompt por request.
# --mcp-minimal genera <proyecto>/.opencode/opencode.json deshabilitándolos
# todos (idempotente; respeta un config de proyecto ya existente).
def apply_mcp_minimal(project_path: str, logger: PipelineLogger) -> None:
    """Genera/actualiza <proyecto>/.opencode/opencode.json con los MCP
    globales deshabilitados POR DEFECTO (minimal), RESPETANDO las decisiones
    explícitas del proyecto: si un MCP ya está configurado en el config del
    proyecto (ej. "second-brain": {"enabled": true}), se conserva tal cual —
    nunca se resetea a false. Solo los MCP sin configuración explícita pasan
    a enabled:false. Es idempotente: re-aplicarlo no toca lo ya decidido."""
    global_cfg = os.path.join(os.path.expanduser("~"), ".config", "opencode", "opencode.json")
    if not os.path.exists(global_cfg):
        logger.warn("No existe opencode.json global — no se puede aplicar --mcp-minimal.")
        return
    try:
        with open(global_cfg, encoding="utf-8") as f:
            g = json.load(f)
    except Exception as e:
        logger.warn(f"opencode.json global inválido ({e}) — no se puede aplicar --mcp-minimal.")
        return
    mcp = g.get("mcp") or {}
    proj_dir = os.path.join(project_path, ".opencode")
    os.makedirs(proj_dir, exist_ok=True)
    proj_cfg_path = os.path.join(proj_dir, "opencode.json")
    existing = {}
    if os.path.exists(proj_cfg_path):
        try:
            with open(proj_cfg_path, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}
    # MERGE: las decisiones explícitas del proyecto ganan; el resto -> off
    existing_mcp = existing.get("mcp") or {}
    merged = dict(existing_mcp)
    for name in mcp:
        if name not in existing_mcp:
            merged[name] = {"enabled": False}
    existing["mcp"] = merged
    with open(proj_cfg_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    disabled = sorted(n for n in mcp if n not in existing_mcp)
    preserved = sorted(n for n in mcp if n in existing_mcp)
    msg = (f"[MCP-MINIMAL] {len(disabled)} MCP deshabilitados, "
           f"{len(preserved)} conservados tal cual (decisiones del proyecto): {preserved}")
    logger.info(f"{msg} — {proj_cfg_path}")
    print(msg)


# ─── FLUJO PRINCIPAL ───────────────────────────────────────────────────────────
def run(project_path: str, objective: str, resume: bool, logger: PipelineLogger = None,
        mcp_minimal: bool = False, no_mcp_minimal: bool = False,
        budget: int = DEFAULT_CONTEXT_BUDGET_TOKENS):
    """Ejecuta el pipeline. Si `logger` es None, crea uno nuevo (uso
    standalone). Si se pasa (uso desde `__main__` con atexit), lo reusa
    para que el handler de atexit tenga referencia al mismo archivo.
    MCP minimal AUTOMÁTICO: si el proyecto no tiene `.opencode/opencode.json`,
    se genera uno deshabilitando todos los MCP globales (los schemas de MCP
    se inyectan en cada request del agente). `--mcp-minimal` fuerza la
    regeneración; `--no-mcp-minimal` salta la generación automática."""
    abs_path = os.path.abspath(project_path)
    if not os.path.exists(abs_path):
        print(f"[ERROR] La ruta no existe: {abs_path}")
        sys.exit(1)

    if logger is None:
        logger = PipelineLogger(abs_path)

    print(f"\n{'='*60}\n  PIPELINE AGNÓSTICO v2 — {Path(abs_path).name}\n  Objetivo: {objective[:120]}{'...' if len(objective) > 120 else ''}\n{'='*60}")
    logger.info(f"Pipeline iniciado. Proyecto: {abs_path}")

    # 0. Backup ALWAYS (independiente de borrar)
    backup_context(abs_path, logger)

    # 0b. Prompt de borrado (excepto --resume)
    handle_opencode_context(abs_path, resume=resume, logger=logger)

    # Detectar stack una sola vez
    stack = detect_stack(abs_path)
    logger.info(f"Stack inicial: {stack}")

    # MCP minimal: deshabilitar MCP globales para este proyecto (ahorro de tokens).
    # Automático en la primera corrida (proyecto sin .opencode/opencode.json);
    # --mcp-minimal fuerza regeneración; --no-mcp-minimal lo salta.
    proj_cfg_path = os.path.join(abs_path, ".opencode", "opencode.json")
    auto_mcp = not os.path.exists(proj_cfg_path)
    if mcp_minimal or (auto_mcp and not no_mcp_minimal):
        apply_mcp_minimal(abs_path, logger)
    elif auto_mcp and no_mcp_minimal:
        logger.info("[MCP-MINIMAL] omitido por --no-mcp-minimal (proyecto sin config).")
        print("[MCP-MINIMAL] omitido por --no-mcp-minimal.")

    # P13: snapshot de markers legítimos que YA existían antes de esta corrida
    # (válidos para --resume). Cualquier marker de un agente futuro que
    # aparezca DESPUÉS de este punto y no esté en este set se considera
    # espurio y se elimina.
    trusted_initial = {a for a in PIPELINE_ORDER if agent_done(a, abs_path)}

    def step(agent: str, obj: str, section_marker: str) -> bool:
        """Ejecuta un paso del pipeline con verificación robusta.
        `section_marker` es un texto human-friendly que NO se usa para
        detección (eso va con agent_done), sólo para log/skip.
        Resuelve automáticamente <agent>-<stack_runner> si existe .md
        especializado; si no, usa el agente genérico (retrocompatible)."""
        if agent_done(agent, abs_path):
            logger.info(f"@{agent} ya marcó done en contexto — saltando.")
            return True
        log_token_metrics(logger, agent, abs_path, obj)
        invoke_as = resolve_agent(agent, stack["runner"])
        ok = run_agent_with_verification(agent, abs_path, obj, logger, invoke_as=invoke_as)
        if ok:
            strip_foreign_markers(agent, abs_path, trusted_initial, logger)
        return ok

    # 1. Explorer
    if not step("explorer", build_agent_objective(abs_path, "explorer", objective, budget=budget), "explorer"):
        logger.error("explorer", "No pudo completarse la fase de exploración.")
        print("\n[ABORTADO] @explorer falló. Revisa el log del pipeline.")
        _write_status(abs_path, last_step="", status="failed",
                      failed="explorer", log_path=logger.log_path)
        sys.exit(PHASE_EXIT_CODES["explorer"])

    # 2. Coder (con prioridad de contexto)
    coder_obj = build_agent_objective(abs_path, "coder", objective, budget=budget)
    if not step("coder", coder_obj, "coder"):
        logger.error("coder", "Coder no pudo completar su tarea tras reintento.")
        print("\n[ABORTADO] @coder falló. Revisa el log del pipeline.")
        _write_status(abs_path, last_step="explorer", status="failed",
                      failed="coder", log_path=logger.log_path)
        sys.exit(PHASE_EXIT_CODES["coder"])

    # 3. Tester
    tester_obj = build_agent_objective(abs_path, "tester", objective, budget=budget)
    if not step("tester", tester_obj, "tester"):
        logger.error("tester", "Tester no pudo completar su tarea tras reintento.")
        print("\n[ABORTADO] @tester falló. Revisa el log del pipeline.")
        _write_status(abs_path, last_step="coder", status="failed",
                      failed="tester", log_path=logger.log_path)
        sys.exit(PHASE_EXIT_CODES["tester"])

    # Mejora 6: re-detectar el stack antes del bucle de debug. El coder puede
    # haber cambiado el runner (agregó package.json, pom.xml, wrapper, etc.),
    # así que re-evaluamos antes de decidir cómo ejecutar/verificar tests.
    stack = detect_stack(abs_path)
    logger.info(f"Stack re-detectado (tras coder): {stack}")

    # 4. Bucle Tester → Debugger (P5+P6)
    loops = 0
    while loops < MAX_DEBUG_LOOPS:
        success, error_log = run_tests(abs_path, stack, logger)
        if success:
            logger.info("Tests/verificación OK. Saliendo del bucle de debug.")
            break

        if not error_log.strip() or stack["runner"] == "none":
            logger.info("No hay error_log real o runner==none — no entra Debugger (P5).")
            break

        loops += 1
        logger.warn(f"REINTENTO {loops}/{MAX_DEBUG_LOOPS} — invocando @debugger con error_log real.")
        debug_obj = build_agent_objective(abs_path, "debugger", objective, budget=budget)
        debug_obj = (f"{debug_obj}\n\n"
                     f"=== ERROR DETECTADO EN EJECUCIÓN/TESTS ===\n{error_log}\n"
                     f"=== FIN ERROR ===\n")
        if not run_agent_with_verification("debugger", abs_path, debug_obj, logger,
                                           invoke_as=resolve_agent("debugger", stack["runner"])):
            logger.error("debugger", f"Bucle {loops}: Debugger falló tras reintento.")
            print(f"\n[ABORTADO] @debugger falló en intento {loops}. Revisa log.")
            _write_status(abs_path, last_step="tester", status="failed",
                          failed="debugger", log_path=logger.log_path)
            sys.exit(PHASE_EXIT_CODES["debugger"])
        strip_foreign_markers("debugger", abs_path, trusted_initial, logger)

    if loops >= MAX_DEBUG_LOOPS:
        logger.warn(f"Alcanzado MAX_DEBUG_LOOPS={MAX_DEBUG_LOOPS}. Pipeline continúa pero tests siguen fallando.")

    # 5. SDD-Updater (no abortamos si falla, pero ahora SÍ lo informamos)
    sdd_obj = build_agent_objective(abs_path, "sdd-updater", objective, budget=budget)
    sdd_ok = step("sdd-updater", sdd_obj, "sdd-updater")
    if not sdd_ok:
        logger.warn("Sdd-updater no completó su fase; el SDD puede estar desactualizado.")
        print("[AVISO] @sdd-updater no completó. El SDD del proyecto puede estar "
              "desactualizado — revisa el log si necesitas documentación precisa.")

    logger.info("PIPELINE FINALIZADO.")
    print(f"\n{'='*60}\n  PIPELINE FINALIZADO\n  Log: {logger.log_path}\n{'='*60}\n")

    # Mejora 3: factura estimada de la corrida.
    logger.log_cost_report()

    # Mejora 4+5: status final. Si sdd-updater no cerró, lo marcamos en el status
    # como fase pendiente/incompleta (pero el pipeline no se considera fallido).
    _write_status(abs_path, last_step="sdd-updater", status="ok",
                  failed=("sdd-updater" if not sdd_ok else None),
                  log_path=logger.log_path)
    return 0


# ─── STATUS JSON ──────────────────────────────────────────────────────────
def _write_status(project_path: str, last_step: str, status: str,
                  failed: str | None, log_path: str) -> None:
    """Escribe pipeline-status.json con el último paso completado, el estado y
    la fase que falló (si aplica). Permite a un wrapper relanzar directo al paso
    justo: si failed='coder' → relanzar desde coder con --resume.
    Sobrescribe el anterior (es el estado MÁS RECIENTE de la corrida)."""
    try:
        path = os.path.join(project_path, STATUS_FILE)
        payload = {
            "last_completed_step": last_step,
            "failed_step": failed,
            "status": status,
            "log": os.path.basename(log_path) if log_path else None,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"  [WARN] no se pudo escribir {STATUS_FILE}: {e}")


# ─── PARSER DE ARGUMENTOS (P10) ────────────────────────────────────────────────
def parse_args(argv: list[str]):
    """Soporta:
        python run_agents_v2.py <project> \"<objetivo>\"
        python run_agents_v2.py <project> --objective-file spec.md
        python run_agents_v2.py <project> \"<objetivo>\" --resume

    ¿Por qué --objective-file? Hasta ahora usas el script pegando el
    objetivo directo en la línea de comandos. Eso funciona, pero para specs
    largas con varias líneas (ej: mi-spec.md) el quoting en PowerShell/bash
    es frágil: los backticks, comillas simples/dobles, ${...}, y newlines
    pueden romper la transmisión del objetivo al script, y de ahí a opencode.

    --objective-file evita esos problemas: el script lee el archivo y mantiene
    el byte-for-byte. Dos patrones recomendados:
      a) Escribir la spec en un archivo (mi-spec.md, tarea-xyz.txt) en el
         propio proyecto y correr:
             python run_agents_v2.py . --objective-file mi-spec.md
      b) Generar el objetivo al vuelo desde otro proceso/redirección:
             python run_agents_v2.py . --objective-file -   # lee stdin
    """
    parser = argparse.ArgumentParser(
        description="Pipeline multi-agente opencode (backend/frontend).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("project", help="Ruta al proyecto")
    parser.add_argument("objective", nargs="?", default=None,
                        help="Objetivo de la corrida (string corto).")
    parser.add_argument("--objective-file", dest="objective_file", default=None,
                        help="Ruta a archivo con el objetivo largo (P10). "
                             "Usa '-' para leer de stdin.")
    parser.add_argument("--resume", action="store_true",
                        help="Retomar sin preguntar por borrar contexto.")
    parser.add_argument("--mcp-minimal", action="store_true",
                        help="Re-aplica el config MCP-minimal del proyecto "
                             "(merge: respeta las decisiones explícitas ya "
                             "configuradas en .opencode/opencode.json).")
    parser.add_argument("--no-mcp-minimal", action="store_true",
                        help="Evita la generación automática del config MCP-minimal "
                             "cuando el proyecto no tiene .opencode/opencode.json.")
    parser.add_argument("--budget-inject", dest="budget", type=int,
                        default=DEFAULT_CONTEXT_BUDGET_TOKENS,
                        help=f"Límite máximo de tokens para el contexto inyectado "
                             f"por agente (default {DEFAULT_CONTEXT_BUDGET_TOKENS}). "
                             f"0 desactiva el recorte.")
    args = parser.parse_args(argv)

    if not args.objective and not args.objective_file:
        parser.error("Debe indicar un objetivo (argumento o --objective-file).")
    if args.objective and args.objective_file:
        parser.error("Especifique sólo uno: objetivo como arg o --objective-file.")

    if args.objective_file:
        if args.objective_file == "-":
            obj = sys.stdin.read()
        else:
            opath = os.path.join(args.project, args.objective_file) \
                    if not os.path.isabs(args.objective_file) else args.objective_file
            if not os.path.exists(opath):
                parser.error(f"--objective-file no encontrado: {opath}")
            with open(opath, encoding="utf-8") as f:
                obj = f.read()
    else:
        obj = args.objective

    if not obj.strip():
        parser.error("El objetivo está vacío.")
    return args.project, obj, args.resume, args.mcp_minimal, args.no_mcp_minimal, args.budget


if __name__ == "__main__":
    import atexit
    import traceback

    proj, obj, resume, mcp_minimal, no_mcp_minimal, budget = parse_args(sys.argv[1:])
    abs_path = os.path.abspath(proj)
    if not os.path.exists(abs_path):
        print(f"[ERROR] La ruta no existe: {abs_path}")
        sys.exit(1)

    # Creamos el logger aquí, antes de run(), para garantizar que exista
    # incluso si run() revienta en su primera línea. Esto habilita que
    # el `atexit` handler pueda escribir el resumen final SIEMPRE.
    _guard_logger = PipelineLogger(abs_path)
    _guard_logger.info(f"(guard) Logger preventivo creado. Proyecto: {abs_path}")

    _pipeline_already_finished = {"value": False}

    def _atexit_handler():
        """Garantiza que cualquier salida inesperada del script
        quede registrada en el log con estado ABORTADO + stack trace si aplica.
        Se ejecuta SIEMPRE que el proceso Python termine, sea normal, sys.exit,
        excepción no capturada, o SIGTERM (en POSIX)."""
        if _pipeline_already_finished["value"]:
            return  # run() terminó bien, no hacer nada.
        _guard_logger.error("atexit",
                            "PIPELINE ABORTADO — salida inesperada sin "
                            "alcanzar el final del run(). Ver stderr arriba.")
        print(f"\n{'='*60}\n  PIPELINE ABORTADO (salida inesperada)\n  Log: {_guard_logger.log_path}\n{'='*60}\n",
              file=sys.stderr)

    atexit.register(_atexit_handler)

    try:
        # Reuso el logger del guard para que run() continúe usando ese mismo
        # archivo de log (en vez de crear uno nuevo). Pasamos el logger
        # explícitamente modificando run() para aceptar logger opcional.
        run(proj, obj, resume, logger=_guard_logger,
            mcp_minimal=mcp_minimal, no_mcp_minimal=no_mcp_minimal,
            budget=budget)
        _pipeline_already_finished["value"] = True
    except KeyboardInterrupt:
        _guard_logger.warn("PIPELINE CANCELADO por el usuario (Ctrl-C).")
        _pipeline_already_finished["value"] = True
        print("\n[CANCELADO] por el usuario. Log guardado en " + _guard_logger.log_path)
        sys.exit(130)
    except SystemExit:
        # sys.exit() vino de adentro (ej. ABORTADO por @explorer fail). Ya se
        # logueó la causa concreta. Marcamos para que atexit no duplique.
        _pipeline_already_finished["value"] = True
        raise
    except Exception as e:
        # Cualquier otra excepción no capturada por run() → stack trace completo
        # al log + stderr, y mensaje final claro.
        tb = traceback.format_exc()
        _guard_logger.error("uncaught",
                            f"Excepción no capturada: {e}\n{tb}")
        _pipeline_already_finished["value"] = True
        print(f"\n{'='*60}\n  PIPELINE ABORTADO (excepción)\n  Error: {e}\n  Log: {_guard_logger.log_path}\n{'='*60}\n",
              file=sys.stderr)
        sys.exit(1)
