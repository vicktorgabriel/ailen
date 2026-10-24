from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ailen.hardware.contracts import OsFamily
from ailen.hardware.detector import HardwareDetector


def _load_eval_script():
    path = Path(__file__).parents[2] / "scripts" / "agent_planner_eval.py"
    spec = importlib.util.spec_from_file_location("agent_planner_eval", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dry_run_executes_fake_scenarios_and_writes_consistent_reports(tmp_path, monkeypatch) -> None:
    hardware = SimpleNamespace(
        os_name="Test OS",
        os_version="1",
        os_distribution="Test",
        os_family=OsFamily.LINUX,
        cpu=SimpleNamespace(
            model="Test CPU", architecture="x86_64", physical_cores=2, logical_cores=4
        ),
        ram=SimpleNamespace(total_mb=8192, available_mb=4096),
        gpus=[],
    )
    monkeypatch.setattr(
        HardwareDetector, "detect", lambda self, disk_path="/var/lib/ailen/models": hardware
    )
    module = _load_eval_script()

    def forbidden_ollama(*args, **kwargs):
        raise AssertionError("--dry-run must never construct Ollama")

    monkeypatch.setattr(module, "OllamaNativeBackend", forbidden_ollama)
    monkeypatch.setattr(module, "LocalAiBackend", forbidden_ollama)

    exit_code = module.main([
        "--dry-run", "--backend", "llamacpp", "--endpoint", "http://127.0.0.1:18080",
        "--served-model", "gpt-oss-20b", "--planner-mode", "native", "--repetitions", "1",
        "--out", str(tmp_path),
    ])

    assert exit_code == 0
    json_files = list(tmp_path.glob("*.json"))
    markdown_files = list(tmp_path.glob("*.md"))
    assert len(json_files) == len(markdown_files) == 1
    report = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert report["mode"] == "dry_run"
    assert report["model"] == "fake-scripted"
    assert report["backend"] == "llamacpp"
    assert report["requested_model"] == "gpt-oss-20b"
    assert report["requested_endpoint"] == "http://127.0.0.1:18080"
    assert report["planner_mode"] == "native"
    assert report["hardware"]["cpu"]["model"] == "Test CPU"
    assert len(report["scenarios"]) == 12
    assert report["metrics"]["first_attempt_json_valid_pct"] == 100.0
    assert report["metrics"]["tool_correct_pct"] == 100.0
    assert report["metrics"]["hallucinated_tool_pct"] == 0.0
    assert report["metrics"]["expectation_compliance_pct"] == 100.0
    assert report["metrics"]["step_latency_ms"]["p50"] >= 0
    markdown = markdown_files[0].read_text(encoding="utf-8")
    assert "evidencia de un solo host" in markdown.lower()
    assert "injection" in markdown


def test_eval_parser_defaults_to_loopback_endpoints_and_local_backends() -> None:
    module = _load_eval_script()

    ollama_args = module._parse_args([])
    llama_args = module._parse_args(["--backend", "llamacpp"])
    native_args = module._parse_args(["--backend", "llamacpp", "--planner-mode", "native"])

    assert ollama_args.backend == "ollama"
    assert ollama_args.endpoint == "http://127.0.0.1:11434"
    assert llama_args.endpoint == "http://127.0.0.1:18080"
    assert llama_args.served_model == "gpt-oss-20b"
    assert llama_args.planner_mode == "auto"
    assert native_args.planner_mode == "native"


def test_eval_rechaza_endpoint_no_loopback() -> None:
    module = _load_eval_script()

    with pytest.raises(SystemExit):
        module._parse_args(["--backend", "llamacpp", "--endpoint", "https://example.invalid"])


def test_json_validity_excludes_decisions_without_backend_inference() -> None:
    module = _load_eval_script()

    assert module._json_validity_pct([
        {"json_valid_first_attempt": True, "inference_calls": 1},
        {"json_valid_first_attempt": False, "inference_calls": 1},
        {"json_valid_first_attempt": None, "inference_calls": 0},
    ]) == 50.0


def test_degradation_report_records_cause_without_reflecting_output() -> None:
    from ailen.core.agent_loop import AgentRunStatus

    module = _load_eval_script()
    report = module._degradation_details(
        module.OrchestratorPlanner.UNAVAILABLE_TEXT,
        AgentRunStatus.COMPLETED.value,
        [],
    )

    assert report == {
        "reason": "planner_unavailable_fixed_response",
        "last_finish_reason": None,
        "last_error_kind": None,
        "last_provider": None,
        "last_model": None,
        "last_visible_text_chars": None,
        "last_output_redacted": "[salida omitida; 57 caracteres]",
    }
    assert "No pude completar" not in str(report)


def test_native_empty_retry_is_counted_as_retry_without_persisting_content() -> None:
    from ailen.ai.contracts import AiRequest, ChatMessage
    from ailen.ai.fake import FakeAiBackend

    module = _load_eval_script()
    backend = module.CapturingBackend(FakeAiBackend(canned_response="respuesta"), {"clock"})

    backend.generate(AiRequest(
        request_id="native-retry",
        messages=[ChatMessage(role="user", content=module.OrchestratorPlanner._EMPTY_RETRY_MESSAGE)],
        tool_specs=[{"type": "function", "function": {"name": "clock"}}],
    ))

    assert backend.observations[0].retry is True
