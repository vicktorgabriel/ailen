"""Unit tests for LabRunner and LabDoctor."""

from tempfile import TemporaryDirectory

from ailen.core.config import load_config
from ailen.runtime.doctor import LabDoctor
from ailen.runtime.runner import LabRunner


def test_lab_doctor_run_checks() -> None:
    cfg = load_config(None)
    doctor = LabDoctor(config=cfg)
    checks = doctor.run_all_checks()
    assert len(checks) >= 6

    check_names = [c.name for c in checks]
    assert "Python Environment" in check_names
    assert "CPU Instruction Sets" in check_names
    assert "System Memory" in check_names
    assert "Local AI Runtime" in check_names

    # Doctor print report should return 0 (pass or warning) or 1 on test host
    ret = doctor.print_report()
    assert ret in (0, 1)


def test_lab_runner_dry_run_and_component_lifecycle() -> None:
    cfg = load_config(None)
    with TemporaryDirectory() as tmpdir:
        runner = LabRunner(
            config=cfg,
            dry_run=True,
            headless=True,
            no_camera=True,
            no_audio=True,
            no_ai=True,
            log_dir=tmpdir,
        )

        ret = runner.start()
        assert ret == 0
        assert len(runner.component_statuses) > 0

        states = {s.name: s.state for s in runner.component_statuses}
        assert states["Face"] == "READY"
        assert states["Vision"] == "DISABLED"
        assert states["Audio"] == "DISABLED"
        assert states["AI Inference"] == "DISABLED"


def test_lab_runner_duration_timed_execution() -> None:
    cfg = load_config(None)
    with TemporaryDirectory() as tmpdir:
        runner = LabRunner(
            config=cfg,
            dry_run=False,
            headless=True,
            no_camera=True,
            no_audio=True,
            no_ai=True,
            duration=0.05,  # 50 ms timed run
            log_dir=tmpdir,
        )

        ret = runner.start()
        assert ret == 0
