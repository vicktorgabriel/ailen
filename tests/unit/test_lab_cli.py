"""Unit tests for 'ailen lab' and 'ailen models' CLI subcommands."""

import json
from io import StringIO
from unittest.mock import patch

from ailen.cli import main


def test_cli_lab_inspect_text_and_json() -> None:
    # 1. Text output
    with patch("sys.stdout", new=StringIO()) as fake_out:
        ret = main(["lab", "inspect"])
        assert ret == 0
        out_text = fake_out.getvalue()
        assert "AILEN LAB HARDWARE INSPECTION" in out_text
        assert "RECOMMENDED PROFILE" in out_text
        assert "RECOMMENDED LOCAL MODEL PLAN" in out_text

    # 2. JSON output
    with patch("sys.stdout", new=StringIO()) as fake_out:
        ret = main(["lab", "inspect", "--json"])
        assert ret == 0
        data = json.loads(fake_out.getvalue())
        assert "hardware" in data
        assert "profile_recommendation" in data
        assert "model_plan" in data


def test_cli_lab_start_dry_run() -> None:
    with (
        patch("sys.stdout", new=StringIO()) as fake_out,
        patch("ailen.cli.setup_logging") as setup_logging,
    ):
        ret = main(["lab", "start", "--dry-run", "--headless", "--no-camera", "--no-audio", "--no-ai"])
        assert ret == 0
        out_text = fake_out.getvalue()
        assert "AILEN LAB COMPONENT STATUS" in out_text
        assert "Dry-run complete" in out_text
        setup_logging.assert_called_once()


def test_cli_lab_start_simulate() -> None:
    with patch("sys.stdout", new=StringIO()) as fake_out:
        ret = main(["lab", "start", "--dry-run", "--simulate"])
        assert ret == 0
        out_text = fake_out.getvalue()
        assert "SIMULATION MODE" in out_text
        assert "SIMULATED" in out_text


def test_cli_lab_doctor_text_and_json() -> None:
    # 1. Text
    with patch("sys.stdout", new=StringIO()) as fake_out:
        ret = main(["lab", "doctor"])
        assert ret in (0, 1)
        out_text = fake_out.getvalue()
        assert "AILEN LAB DOCTOR" in out_text
        assert "Python Environment" in out_text

    # 2. JSON
    with patch("sys.stdout", new=StringIO()) as fake_out:
        ret = main(["lab", "doctor", "--json"])
        assert ret in (0, 1)
        data = json.loads(fake_out.getvalue())
        assert isinstance(data, list)
        assert any(c["name"] == "Python Environment" for c in data)


def test_cli_lab_prepare_ai() -> None:
    with patch("sys.stdout", new=StringIO()) as fake_out:
        ret = main(["lab", "prepare-ai", "--purpose", "SANITY"])
        assert ret == 0
        out_text = fake_out.getvalue()
        assert "AILEN LAB AI PREPARATION" in out_text


def test_cli_lab_benchmark() -> None:
    with patch("sys.stdout", new=StringIO()) as fake_out:
        ret = main(["lab", "benchmark"])
        assert ret == 0
        out_text = fake_out.getvalue()
        assert "Benchmark lab report saved to" in out_text


def test_cli_models_list_text_and_json() -> None:
    # 1. Text output
    with patch("sys.stdout", new=StringIO()) as fake_out:
        ret = main(["models", "list"])
        assert ret == 0
        out_text = fake_out.getvalue()
        assert "MODEL ID" in out_text
        assert "qwen3.5-0.8b-q4_0" in out_text

    # 2. JSON output
    with patch("sys.stdout", new=StringIO()) as fake_out:
        ret = main(["models", "list", "--json"])
        assert ret == 0
        data = json.loads(fake_out.getvalue())
        assert isinstance(data, list)
        assert len(data) >= 5
        assert any(m["model_id"] == "qwen3.5-0.8b-q4_0" for m in data)


def test_cli_models_plan_text_and_json() -> None:
    # 1. Text output
    with patch("sys.stdout", new=StringIO()) as fake_out:
        ret = main(["models", "plan", "--purpose", "BALANCED"])
        assert ret == 0
        out_text = fake_out.getvalue()
        assert "RECOMMENDED MODEL PLAN" in out_text

    # 2. JSON output
    with patch("sys.stdout", new=StringIO()) as fake_out:
        ret = main(["models", "plan", "--json"])
        assert ret == 0
        data = json.loads(fake_out.getvalue())
        assert "runtime" in data
        assert "device" in data
        assert "reason_codes" in data


def test_cli_models_fetch_rejects_unverified_catalog_entry() -> None:
    with patch("sys.stdout", new=StringIO()) as fake_out:
        ret = main(["models", "fetch", "qwen2.5-7b-instruct-q4_k_m", "--yes"])
    assert ret == 1
    assert "not approved for download" in fake_out.getvalue()
