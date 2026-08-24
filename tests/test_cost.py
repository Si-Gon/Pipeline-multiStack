"""Tests del reporte de costo estimado y del contador por modelo."""
import threading
import run_agents_v2 as R


class _FakeLogger:
    """Contenedor mínimo que expone los atributos que usa add_cost/cost_report."""
    def __init__(self):
        self.log_path = "fake.log"
        self._cost = {}
        self._cost_lock = threading.Lock()


def test_add_cost_acumula_por_modelo():
    lg = _FakeLogger()
    R.PipelineLogger.add_cost(lg, R.DEFAULT_MODEL_FAST, 1000, 500)
    R.PipelineLogger.add_cost(lg, R.DEFAULT_MODEL_FAST, 2000, 1000)
    assert lg._cost[R.DEFAULT_MODEL_FAST] == [3000, 1500]


def test_cost_report_muestra_modelos_y_total():
    lg = _FakeLogger()
    R.PipelineLogger.add_cost(lg, R.DEFAULT_MODEL_FAST, 5000, 2000)
    R.PipelineLogger.add_cost(lg, R.DEFAULT_MODEL_CODING, 12000, 3000)
    rep = R.PipelineLogger.cost_report(lg)
    assert "deepseek-v4-flash" in rep
    assert "qwen3.7" in rep
    assert "$0.0033" in rep   # 5000/1e6*0.25 + 2000/1e6*1.00
    assert "$0.0216" in rep   # 12000/1e6*1.20 + 3000/1e6*2.40
    assert "TOTAL" in rep


def test_cost_report_vacio():
    lg = _FakeLogger()
    assert "sin actividad" in R.PipelineLogger.cost_report(lg)


def test_ignore_modelo_invalido():
    lg = _FakeLogger()
    R.PipelineLogger.add_cost(lg, None, 100, 100)
    assert lg._cost == {}  # no registra si model es None/empty