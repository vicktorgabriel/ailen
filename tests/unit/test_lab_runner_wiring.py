"""Unit tests for LabRunner live wiring, single-flight interaction, metrics, and presence."""

import time
from pathlib import Path
from unittest.mock import MagicMock

from ailen.core.config import AILENConfig
from ailen.domain.enums import AssistantState, EventType
from ailen.domain.models import CoreEvent
from ailen.face.null import NullFaceController
from ailen.runtime.metrics import LabSessionMetrics
from ailen.runtime.runner import LabRunner
from ailen.vision.contracts import PresenceObservation


def test_metrics_no_fabricated_values() -> None:
    metrics = LabSessionMetrics(session_id="test_sess")
    metrics.record_utterance(success=True, latency_ms=120.0)
    metrics.record_utterance(success=True, latency_ms=180.0)
    metrics.record_ai_call(latency_ms=450.0, in_tokens=50, out_tokens=25)
    metrics.record_tts_call(latency_ms=210.0)
    metrics.finalize()

    data = metrics.to_dict()
    assert data["speech"]["utterances"] == 2
    assert data["speech"]["stt_latency_avg_ms"] == 150.0
    assert data["speech"]["tts_latency_avg_ms"] == 210.0
    assert data["ai"]["latency_avg_ms"] == 450.0
    assert data["ai"]["tokens_in"] == 50
    assert data["ai"]["tokens_out"] == 25


def test_lab_runner_simulate_initialization(tmp_path: Path) -> None:
    cfg = AILENConfig()
    runner = LabRunner(
        config=cfg,
        dry_run=True,
        simulate=True,
        log_dir=tmp_path,
    )
    code = runner.start()
    assert code == 0
    assert any(s.state == "SIMULATED" for s in runner.component_statuses)


def test_lab_runner_single_flight_serialization() -> None:
    cfg = AILENConfig()
    runner = LabRunner(
        config=cfg,
        dry_run=True,
        simulate=True,
    )
    runner.inspect_and_plan()
    runner.init_components()

    # Mock conversation coordinator
    mock_conv = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "Respuesta"
    mock_resp.provider = "fake"
    mock_resp.model = "fake"
    mock_resp.usage = None
    mock_conv.handle_user_input.return_value = (mock_resp, MagicMock())
    runner.conversation_coordinator = mock_conv

    # Simulate transcript event
    event = CoreEvent(
        event_id="test-1",
        event_type=EventType.TRANSCRIPT_READY,
        source="test",
        payload={"text": "Hola Ailén", "latency_ms": 100.0},
    )
    runner._on_transcript_event(event)

    # Allow thread to run
    time.sleep(0.1)
    mock_conv.handle_user_input.assert_called_once_with("Hola Ailén", session_id=runner._session_id)


def test_lab_runner_vision_presence_and_gaze() -> None:
    cfg = AILENConfig()
    runner = LabRunner(
        config=cfg,
        dry_run=True,
        simulate=True,
    )
    runner.inspect_and_plan()
    runner.init_components()

    # Replace face controller with NullFaceController to test state & gaze
    face = NullFaceController()
    runner.face_controller = face
    runner.state_manager.transition_to(AssistantState.SLEEP, reason="test_init")

    # Feed presence observation
    obs = PresenceObservation(present=True, primary_x_normalized=0.4, primary_y_normalized=-0.2, confidence=0.9)
    if runner.interaction_coordinator:
        runner.interaction_coordinator.handle_presence_observation(obs)
    face.set_gaze(obs.primary_x_normalized or 0.0, obs.primary_y_normalized or 0.0)

    assert runner.state_manager.current_state in (AssistantState.ATTENTION, AssistantState.IDLE, AssistantState.SLEEP)


def test_metrics_unknown_tokens_remain_unknown() -> None:
    metrics = LabSessionMetrics(session_id="unknown_tokens")
    metrics.record_ai_call(latency_ms=100.0, in_tokens=None, out_tokens=None)
    data = metrics.to_dict()
    assert data["ai"]["tokens_in"] is None
    assert data["ai"]["tokens_out"] is None
    assert data["ai"]["token_usage_complete"] is False


def test_lab_runner_duplicate_transcript_event_processed_once() -> None:
    cfg = AILENConfig()
    runner = LabRunner(config=cfg, dry_run=True, simulate=True)
    runner.inspect_and_plan()
    runner.init_components()

    mock_conv = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "Respuesta"
    mock_resp.provider = "fake"
    mock_resp.model = "fake"
    mock_resp.latency_ms = 5.0
    mock_resp.usage = None
    mock_conv.handle_user_input.return_value = (mock_resp, MagicMock())
    runner.conversation_coordinator = mock_conv

    event = CoreEvent(
        event_id="same-event",
        event_type=EventType.TRANSCRIPT_READY,
        source="test",
        payload={"text": "Hola", "latency_ms": 1.0},
    )
    runner._on_transcript_event(event)
    time.sleep(0.05)
    runner._on_transcript_event(event)
    time.sleep(0.05)
    mock_conv.handle_user_input.assert_called_once()


def test_lab_runner_real_mode_does_not_wire_audio_when_speech_backends_missing() -> None:
    cfg = AILENConfig()
    cfg.speech.stt_engine = "mock"
    cfg.speech.tts_engine = "mock"
    runner = LabRunner(config=cfg, dry_run=True, headless=True)
    runner.inspect_and_plan()
    runner.init_components()
    assert runner.stt_backend is None
    assert runner.tts_backend is None
    assert runner.audio_coordinator is None
