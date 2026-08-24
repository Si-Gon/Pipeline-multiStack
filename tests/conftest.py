"""Fixtures compartidos para los tests del pipeline."""
import os
import sys
import pytest

# Asegura que el módulo raíz (run_agents_v2.py) sea importable desde los tests,
# tanto en layout flat (raíz) como tras `pip install -e .`.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture
def tmp_project(tmp_path):
    """Crea una estructura mínima de proyecto para correr detect_stack sin
    llamar a opencode: un .opencode-context.md vacío y una carpeta pipeline-artifacts."""
    (tmp_path / ".opencode-context.md").write_text(
        "## Contexto del Proyecto\n\n", encoding="utf-8"
    )
    (tmp_path / "pipeline-artifacts").mkdir(exist_ok=True)
    return tmp_path