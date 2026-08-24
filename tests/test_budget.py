"""Tests del presupuesto de contexto inyectado (--budget-inject)."""
import run_agents_v2 as R


def _write_context(project, blocks):
    """Escribe un .opencode-context.md con markers reales para los agentes dados."""
    content = ""
    for agent, text in blocks.items():
        content += text + "\n<!-- AGENT_DONE: {} -->\n\n".format(agent)
    (project / ".opencode-context.md").write_text(content, encoding="utf-8")


def test_budget_no_degrade_con_contexto_normal(tmp_project):
    """Con un presupuesto alto (9000), el contexto no se recorta ni pierde marca."""
    _write_context(tmp_project, {
        "explorer": "## explorer\nexploré el proyecto\n## Mensaje para el siguiente agente\n**Para @coder:** haz X",
    })
    blocks = R.parse_context_blocks(str(tmp_project))
    assert "explorer" in blocks

    ctx = R.enforce_context_budget(str(tmp_project), "coder", budget=9000)
    assert "[... CONTEXTO RECORTADO" not in ctx
    assert "exploré el proyecto" in ctx
    assert "-- FIN CONTEXTO INYECTADO --" in ctx


def test_budget_fuerza_recorte_y_marca(tmp_project):
    """Con un presupuesto muy bajo, recorta el bloque grande y marca el recorte."""
    _write_context(tmp_project, {
        "explorer": "## explorer\n" + ("x" * 4000) +
                    "\n## Mensaje para el siguiente agente\n**Para @coder:** haz Y",
    })
    ctx = R.enforce_context_budget(str(tmp_project), "coder", budget=50)
    assert "[... CONTEXTO RECORTADO" in ctx
    # El bloque original eran 4000 x's (~1000 tokens); el recorte debe ser mucho menor.
    # budget=50 → recorta a ~200 chars (50*4) + header. Verificamos que no se coló
    # el bloque casi completo: el contexto no puede exceder ~350 chars / ~88 tokens.
    assert R.est_tokens(ctx) <= 90  # margen para header + marker de recorte


def test_est_tokens_es_aproximado_pero_positivo():
    """est_tokens estima ~4 chars/token y nunca devuelve negativo."""
    assert R.est_tokens("") == 0
    assert R.est_tokens("hola mundo") > 0
    assert R.est_tokens("a" * 40) == 10


def test_budget_cero_usa_detection_normal_sin_recorte(tmp_project):
    """budget<=0 debe usar build_injected_context (sin recorte por presupuesto)."""
    _write_context(tmp_project, {"explorer": "## explorer\ncontenido base"})
    obj = R.build_agent_objective(str(tmp_project), "coder", "objetivo test", budget=0)
    assert "contenido base" in obj
    assert "[... CONTEXTO RECORTADO" not in obj