"""Tests de pipeline-status.json y mapeo de exit codes."""
import json
import run_agents_v2 as R


def test_write_status_ok(tmp_project):
    R._write_status(str(tmp_project), last_step="sdd-updater", status="ok",
                    failed=None, log_path="pipeline-1.log")
    p = tmp_project / R.STATUS_FILE
    assert p.exists()
    j = json.loads(p.read_text(encoding="utf-8"))
    assert j["status"] == "ok"
    assert j["failed_step"] is None
    assert j["last_completed_step"] == "sdd-updater"
    assert "timestamp" in j


def test_write_status_fallido(tmp_project):
    R._write_status(str(tmp_project), last_step="coder", status="failed",
                    failed="tester", log_path="pipeline-2.log")
    j = json.loads((tmp_project / R.STATUS_FILE).read_text(encoding="utf-8"))
    assert j["failed_step"] == "tester"
    assert j["status"] == "failed"


def test_phase_exit_codes_mapeo_completo():
    assert R.PHASE_EXIT_CODES == {
        "explorer": 2, "coder": 3, "tester": 4,
        "debugger": 5, "sdd-updater": 6,
    }
    # códigos únicos (ninguna fase comparte exit code)
    assert len(set(R.PHASE_EXIT_CODES.values())) == len(R.PHASE_EXIT_CODES)


def test_status_file_sobreescribe_anterior(tmp_project):
    R._write_status(str(tmp_project), last_step="a", status="failed", failed="a", log_path="x")
    R._write_status(str(tmp_project), last_step="b", status="ok", failed=None, log_path="y")
    j = json.loads((tmp_project / R.STATUS_FILE).read_text(encoding="utf-8"))
    assert j["last_completed_step"] == "b"
    assert j["status"] == "ok"