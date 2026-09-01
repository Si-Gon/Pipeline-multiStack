"""Test de la rubric rediseñada (sdd/rubric.py) — score honesto de sustancia.

Garantías clave (regresión del rediseño 2026-08-30):
- Una spec SOLO plantilla (sin rellenar) NO debe ser A: debe quedar baja (score < 70).
- Un bundle relleno de verdad (objetivo accionable + EARS/Gherkin + requisitos +
  research con ref real + tasks con tests + history detallado) debe pasar la meta 85 (A).
- Los placeholders de plantilla restan (antipatrón detectado).
"""
import os
import tempfile

import sdd.rubric as R
import sdd.spec_templates as T


def _build_rellena(tmp: str, name: str) -> str:
    """Construye un bundle relleno de verdad (alta sustancia)."""
    d = T.create_spec(tmp, name)["dir"]
    # spec.md con objetivo accionable + EARS + requisitos reales
    open(os.path.join(d, "spec.md"), "w", encoding="utf-8").write(
        "# Especificación test - " + name + "\n"
        "## Objetivo\n"
        "Implementar un módulo que permita registrar compras con su valor total en CLP "
        "y que recalcule el subtotal al cambiar la cantidad, junto con una fila de "
        "productos recomendados del mismo rubro.\n"
        "## Criterios de aceptación\n"
        "- CUANDO el usuario agrega un producto con stock, EL SISTEMA DEBERÁ incrementar "
        "la cantidad o crearla, y recalcular el subtotal en CLP (criterio EARS n°1, observable).\n"
        "- SI el carrito está vacío y se abre el resumen, ENTONCES EL SISTEMA DEBERÁ mostrar "
        "un estado vacío sin totales (criterio EARS n°2, observable).\n"
        "## Requisitos\n"
        "- Requisito de negocio: el carrito duplica en memoria y no persiste nada externo.\n"
        "- Requisito de datos: los totales se formatean en CLP enteros con toLocaleString.\n"
    )
    # plan: hitos/dependencias/riesgos reales
    open(os.path.join(d, "plan.md"), "w", encoding="utf-8").write(
        "# Plan\n"
        "## Hitos / Milestones\n"
        "1. Hito 1: carrito operativo con subtotales en CLP.\n"
        "2. Hito 2: fila 'Sugerido para ti' integrada en el detalle.\n"
        "## Dependencias / Dependencies\n"
        "- Dependencia: el render de catálogo del proyecto (tarjetaProducto) se reutiliza.\n"
        "## Riesgos / Risks\n"
        "- Riesgo: tocar el catálogo existente puede romper las specs 001/002 — se añade capa.\n"
    )
    # research: decisión razonada + ref real (URL)
    open(os.path.join(d, "research.md"), "w", encoding="utf-8").write(
        "# Research\n"
        "## Decision\n"
        "Decisión: carrito en memoria (Opción A) por simplicidad.\n"
        "Rationale: evita tocar el backend y reutiliza el render de tarjetas ya existente.\n"
        "Referencia: https://developer.mozilla.org/es/docs/Web/JavaScript/Reference/Global_Objects/Intl/NumberFormat\n"
    )
    # tasks: >=5 + mentiona tests
    open(os.path.join(d, "tasks.md"), "w", encoding="utf-8").write(
        "## Tasks\n"
        "- [ ] Agregar producto al carrito\n"
        "- [ ] Incrementar cantidad si ya existe\n"
        "- [ ] Recalcular subtotal y total en CLP\n"
        "- [ ] Mostrar estado vacío del carrito\n"
        "- [ ] Validar con test carritoService.spec.js\n"
        "- [ ] Verificar con Playwright que el badge se actualiza\n"
    )
    # history detallado (fila con cambio descrito)
    open(os.path.join(d, "history.md"), "w", encoding="utf-8").write(
        "# Change history\n"
        "| Date | Type | Summary | Files | Owner |\n"
        "|---|---|---|---|---|\n"
        "| 2026-08-30 | Feature | Carrito funcional implementado: agregar con cantidad, "
        "subtotales y total en CLP, estado vacío, sin stock y fila 'Sugerido para ti' por "
        "categoría, reusando el render del catálogo existente | `src/cart/carritoService.js`, "
        "`src/cart/vistaCarrito.js`, `src/utils/formato.js`, `styles.css` | silvio |\n"
    )
    return d


def test_plantilla_sola_no_es_A():
    """Regresión clave: la plantilla vacía NO debe ser A (antes era 89/A por tautología)."""
    tmp = tempfile.mkdtemp()
    d = T.create_spec(tmp, "Vacia")["dir"]
    r = R.score_spec_dir(d)
    assert r["score"] < 85, f"plantilla sola no debe ser A, pero dio {r['score']}={r['grade']}"
    assert r["grade"] != "A"


def test_bundle_relleno_es_A():
    """Un bundle con sustancia real debe pasar la meta 85 (A)."""
    tmp = tempfile.mkdtemp()
    d = _build_rellena(tmp, "Carrito real")
    r = R.score_spec_dir(d)
    assert r["grade"] == "A", f"bundle relleno debe ser A, pero dio {r['score']}={r['grade']} (notes={r['notes']})"


def test_placeholder_penaliza():
    """Los placeholders de plantilla deben restar (detectados como antipatrón)."""
    tmp = tempfile.mkdtemp()
    d = T.create_spec(tmp, "Con placeholder")["dir"]
    # dejar un placeholder evidente sin rellenar
    spec = open(os.path.join(d, "spec.md"), encoding="utf-8").read()
    assert "definir qué debe hacer" in spec  # token de plantilla presente y penalizado


def test_notes_en_plantilla():
    """La plantilla vacía debe llevar nota de placeholders sin rellenar."""
    tmp = tempfile.mkdtemp()
    d = T.create_spec(tmp, "Vacia")["dir"]
    r = R.score_spec_dir(d)
    assert any("placeholder" in n for n in r["notes"])