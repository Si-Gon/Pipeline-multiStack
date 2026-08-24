"""Tests del punto de entrada CLI (main) y la detección de stack."""
import run_agents_v2 as R


def test_parse_args_objetivo_corto():
    proj, obj, resume, mcp, no_mcp, budget = R.parse_args(["mi-proyecto", "hacer login"])
    assert proj == "mi-proyecto"
    assert obj == "hacer login"
    assert resume is False
    assert budget == R.DEFAULT_CONTEXT_BUDGET_TOKENS


def test_parse_args_budget_personalizado():
    args = R.parse_args(["mi-proyecto", "objetivo", "--budget-inject", "500"])
    assert args[5] == 500


def test_parse_args_resume_flag():
    args = R.parse_args(["mi-proyecto", "objetivo", "--resume"])
    assert args[2] is True


def test_main_ruta_inexistente_sale_1(capsys):
    """`pipeline run` con una ruta que no existe debe imprimir error y salir(1)."""
    import pytest
    with pytest.raises(SystemExit) as e:
        R.main(["run", "C:\\\\ruta\\\\que\\\\no\\\\existe\\\\xyz", "objetivo"])
    assert e.value.code == 1


def test_main_run_prefiere_subcomando():
    """`pipeline run <proyecto> "objetivo"` resuelve el subcomando run."""
    import pytest
    with pytest.raises(SystemExit) as e:
        R.main(["run", "C:\\\\ruta\\\\inexistente", "objetivo"])
    assert e.value.code == 1  # llega a validación de ruta tras parsear run


def test_main_resume_fuerza_flag():
    """`pipeline resume <proyecto> "objetivo"` debe inyectar --resume al parsear."""
    import pytest
    with pytest.raises(SystemExit) as e:
        R.main(["resume", "C:\\\\ruta\\\\inexistente", "objetivo"])
    assert e.value.code == 1  # valida ruta tras parsear con --resume forzado


def test_main_subcomando_desconocido_sale_2():
    """Un primer token no reconocido imprime error y sale 2."""
    import pytest
    with pytest.raises(SystemExit) as e:
        R.main(["fruta"])
    assert e.value.code == 2


def test_main_ayuda_sale_0():
    """`pipeline help` imprime ayuda y sale 0."""
    import pytest
    with pytest.raises(SystemExit) as e:
        R.main(["help"])
    assert e.value.code == 0


def test_main_invoca_argv_vacio_tipico():
    """main() sin argumentos imprime la ayuda y sale con código 2."""
    import pytest
    with pytest.raises(SystemExit) as e:
        R.main([])
    assert e.value.code == 2


def test_main_dispatch_status_sin_proyecto():
    """`pipeline status` sin ruta imprime error y sale 2."""
    import pytest
    with pytest.raises(SystemExit) as e:
        R.main(["status"])
    assert e.value.code == 2


def test_main_dispatch_status_ruta_inexistente(tmp_path, capsys):
    """status con ruta inexistente sale 1."""
    import pytest
    with pytest.raises(SystemExit) as e:
        R.main(["status", str(tmp_path / "no-existe")])
    assert e.value.code == 1


def test_cmd_status_muestra_json(tmp_project, capsys):
    """status imprime el contenido legible de pipeline-status.json."""
    R._write_status(str(tmp_project), last_step="coder", status="failed",
                    failed="tester", log_path="pipeline-x.log")
    R.cmd_status(str(tmp_project))
    out = capsys.readouterr().out
    assert "failed" in out
    assert "coder" in out
    assert "tester" in out


def test_cmd_status_sin_json(tmp_project, capsys):
    """status sin pipeline-status.json avisa y no falla."""
    R.cmd_status(str(tmp_project))
    out = capsys.readouterr().out
    assert "no hay pipeline-status.json" in out


def test_cmd_cost_sin_logs(tmp_project, capsys):
    """cost sin logs avisa y no falla."""
    R.cmd_cost(str(tmp_project))
    out = capsys.readouterr().out
    assert "no hay logs" in out


def test_cmd_cost_con_log(tmp_project, capsys):
    """cost extrae y muestra la sección COSTO ESTIMADO del log más reciente."""
    adir = tmp_project / R.ARTIFACTS_DIR
    adir.mkdir(exist_ok=True)
    log = adir / "pipeline-20260824.log"
    log.write_text(
        "[INFO] algo\n"
        "[COSTO ESTIMADO] por modelo (USD):\n"
        "  opencode-go/deepseek-v4-flash in~5000 out~2000 -> $0.0033\n"
        "  TOTAL -> $0.0033\n"
        "[INFO] fin\n",
        encoding="utf-8",
    )
    R.cmd_cost(str(tmp_project))
    out = capsys.readouterr().out
    assert "[COSTO ESTIMADO]" in out
    assert "$0.0033" in out
    assert "TOTAL" in out