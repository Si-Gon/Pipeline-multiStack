"""gate.py — estado de aprobación/consentimiento por spec + LOCK del pipeline.

El gate es la firma humana del SDD. Dos actos:
- aprobada  : la spec está completa y revisada (score + humana).
- consentida: autorización para implementar.

LOCK: el pipeline `run` corre solo si ambas son True para la spec objetivo.
Si falta alguna → gate 'blocked' → el pipeline NO lanza el coder (mejora #1 de
la evaluación E2E: convertir el gate independiente de juanklagos en cadena acoplada).

Estado en un JSON versionado: <proyecto>/spec/.sdd/gate.json
"""
import json
import os
import re

def gate_path(project_root: str) -> str:
    return os.path.join(project_root, "spec", ".sdd", "gate.json")


def load_gate(project_root: str) -> dict:
    """Lee gate.json; si no existe, devuelve estado vacío (sin specs)."""
    p = gate_path(project_root)
    if not os.path.exists(p):
        return {"specs": {}}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"specs": {}}


def save_gate(project_root: str, gate: dict) -> None:
    p = gate_path(project_root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(gate, f, ensure_ascii=False, indent=2)


def _norm_spec_key(spec_id: str) -> str:
    """Normaliza a número: '002-tienda...' → '2', '1' → '1', '002' → '2'."""
    m = re.match(r"^\s*0*(\d+)", str(spec_id))
    return m.group(1) if m else str(spec_id)


def _spec_entry(gate: dict, spec_id: str) -> dict:
    return gate.setdefault("specs", {}).setdefault(_norm_spec_key(spec_id), {})


def set_state(project_root: str, spec_id: str, *, aprobada=None, consentida=None,
              score=None, grade=None) -> dict:
    gate = load_gate(project_root)
    e = _spec_entry(gate, spec_id)
    if aprobada is not None:
        e["aprobada"] = bool(aprobada)
    if consentida is not None:
        e["consentida"] = bool(consentida)
    if score is not None:
        e["score"] = score
    if grade is not None:
        e["grade"] = grade
    save_gate(project_root, gate)
    return gate


def approve(project_root: str, spec_id: str) -> dict:
    return set_state(project_root, spec_id, aprobada=True)


def consent(project_root: str, spec_id: str) -> dict:
    return set_state(project_root, spec_id, consentida=True)


def get_spec_state(project_root: str, spec_id: str) -> dict:
    """Estado de una spec: aprobada? consentida? y verdict del gate."""
    gate = load_gate(project_root)
    key = _norm_spec_key(spec_id)
    e = gate.get("specs", {}).get(key, {})
    aprobada = bool(e.get("aprobada", False))
    consentida = bool(e.get("consentida", False))
    return {
        "spec_id": spec_id,
        "aprobada": aprobada,
        "consentida": consentida,
        "locked": not (aprobada and consentida),
        "verdict": "open" if (aprobada and consentida) else "blocked",
        "score": e.get("score"),
        "grade": e.get("grade"),
    }


def gate_summary(project_root: str) -> dict:
    """Resumen del gate para UI/bridge: verdict global por spec."""
    gate = load_gate(project_root)
    specs = gate.get("specs", {})
    out = []
    for key, e in sorted(specs.items()):
        aprobada = bool(e.get("aprobada", False))
        consentida = bool(e.get("consentida", False))
        out.append({
            "specId": key,
            "aprobada": aprobada,
            "consentida": consentida,
            "verdict": "open" if (aprobada and consentida) else "blocked",
            "locked": not (aprobada and consentida),
            "score": e.get("score"),
            "grade": e.get("grade"),
        })
    n_aprob = sum(1 for s in out if s["aprobada"])
    n_cons = sum(1 for s in out if s["consentida"])
    blocked = [s for s in out if s["locked"]]
    return {
        "verdict": "open" if not blocked else "blocked",
        "errors": len(blocked),
        "warnings": 0,
        "approvedSpecs": n_aprob,
        "consentedSpecs": n_cons,
        "totalSpecs": len(out),
        "specs": out,
        "lock_required": True,
    }