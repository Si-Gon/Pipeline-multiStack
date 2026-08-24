"""Tests de la config por proyecto (pipeline.yaml) y el desacople de modelos/runner (F4)."""
import os
import run_agents_v2 as R


def test_sin_pipeline_yaml_usa_defaults(tmp_project):
    """Sin pipeline.yaml, devuelve los modelos default."""
    cfg = R.load_pipeline_config(str(tmp_project))
    assert cfg["models"] == R.DEFAULT_AGENT_MODELS
    assert cfg["runner"]["name"] == R.DEFAULT_RUNNER_NAME
    assert cfg["budget"] == R.DEFAULT_CONTEXT_BUDGET_TOKENS


def test_pipeline_yaml_sobreescribe_modelo(tmp_project):
    """pipeline.yaml puede cambiar el modelo de un rol específico."""
    (tmp_project / "pipeline.yaml").write_text(
        "models:\n  coder: opencode-go/my-custom-model\n", encoding="utf-8")
    R._config_cache.pop(str(tmp_project), None)  # limpiar cache
    model = R.get_agent_model(str(tmp_project), "coder")
    assert model == "opencode-go/my-custom-model"
    # los demás roles conservan el default
    assert R.get_agent_model(str(tmp_project), "tester") == R.DEFAULT_MODEL_CODING


def test_pipeline_yaml_budget(tmp_project):
    """pipeline.yaml puede cambiar el budget por proyecto."""
    (tmp_project / "pipeline.yaml").write_text("budget: 5000\n", encoding="utf-8")
    R._config_cache.pop(str(tmp_project), None)
    cfg = R.load_pipeline_config(str(tmp_project))
    assert cfg["budget"] == 5000


def test_pipeline_yaml_runner_template(tmp_project):
    """pipeline.yaml puede definir un run_template (puerta para otros CLIs)."""
    (tmp_project / "pipeline.yaml").write_text(
        "runner:\n  name: claude-code\n  binary: claude\n"
        "  run_template: \"{binary} -p {objective_file} --model {model}\"\n",
        encoding="utf-8")
    R._config_cache.pop(str(tmp_project), None)
    cfg = R.load_pipeline_config(str(tmp_project))
    assert cfg["runner"]["name"] == "claude-code"
    assert cfg["runner"]["binary"] == "claude"
    assert cfg["runner"]["run_template"] is not None


def test_run_agent_usa_modelo_configurado(tmp_project, monkeypatch):
    """run_agent resuelve el modelo desde pipeline.yaml, no del default."""
    (tmp_project / "pipeline.yaml").write_text(
        "models:\n  coder: opencode-go/custom-coder\n", encoding="utf-8")
    captured = {}
    def fake_build(runner, project_path, obj_file, agent, model):
        captured["model"] = model
        return ["echo", "noop"]
    monkeypatch.setattr(R, "_build_runner_cmd", fake_build)
    R.run_agent("coder", str(tmp_project), "obj test", _FakeLogger())
    assert captured["model"] == "opencode-go/custom-coder"


class _FakeLogger:
    """Mínimo logger para tests de run_agent (solo .info/.error)."""
    def __init__(self):
        self.log_path = "fake.log"
    def info(self, msg): pass
    def log(self, msg, level=None): pass
    def error(self, agent, snippet): pass
    def warn(self, msg): pass
    def add_cost(self, *a, **k): pass


def test_get_model_pricing_default_para_desconocido():
    """Modelos no listados usan DEFAULT_PRICING."""
    assert R.get_model_pricing("modelo/desconocido") == R.DEFAULT_PRICING


def test_apply_profile_rapido():
    """El perfil 'rapido' sobreescribe todos los roles al modelo fast."""
    cfg = {"models": dict(R.DEFAULT_AGENT_MODELS), "budget": R.DEFAULT_CONTEXT_BUDGET_TOKENS}
    R.apply_profile(cfg, "rapido")
    assert cfg["models"]["coder"] == R.DEFAULT_MODEL_FAST
    assert cfg["budget"] == 4000


def test_apply_profile_minucioso():
    """El perfil 'minucioso' usa el modelo de debug para todos + budget alto."""
    cfg = {"models": dict(R.DEFAULT_AGENT_MODELS), "budget": R.DEFAULT_CONTEXT_BUDGET_TOKENS}
    R.apply_profile(cfg, "minucioso")
    assert cfg["models"]["coder"] == R.DEFAULT_MODEL_DEBUG
    assert cfg["models"]["tester"] == R.DEFAULT_MODEL_DEBUG
    assert cfg["budget"] == 12000


def test_apply_profile_equilibrado_default():
    """El perfil 'equilibrado' conserva los modelos default."""
    cfg = {"models": dict(R.DEFAULT_AGENT_MODELS), "budget": R.DEFAULT_CONTEXT_BUDGET_TOKENS}
    R.apply_profile(cfg, "equilibrado")
    assert cfg["models"]["coder"] == R.DEFAULT_MODEL_CODING
    assert cfg["budget"] == R.DEFAULT_CONTEXT_BUDGET_TOKENS


def test_apply_profile_inexistente_no_cambia():
    """Un perfil desconocido se ignora (no rompe)."""
    cfg = {"models": dict(R.DEFAULT_AGENT_MODELS), "budget": 5000}
    R.apply_profile(cfg, "no-existe")
    assert cfg["budget"] == 5000