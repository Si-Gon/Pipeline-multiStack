"""Tests de la detección de stack del proyecto."""
import run_agents_v2 as R


def test_detecta_maven_por_pom(tmp_path):
    (tmp_path / "pom.xml").write_text("<project></project>", encoding="utf-8")
    (tmp_path / "src").mkdir(exist_ok=True)
    stack = R.detect_stack(str(tmp_path))
    assert stack["runner"] == "maven"


def test_detecta_pytest_por_test_py(tmp_path):
    # detect_stack exige marker de paquete python (pyproject/setup/requirements)
    # ADEMÁS de archivos de test.
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / "test_app.py").write_text("def test_x(): pass", encoding="utf-8")
    stack = R.detect_stack(str(tmp_path))
    assert stack["runner"] == "pytest"


def test_detecta_pyproject_con_pytest(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (tmp_path / "tests").mkdir(exist_ok=True)  # carpeta tests → has_test_files
    stack = R.detect_stack(str(tmp_path))
    assert stack["runner"] == "pytest"


def test_detecta_none_sin_archivos(tmp_path):
    # proyecto vacío → sin runner detectable
    stack = R.detect_stack(str(tmp_path))
    assert stack["runner"] == "none"


def test_detect_node_por_package_json(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"test": "jest"}}', encoding="utf-8")
    stack = R.detect_stack(str(tmp_path))
    assert stack["runner"] == "npm"