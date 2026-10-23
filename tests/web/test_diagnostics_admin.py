"""Diagnostics must expose measured data, preserve provenance and stay read-only."""
import json
from pathlib import Path
from urllib.parse import urlencode

from ailen.core.config import AILENConfig
from ailen.core.health import HealthService
from ailen.domain.enums import ServiceStatus
from ailen.runtime.doctor import DiagnosticCheck
from ailen.services.diagnostics_admin_service import DiagnosticsAdminService
from ailen.services.status_service import StatusService
from ailen.web.app import AILENWebApp, WebRequest
from ailen.web.services import FakeAuthService


def test_diagnostics_real_status_and_explicit_doctor(tmp_path):
    calls = []
    health = HealthService()
    health.set_component_status("audio", ServiceStatus.UNKNOWN)
    status = StatusService(health)
    service = DiagnosticsAdminService(
        status, lambda: AILENConfig(), tmp_path,
        check_runner=lambda config: calls.append(config) or [
            DiagnosticCheck("Python Environment", "PASS", "secret /private/path"),
            DiagnosticCheck("Audio Devices", "WARN", "password=supersecret"),
        ],
    )
    auth = FakeAuthService("test")
    token, csrf = auth.create_session()
    app = AILENWebApp(auth, status, diagnostics=service)

    def req(method="GET", path="/diagnostico", data=None, authenticated=True):
        return app.handle(WebRequest(method, path,
            headers={"cookie": f"ailen_session={token}"} if authenticated else {},
            body=urlencode(data or {}).encode()))

    body = req().body.decode()
    assert "UNKNOWN" in body and "Sin medición" in body and "Sin ejecutar" in body
    assert "340 ms" not in body and "15.4 tok/s" not in body
    assert calls == []
    assert req(authenticated=False).status == 303
    assert req("POST", "/diagnostico/run").status == 403
    assert req("GET", "/diagnostico/run").status == 405
    response = req("POST", "/diagnostico/run", {"_csrf": csrf})
    assert response.status == 303 and len(calls) == 1
    body = req().body.decode()
    assert "WARN" in body and "Audio Devices" in body
    assert "supersecret" not in body and "/private/path" not in body


def report(mode="real"):
    return {
        "execution_mode": mode, "session_id": "lab-test", "started_at": 1000, "ended_at": 2000,
        "speech": {"stt_latency_avg_ms": 123, "stt_latency_p95_ms": 234,
                   "stt_latency_samples": 2},
        "ai": {}, "turns": {"secret": "should-never-render"},
    }


def test_telemetry_measured_missing_simulated_and_corrupt(tmp_path: Path):
    service = DiagnosticsAdminService(StatusService(HealthService()), lambda: AILENConfig(), tmp_path)
    assert service.snapshot().telemetry.state == "NO_DATA"
    path = tmp_path / "session_2000.json"
    path.write_text(json.dumps(report()))
    telemetry = service.snapshot().telemetry
    assert telemetry.state == "RECORDED" and telemetry.ended_at
    assert telemetry.rows[0].average_ms == 123
    assert telemetry.rows[1].average_ms is None
    assert "should-never-render" not in repr(telemetry)
    for mode in ("simulation", "dry_run", "unknown"):
        path.write_text(json.dumps(report(mode)))
        assert service.snapshot().telemetry.state == "UNVERIFIED"
    path.write_text("{")
    assert service.snapshot().telemetry.state == "UNAVAILABLE"
    path.unlink()
    target = tmp_path / "outside.json"
    target.write_text(json.dumps(report()))
    path.symlink_to(target)
    assert service.snapshot().telemetry.state == "UNAVAILABLE"


def test_doctor_failure_does_not_retain_old_pass_or_leak(tmp_path):
    def failing(config):
        raise RuntimeError("secret-must-not-leak")
    service = DiagnosticsAdminService(StatusService(HealthService()), lambda: AILENConfig(), tmp_path,
                                      check_runner=failing)
    assert service.run_checks() is True
    snapshot = service.snapshot()
    assert snapshot.doctor_state == "UNAVAILABLE"
    assert "secret-must-not-leak" not in repr(snapshot)


def test_overlapping_doctor_execution_rejected(tmp_path):
    import threading
    started, release = threading.Event(), threading.Event()
    def slow(config):
        started.set()
        assert release.wait(3)
        return [DiagnosticCheck("Python Environment", "PASS", "")]
    service = DiagnosticsAdminService(StatusService(HealthService()), lambda: AILENConfig(),
                                      tmp_path, check_runner=slow)
    thread = threading.Thread(target=service.run_checks)
    thread.start()
    try:
        assert started.wait(3)
        assert service.run_checks() is False
        assert service.snapshot().doctor_state == "RUNNING"
    finally:
        release.set()
        thread.join(3)
    assert service.snapshot().doctor_state == "PASS"


def test_doctor_disabled_local_never_discovers_runtimes(monkeypatch):
    from ailen.hardware.detector import HardwareDetector
    from ailen.hardware.fake import FakeHardwareAdapter
    from ailen.runtime.doctor import LabDoctor
    cfg = AILENConfig()
    cfg.ai.local.enabled = False
    report = HardwareDetector(FakeHardwareAdapter()).detect()
    monkeypatch.setattr(HardwareDetector, "detect", lambda *args: report)
    def forbidden(*args):
        raise AssertionError("local discovery forbidden")
    monkeypatch.setattr("ailen.runtime.doctor.LocalRuntimeManager", forbidden)
    checks = LabDoctor(cfg).run_all_checks()
    assert next(c for c in checks if c.name == "Local AI Runtime").result == "SKIP"


def test_metrics_provenance_and_numeric_validation(tmp_path):
    from ailen.runtime.metrics import LabSessionMetrics
    metrics = LabSessionMetrics("test", execution_mode="real")
    metrics.record_utterance(True, 77)
    metrics.record_ai_call(300)
    metrics.finalize()
    data = metrics.to_dict()
    assert data["speech"]["stt_latency_samples"] == 1
    assert data["ai"]["latency_samples"] == 1
    path = tmp_path / "session_1.json"
    path.write_text(json.dumps(data))
    service = DiagnosticsAdminService(StatusService(HealthService()), lambda: AILENConfig(), tmp_path)
    assert service.snapshot().telemetry.rows[0].average_ms == 77
    for bad_value in (True, -1, "300", float("nan"), float("inf")):
        data["speech"]["stt_latency_avg_ms"] = bad_value
        path.write_text(json.dumps(data))
        assert service.snapshot().telemetry.rows[0].average_ms is None
    path.write_bytes(b" " * (1024 * 1024 + 1))
    assert service.snapshot().telemetry.state == "UNAVAILABLE"


def test_runner_labels_simulation_and_real():
    from ailen.runtime.runner import LabRunner
    assert LabRunner(AILENConfig(), simulate=True).metrics.execution_mode == "simulation"
    assert LabRunner(AILENConfig(), dry_run=True).metrics.execution_mode == "dry_run"
    assert LabRunner(AILENConfig()).metrics.execution_mode == "real"
