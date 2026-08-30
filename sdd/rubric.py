"""rubric.py — score determinista de una spec SDD (port de sdd-spec-scoring).

La misma rubric que verifiqué en @juanklagos/sdd-core (dist/score.js), sin
dependencia del paquete. Heurística: regex sobre el texto, no LLM.

Max alcanzable = 89 (no 100). Importante: score alto != buen diseño (ver DESIGN.md
y skill sdd-spec-scoring — "A" ≠ producto bueno; mide cobertura de secciones).

Buckets y pesos:
- 5 docs presentes (spec/plan/tasks/research/history) x4 = 20
- spec.md : objective/objetivo + requirement/requisito + acceptance/aceptación = 18 (6x3)
- plan.md : milestone/hito o dependency/dependencia o risk/riesgo = 9
- tasks.md: >=5 checkbox top-level `- [ ]` = 15
- research.md: decision/decisión + rationale/justif/por qué + reference/referencia = 15 (5x3)
- history.md: fecha \\d{4}-\\d{2}-\\d{2} = 12
"""
import os
import re

REQUIRED_DOCS = ["spec.md", "plan.md", "tasks.md", "research.md", "history.md"]
TASK_LINE_RE = re.compile(r"^- \[[ xX]\]")


def score_spec_dir(spec_dir: str) -> dict:
    """Puntúa una spec en `spec_dir` (carpeta NNN-slug/). Devuelve score/grade/notes."""
    score = 0
    notes = []

    def read(name):
        p = os.path.join(spec_dir, name)
        try:
            with open(p, encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    docs = {name: read(name) for name in REQUIRED_DOCS}
    present = sum(1 for v in docs.values() if v is not None)
    score += present * 4
    if present < len(REQUIRED_DOCS):
        notes.append("missing required files")

    spec = docs["spec.md"]
    if spec is not None:
        hits = 0
        if re.search(r"objective|objetivo", spec, re.I):
            hits += 1
        if re.search(r"requirement|requisito", spec, re.I):
            hits += 1
        if re.search(r"acceptance|aceptaci[oó]n", spec, re.I):
            hits += 1
        score += hits * 6
        if hits < 3:
            notes.append("spec.md lacks objective/requirements/acceptance")

    plan = docs["plan.md"]
    if plan is not None:
        if re.search(r"milestone|hito|dependency|dependencia|risk|riesgo", plan, re.I):
            score += 9
        else:
            notes.append("plan.md lacks milestones/dependencies/risks")

    tasks = docs["tasks.md"]
    if tasks is not None:
        n = sum(1 for line in tasks.split("\n") if TASK_LINE_RE.match(line))
        if n >= 5:
            score += 15
        elif n >= 3:
            score += 10
            notes.append("tasks.md has limited task breakdown")
        elif n >= 1:
            score += 5
            notes.append("tasks.md needs more actionable tasks")
        else:
            notes.append("tasks.md has no checklist tasks")

    research = docs["research.md"]
    if research is not None:
        hits = 0
        if re.search(r"decision|decisi[oó]n", research, re.I):
            hits += 1
        if re.search(r"rationale|justific|why|por qu[eé]", research, re.I):
            hits += 1
        if re.search(r"reference|referencia", research, re.I):
            hits += 1
        score += hits * 5
        if hits < 2:
            notes.append("research.md needs clearer decision rationale")

    history = docs["history.md"]
    if history is not None:
        if re.search(r"\d{4}-\d{2}-\d{2}", history):
            score += 12
        else:
            score += 6
            notes.append("history.md has no dated entries")

    score = min(score, 100)
    grade = "A" if score >= 85 else ("B" if score >= 70 else ("C" if score >= 55 else "D"))
    return {"score": score, "grade": grade, "notes": notes}


def score_project(project_root: str) -> list:
    """Puntúa todas las specs en spec/specs/NNN-slug/. Devuelve lista."""
    specs_dir = os.path.join(project_root, "spec", "specs")
    results = []
    if not os.path.isdir(specs_dir):
        return results
    for entry in sorted(os.listdir(specs_dir)):
        d = os.path.join(specs_dir, entry)
        if not os.path.isdir(d) or entry.startswith("_") or not os.path.exists(os.path.join(d, "spec.md")):
            continue
        r = score_spec_dir(d)
        r["specId"] = entry
        results.append(r)
    return results