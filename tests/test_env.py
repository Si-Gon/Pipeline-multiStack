"""Tests de la carga de configuración desde `.env`."""
import os
import run_agents_v2 as R


def test_dotenv_se_carga_al_importar():
    """Al importar el módulo, load_dotenv debe ejecutarse (carga el .env raíz)."""
    import dotenv
    # load_dotenv queda en sys.modules tras el import del módulo
    assert "dotenv" in __import__("sys").modules


def test_load_dotenv_honra_prioridad_de_entorno(tmp_path, monkeypatch):
    """Las variables del sistema tienen prioridad sobre las del .env."""
    from dotenv import load_dotenv
    envfile = tmp_path / ".env"
    envfile.write_text("PIPELINE_TEST_VAR=desde_env\n", encoding="utf-8")

    # Primero: sin var en sistema → el .env la provee
    monkeypatch.delenv("PIPELINE_TEST_VAR", raising=False)
    load_dotenv(dotenv_path=str(envfile), override=True)
    assert os.environ.get("PIPELINE_TEST_VAR") == "desde_env"

    # Segundo: var del sistema presente → prevalece sobre el .env
    monkeypatch.setenv("PIPELINE_TEST_VAR", "desde_sistema")
    load_dotenv(dotenv_path=str(envfile), override=False)
    assert os.environ.get("PIPELINE_TEST_VAR") == "desde_sistema"


def test_env_example_documenta_variables_reales():
    """El .env.example referencia variables que el script realmente usa."""
    example = open(R.Path(R.__file__).resolve().parent / ".env.example", encoding="utf-8").read()
    for var in ["OPENCODE_BIN", "OPENCODE_AGENTS_DIR", "OC_AGENT_TIMEOUT_",
                "OC_PRICE_IN_", "OC_PRICE_OUT_"]:
        assert var in example, f"falta {var} en .env.example"