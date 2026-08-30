"""spec_templates.py — generación de spec nueva (bundle base 5 archivos).

¿Por qué? El pipeline (mejora pendiente) necesita crear specs nuevas, no solo
correr `--objective-file` sobre specs escritas a mano. Este módulo reproduce el
bundle mínimo que el SDD usa (spec/plan/tasks/research/history) a partir de los
templates del SDD, SIN el scaffolding ruidoso (scripts, template-context, multistack)
que ya se eliminó.

Conserva los campos que la rubric de sdd-spec-scoring puntúa (objetivo, requisito,
aceptación, hitos/dependencias/riesgos, >=5 tasks, research con decisión/rationale/
referencia, history con fecha) para que una spec nueva arranque puntuable, no vacía.
"""
import os
import re

# Nombres de los 5 archivos del bundle (contrato del SDD propio).
BUNDLE_FILES = ["spec.md", "plan.md", "tasks.md", "research.md", "history.md"]


def _slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def next_spec_number(specs_dir: str) -> int:
    """Próximo número de spec (001, 002, ...) + 1."""
    nums = []
    if os.path.isdir(specs_dir):
        for entry in os.listdir(specs_dir):
            m = re.match(r"^(\d{3})", entry)
            if m:
                nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


def _spec_md(name: str, slug: str) -> str:
    return f"""# Especificación {slug} - {name}

## Objetivo

{name}: definir qué debe hacer y qué debe quedar implementado antes de cerrar.

## Estado de aprobación / Approval status

- Estado / Status: `Pendiente`
- Valores permitidos / Allowed values: `Pendiente` o `Aprobado`
- Fecha de aprobación: `YYYY-MM-DD`
- Aprobado por: `Nombre o rol`

## Historia de usuario principal

como [rol] quiero [capacidad] para [beneficio]

## Escenarios de aceptación

1. Dado [contexto], CUANDO [acción], ENTONCES [resultado observable].

## Criterios de aceptación (formato EARS recomendado)

- CUANDO [disparador], EL SISTEMA DEBERÁ [comportamiento observable].
- SI [condición de error], ENTONCES EL SISTEMA DEBERÁ [comportamiento observable].

## Requisitos

- Requisito 1

## Ámbito de archivos / File scope

<!-- Rutas que gobierna esta spec, una por línea, en backticks. -->
- `src/` — implementación del comportamiento

## Criterios de éxito

- Criterio 1
"""


def _plan_md(name: str, slug: str) -> str:
    return f"""# Plan - {name}

## Resumen

Implementar {name} en fases, priorizando el camino funcional primero.

## Estrategia / Strategy

- [ ] Fase A: modelo y datos
- [ ] Fase B: comportamiento principal
- [ ] Fase C: detalles / robustez

## Hitos / Milestones

1. Hito 1 — corte funcional mínimo
2. Hito 2 — comportamiento completo

## Dependencias / Dependencies

- Dependencia 1

## Riesgos / Risks

- Riesgo 1
"""


def _tasks_md(name: str, slug: str) -> str:
    return f"""# Tasks - {name}

## Fase A — modelo/datos
- [ ] Tarea básica de la fase A
- [ ] Segunda tarea de la fase A
- [ ] Tercera tarea de la fase A

## Fase B — comportamiento
- [ ] Tarea básica de la fase B
- [ ] Segunda tarea de la fase B
- [ ] Tercera tarea de la fase B

## Fase C — detalles/robustez
- [ ] Tarea básica de la fase C
- [ ] Segunda tarea de la fase C

## Validation
- [ ] Verificación final (tests / revisión)
"""


def _research_md(name: str, slug: str) -> str:
    return f"""# Research - {name}

## Current behavior / Estado actual

- Descripción breve de lo que existe hoy.

## Technical options / Opciones técnicas

- Opción A: ...
- Opción B: ...

## Decision / Decisión

- Decision: opción elegida (por qué).
- Rationale / Justificación: motivo.
- Referencia / Reference: fuente o patrón de referencia.

## Aprendizajes / Learnings

- Apunte accionable para próximas iteraciones.
"""


def _history_md(name: str, slug: str) -> str:
    return f"""# History - {name}

## 2026-08-30 - v0.1

### Added
- Spec inicial generada: {slug}
### Why
- Arranque de la especificación {name}.
"""


TEMPLATES = {
    "spec.md": _spec_md,
    "plan.md": _plan_md,
    "tasks.md": _tasks_md,
    "research.md": _research_md,
    "history.md": _history_md,
}


def create_spec(project_root: str, name: str) -> dict:
    """Crea una spec nueva (NNN-slug/) con los 5 archivos base. Devuelve metadatos."""
    slug = _slugify(name)
    if not slug:
        raise ValueError("nombre de spec vacío o inválido")

    specs_dir = os.path.join(project_root, "spec", "specs")
    os.makedirs(specs_dir, exist_ok=True)
    num = next_spec_number(specs_dir)
    spec_id = f"{num:03d}-{slug}"
    spec_dir = os.path.join(specs_dir, spec_id)
    if os.path.exists(spec_dir):
        raise FileExistsError(f"ya existe la carpeta: {spec_dir}")

    os.makedirs(spec_dir, exist_ok=True)
    created = []
    for fname, fn in TEMPLATES.items():
        path = os.path.join(spec_dir, fname)
        with open(path, "w", encoding="utf-8") as f:
            f.write(fn(name, spec_id))
        created.append(fname)

    return {"id": spec_id, "dir": spec_dir, "files": created, "num": num}