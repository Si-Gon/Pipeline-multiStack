"""rubric.py — score determinista de una spec SDD (rediseñado: score HONESTO).

Motivo del rediseño (2026-08-30): la rubric vieja puntuaba por PRESENCIA de
keywords, y la plantilla del bundle arrancaba en 89/A sin rellenar nada — un
score deshonesto (tautología). Acá la plantilla SOLA queda ~30/D: subir de nota
exige SUSTANCIA real, no solo cabeceras.

Principio:
- Estructura = barata (base). Contenido = caro (solo puntúa lo que demuestra
  intención de construir algo verificable).
- Detecta placeholders de plantilla y los PENALIZA (antipatrón = resta).
- Techo ~95 (con sustancia real). Meta 85 = nota A, pero ahora 85 exige rellenar
  de verdad (objetivo accionable + aceptación verificable + tests explícitos +
  referencia real), no copiar la estructura.

Dimensiones y pesos (heurísticas regex sobre texto, no LLM):
- 5 docs presentes y NO vacíos (len>300)         : 20 (4/cada, solo si tiene cuerpo)
- spec.md objetivo accionable (verbo+resultado) : 10 (2,5x2: 'CUANDO/SI...DEBERÁ' + verbo accionable)
- spec.md aceptación verificable (EARS real)    : 14 (CUANDO...ENTONCES...DEBERÁ + cuerpo)
- spec.md requisitos con cuerpo real             : 10 (>=2 items con longitud)
- plan.md hitos/dependencias/riesgos con cuerpo  : 9
- research.md decisión razonada + ref REAL       : 10 (ref con URL/patrón/archivo)
- tasks.md >=5 + al menos 1 test explícito       : 15 (12 tareas + 3 test)
- history.md fecha en fila con cambio descrito   : 9
- PENALIZACIÓN placeholders de plantilla         : -30 max (por token detectado)
                                               TOTAL techo = ~95
"""
import os
import re

REQUIRED_DOCS = ["spec.md", "plan.md", "tasks.md", "research.md", "history.md"]
MIN_DOC_LEN = 200          # un doc "presente pero vacío" no cuenta (len > umbral)
TASK_LINE_RE = re.compile(r"^- \[[ xX]\]")
PARA_RE = re.compile(r"\n{2,}")          # separadores de párrafo

# Antipatrones: tokens literales de la plantilla que indican "sin rellenar"
PLACEHOLDER_TOKENS = [
    r"\bRequisito\s*1\b",
    r"\bDependencia\s*1\b",
    r"\bRiesgo\s*1\b",
    r"\bHito\s*1\b",
    r"\bCriterio\s*1\b",
    r"\bTarea\s*b[aá]sica\s*de la fase",
    r"\bDescripci[oó]n\s*breve\s*de lo que existe",
    r"\b[Oo]pci[oó]n\s*A\s*:",
    r"\b[Jj]ustificaci[oó]n\s*:\s*$",
    r"\b[Rr]eferencia\s*:\s*$",
    r"\bdado\s*\[contexto\]",
    r"\bcomo\s*\[rol\]\s*quiero",
    r"\bdefinir qué debe hacer",
    r"\[contexto\]",
    r"\[disparador\]",
    r"\[comportamiento observable\]",
    r"\[resultado observable\]",
    r"\[rol\]",
    r"\[capacidad\]",
    r"\[beneficio\]",
    r"\[acción\]",
]

# Verbos accionables para detectar un objetivo real (no "definir X" genérico)
ACTION_VERBS = r"(crear|implementar|habilitar|permitir|agregar|a[nñ]adir|poder|mostrar|recalcular|generar|validar|persistir|incrementar|cargar|configurar|exportar|importar|buscar|filtrar|ordenar|integrar|proveer|proveer la|dise[nñ]ar|redise[nñ]ar|representar|definir|entregar|construir|producir|ofrecer)"


def _read_tree(spec_dir: str):
    docs = {}
    for name in REQUIRED_DOCS:
        p = os.path.join(spec_dir, name)
        try:
            with open(p, encoding="utf-8") as f:
                docs[name] = f.read()
        except Exception:
            docs[name] = None
    return docs


def _doc_len(text: str) -> int:
    return len(text) if text else 0


def _count_placeholder_penalty(docs: dict) -> int:
    """Resta hasta 30 por placeholders (antipatrón de plantilla sin rellenar)."""
    total_tokens = 0
    for name, text in docs.items():
        if not text:
            continue
        for pat in PLACEHOLDER_TOKENS:
            total_tokens += len(re.findall(pat, text))
    return min(total_tokens * 5, 30)


def _num_parrafos(text: str) -> int:
    if not text:
        return 0
    return max(1, len(PARA_RE.split(text.strip())))


def score_spec_dir(spec_dir: str) -> dict:
    """Puntúa una spec en `spec_dir`. Devuelve score/grade/notes (determinista)."""
    docs = _read_tree(spec_dir)
    score = 0
    notes = []

    # 1) 5 docs presentes y con cuerpo (no vacíos)
    present = 0
    for name in REQUIRED_DOCS:
        if docs[name] is not None and _doc_len(docs[name]) > MIN_DOC_LEN:
            present += 1
        elif docs[name] is not None and _doc_len(docs[name]) <= MIN_DOC_LEN:
            notes.append(f"{name} presente pero vacío/comprimido (sin cuerpo real)")
    score += present * 4          # 20 si los 5 tienen cuerpo

    spec = docs["spec.md"]
    if spec is not None:
        # 2) Objetivo accionable: verbo accionable + resultado
        objs = re.findall(r"##\s*(?:Objetivo|Objective)[^\n]*\n(.*?)(?=\n##|\Z)", spec, re.I | re.S)
        obj_block = objs[0] if objs else spec
        accionable = bool(re.search(ACTION_VERBS, obj_block, re.I)) and len(obj_block.strip()) > 40
        if accionable:
            score += 10
        else:
            notes.append("spec.md objetivo no accionable (falta verbo de acción / resultado)")

        # 3) Aceptación verificable: criterios EARS (CUANDO...ENTONCES...DEBERÁ)
        #    O escenarios Gherkin (Dado...CUANDO...ENTONCES resultado observable).
        #    Ambos son aceptación real; el objetivo es no dejar pasar placeholders.
        ears = re.findall(
            r"(?:CUANDO|SI|WHEN|IF|DADO)\b[^#]{20,}?(?:DEBER[AÁ]|MUST|SHALL|DEBE|ENTONCES)",
            spec, re.I | re.S
        )
        gherkin_matches = re.findall(
            r"Dado\b.*?CUANDO\b.*?ENTONCES\b[^\n]*(?:\n|$)", spec, re.I | re.S
        )
        ears_real = [e for e in ears if len(e) > 50]
        gherkin_real = [g for g in gherkin_matches if len(g.strip()) > 25]  # con resultado observable
        acc_total = min(len(ears_real) * 7, 14) if ears_real else 0
        if not ears_real and gherkin_real:
            acc_total = min(len(gherkin_real) * 4, 14)   # Gherkin también cuenta (14 con ~4 escenarios)
        score += acc_total
        if not ears_real and not gherkin_real:
            notes.append("spec.md aceptación no verificable (sin criterios EARS/Gherkin reales)")

        # 4) Requisitos con cuerpo real: >=2 items con >=20 chars cada uno
        reqs = re.findall(r"^[-*]\s+(.{20,})", spec, re.M)
        reqs_real = [r for r in reqs if r.strip(" `") not in ("Requisito 1",)]
        if len(reqs_real) >= 2:
            score += 10
        else:
            notes.append("spec.md requisitos sin cuerpo real (<2 ítems sustantivos)")

    plan = docs["plan.md"]
    if plan is not None:
        # Presencia de conceptos de planificación con cuerpo (nombres de sección
        # pueden variar: 'Hitos'/'Fases'/'Etapas', 'Dependencias', 'Riesgo'). Exigir
        # 2+ conceptos y que el doc tenga densidad (no una plantilla con 1 línea).
        concepto_menciones = sum(bool(re.search(p, plan, re.I)) for p in [
            r"(?:hito|milestone|fase|etapa|phase)",
            r"(?:dependenci[ae]|dependency)",
            r"(?:riesgo|risk)",
        ])
        doc_denso = len(plan) > 140 and plan.count("-") + plan.count("*") + plan.count("1.") >= 2
        if concepto_menciones >= 2 and doc_denso:
            score += 9
        else:
            notes.append("plan.md sin hitos+dependencias+riesgos con cuerpo")

    research = docs["research.md"]
    if research is not None:
        has_decision = bool(re.search(r"decision|decisi[oó]n", research, re.I))
        # ref REAL: URL, ruta de archivo, nombre de método/patrón (no la palabra suelta)
        ref_real = bool(re.search(
            r"(https?://|`[A-Za-z0-9_./\\-]+\.(?:js|py|md|json|html)`|patr[oó]n de|service|API de|m[oó]dulo de)",
            research, re.I
        ))
        if has_decision and ref_real:
            score += 10
        elif has_decision:
            score += 5
            notes.append("research.md tiene decisión pero sin referencia real (URL/patrón/archivo)")
        else:
            notes.append("research.md sin decisión razonada")

    tasks = docs["tasks.md"]
    if tasks is not None:
        n = sum(1 for line in tasks.split("\n") if TASK_LINE_RE.match(line))
        if n >= 5:
            score += 12
        elif n >= 3:
            score += 8
        else:
            notes.append("tasks.md con pocas tareas (<5 checkboxes)")
        # test explícito
        has_test = bool(re.search(r"(test|verificar|verificaci[oó]n|Playwright|__spec_test|assert)", tasks, re.I))
        if has_test:
            score += 3
        else:
            notes.append("tasks.md no menciona verificación/tests explícitos")

    history = docs["history.md"]
    if history is not None:
        # fecha en fila de tabla (| YYYY-MM-DD |) con detalle de cambio tras ella
        if re.search(r"\d{4}-\d{2}-\d{2}\s*\|[^|]*\|[^|]+\|[^|]+", history):
            score += 9
        elif re.search(r"\d{4}-\d{2}-\d{2}", history):
            score += 5
            notes.append("history.md con fecha pero sin detalle del cambio")
        else:
            notes.append("history.md sin entradas fechadas")

    # PENALIZACIÓN por placeholders de plantilla
    penalty = _count_placeholder_penalty(docs)
    if penalty:
        score -= penalty
        notes.append(f"placeholders de plantilla sin rellenar (−{penalty})")

    score = max(0, min(score, 100))
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