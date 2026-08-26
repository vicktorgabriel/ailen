"""Unit tests for Time To First Audible Response (TTFAR) metric tracking."""

import pytest

from ailen.runtime.metrics import LabSessionMetrics


def test_ttfar_recording_and_averaging() -> None:
    m = LabSessionMetrics(session_id="test-session")
    m.record_ttfar(850.0)
    m.record_ttfar(950.0)
    m.record_ttfar(1200.0)

    d = m.to_dict()
    speech = d["speech"]
    assert speech["ttfar_avg_ms"] == 1000.0
    assert speech["ttfar_p95_ms"] is not None
    assert speech["ttfar_p95_ms"] >= 1000.0


def test_lab_runner_ttfar_handlers_record_real_interval(monkeypatch) -> None:
    from ailen.core.config import AILENConfig
    from ailen.runtime.runner import LabRunner

    runner = LabRunner(AILENConfig(), dry_run=True, headless=True, no_camera=True)
    values = iter([10.0, 10.85])
    monkeypatch.setattr("ailen.runtime.runner.time.monotonic", lambda: next(values))
    runner._on_voice_ended_event(None)
    runner._on_speech_started_event(None)
    assert runner.metrics.ttfar_latencies_ms == [pytest.approx(850.0)]


def test_ai_metrics_separate_prompt_and_generation_latency() -> None:
    metrics = LabSessionMetrics(session_id="test-ai-stages")
    metrics.record_ai_call(
        latency_ms=900.0,
        in_tokens=100,
        out_tokens=20,
        prompt_eval_ms=300.0,
        generation_ms=500.0,
        load_ms=10.0,
    )

    ai = metrics.to_dict()["ai"]
    assert ai["prompt_eval_avg_ms"] == 300.0
    assert ai["generation_avg_ms"] == 500.0
    assert ai["load_avg_ms"] == 10.0
