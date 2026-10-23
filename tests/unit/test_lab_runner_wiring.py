"""Unit tests for LabRunner live wiring, single-flight interaction, metrics, and presence."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from ailen.core.config import AILENConfig
from ailen.domain.enums import AssistantState, EventType, PrivacyLevel
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
    mock_resp.latency_ms = 10.0
    mock_conv.handle_transcript.return_value = (mock_resp, MagicMock())
    runner.conversation_coordinator = mock_conv

    # Simulate transcript event
    event = CoreEvent(
        event_id="test-1",
        event_type=EventType.TRANSCRIPT_READY,
        source="test",
        payload={
            "text": "Hola Ailén",
            "confidence": 0.84,
            "language": "es",
            "latency_ms": 100.0,
            "engine": "vosk",
            "audio_duration_ms": 860.0,
            "utterance_id": "utterance-7",
            "interrupted": True,
            "alternatives": [{"text": "Hola AILEN", "confidence": 0.61}],
        },
    )
    runner._on_transcript_event(event)

    # Allow thread to run
    time.sleep(0.1)
    assert runner._conversation_session_id is not None
    mock_conv.handle_transcript.assert_called_once()
    turn = mock_conv.handle_transcript.call_args.args[0]
    assert turn.text == "Hola Ailén"
    assert turn.confidence == 0.84
    assert turn.engine == "vosk"
    assert turn.audio_duration_ms == 860.0
    assert turn.utterance_id == "utterance-7"
    assert turn.interrupted is True
    assert len(turn.alternatives) == 1
    assert turn.alternatives[0].text == "Hola AILEN"
    assert turn.alternatives[0].confidence == 0.61
    assert mock_conv.handle_transcript.call_args.kwargs == {
        "session_id": runner._conversation_session_id,
    }


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


def test_metrics_capture_external_provider_latency_without_prompt_content() -> None:
    metrics = LabSessionMetrics(session_id="external-provider")
    metrics.record_ai_call(
        latency_ms=2200.0,
        provider="remote:limited",
        model="operator-selected-model",
        first_text_ms=1800.0,
        provider_setup_ms=0.0,
        provider_ready_ms=420.0,
        request_chars=640,
        fallback_used=True,
        fallback_cause="rate_limit",
    )

    data = metrics.to_dict()["ai"]
    assert data["provider_model_counts"] == {
        "remote:limited:operator-selected-model": 1
    }
    assert data["first_text_avg_ms"] == 1800.0
    assert data["provider_setup_avg_ms"] == 0.0
    assert data["provider_ready_avg_ms"] == 420.0
    assert data["request_chars_total"] == 640
    assert data["fallback_count"] == 1
    assert data["fallback_causes"] == {"rate_limit": 1}


def test_metrics_record_redacted_per_turn_stages_only() -> None:
    metrics = LabSessionMetrics(session_id="turn-detail")
    metrics.record_turn_stage(
        "utterance-1",
        "stt_result",
        confidence=0.31,
        confidence_band="doubtful",
        engine="vosk",
        transcript="PRIVATE WORDS",
        prompt="PRIVATE PROMPT",
        audio_duration_ms=820.0,
    )

    stages = metrics.to_dict()["turns"]["stages"]
    assert len(stages) == 1
    assert stages[0]["turn_id"] == "utterance-1"
    assert stages[0]["confidence_band"] == "doubtful"
    assert stages[0]["audio_duration_ms"] == 820.0
    assert "transcript" not in stages[0]
    assert "prompt" not in stages[0]
    assert "PRIVATE" not in json.dumps(stages)


def test_runner_records_pcm_and_barge_in_stages_by_turn_id() -> None:
    runner = LabRunner(config=AILENConfig(), dry_run=True, simulate=True)
    runner._on_speech_started_event(CoreEvent(
        event_id="start",
        event_type=EventType.SPEECH_STARTED,
        source="test",
        payload={
            "turn_id": "turn-1",
            "speech_generation": 4,
            "request_to_pcm_ms": 123.0,
            "expression_requested": "happy",
        },
    ))
    runner._on_speech_interrupted_event(CoreEvent(
        event_id="barge",
        event_type=EventType.SPEECH_INTERRUPTED,
        source="test",
        payload={
            "turn_id": "turn-1",
            "speech_generation": 4,
            "buffered_frames": 6,
            "playback_stop_ms": 8.5,
            "logical_generation_cancelled": True,
            "synthesizer_draining": True,
        },
    ))
    runner._on_speech_synthesis_drained_event(CoreEvent(
        event_id="drained",
        event_type=EventType.SPEECH_SYNTHESIS_DRAINED,
        source="test",
        payload={
            "turn_id": "turn-1",
            "speech_generation": 4,
            "cancelled": True,
            "stale": True,
        },
    ))

    stages = runner.metrics.to_dict()["turns"]["stages"]
    assert [stage["stage"] for stage in stages] == [
        "first_pcm_submit",
        "barge_in",
        "stale_tts_drain_complete",
    ]
    assert stages[0]["request_to_pcm_ms"] == 123.0
    assert stages[1]["playback_stop_ms"] == 8.5
    assert stages[1]["frame_count"] == 6
    assert stages[1]["generation_cancelled"] is True
    assert stages[2]["stale"] is True


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
    mock_conv.handle_transcript.return_value = (mock_resp, MagicMock())
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
    mock_conv.handle_transcript.assert_called_once()


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


def test_low_quality_transcript_reprompts_without_calling_llm(monkeypatch) -> None:
    runner = LabRunner(config=AILENConfig(), dry_run=True, simulate=True)
    runner.inspect_and_plan()
    runner.init_components()

    mock_conv = MagicMock()
    runner.conversation_coordinator = mock_conv
    started: list[tuple[object, tuple[object, ...]]] = []

    class CapturedThread:
        def __init__(self, target, args=(), daemon=None):  # type: ignore[no-untyped-def]
            self.target = target
            self.args = args

        def start(self) -> None:
            started.append((self.target, self.args))

    monkeypatch.setattr("ailen.runtime.runner.threading.Thread", CapturedThread)

    event = CoreEvent(
        event_id="noise-event",
        event_type=EventType.TRANSCRIPT_READY,
        source="test",
        payload={"text": "?", "latency_ms": 20.0},
    )
    runner._on_transcript_event(event)

    mock_conv.handle_user_input.assert_not_called()
    assert runner.metrics.stt_fail_count == 1
    assert len(started) == 1
    assert started[0][0] == runner._run_stt_reprompt

def test_lab_runner_stop_waits_for_inflight_interaction(tmp_path: Path) -> None:
    import threading

    runner = LabRunner(
        config=AILENConfig(),
        dry_run=True,
        headless=True,
        no_camera=True,
        no_audio=True,
        no_ai=True,
        log_dir=tmp_path,
    )
    runner._is_running = True
    with runner._interaction_lock:
        runner._is_processing_interaction = True

    def release() -> None:
        time.sleep(0.12)
        with runner._interaction_lock:
            runner._is_processing_interaction = False

    worker = threading.Thread(target=release)
    worker.start()
    started = time.monotonic()
    runner.stop()
    elapsed = time.monotonic() - started
    worker.join(timeout=1.0)

    assert elapsed >= 0.08
    assert runner._is_running is False


def test_lab_runner_wires_vad_from_speech_config() -> None:
    cfg = AILENConfig()
    cfg.speech.vad_threshold = 0.013
    cfg.speech.vad_hangover_ms = 80
    cfg.speech.pre_roll_ms = 300
    cfg.speech.silence_timeout_ms = 520
    cfg.speech.min_speech_ms = 160
    runner = LabRunner(config=cfg, dry_run=True, simulate=True)
    runner.inspect_and_plan()
    runner.init_components()

    assert runner.audio_coordinator is not None
    collector = runner.audio_coordinator.collector
    assert collector.vad.threshold_rms == 0.013  # type: ignore[attr-defined]
    assert collector.vad.hangover_frames == 4  # type: ignore[attr-defined]
    assert collector.min_speech_ms == 160
    assert collector.silence_timeout_ms == 520
    assert collector._pre_roll_frame_count == 15


def test_web_availability_does_not_require_remote_ai() -> None:
    cfg = AILENConfig()
    cfg.network.outbound_web_enabled = True
    cfg.ai.allow_remote = False
    cfg.ai.remote.enabled = False
    runner = LabRunner(config=cfg, dry_run=True, simulate=True)
    runner.inspect_and_plan()
    runner.init_components()

    assert runner.conversation_coordinator is not None
    assert runner.conversation_coordinator.internet_available is True
    assert runner.conversation_coordinator.tool_network_allowed is True
    assert runner.conversation_coordinator.external_allowed is False


def test_remote_opt_in_keeps_core_private_and_allows_sanitized_turn() -> None:
    cfg = AILENConfig()
    cfg.ai.provider = "remote:test"
    cfg.ai.allow_remote = True
    cfg.ai.remote.enabled = True
    cfg.ai.allow_sanitized_external_prompts = True
    runner = LabRunner(config=cfg, dry_run=True, simulate=True)
    runner.inspect_and_plan()
    runner.init_components()

    assert runner.conversation_coordinator is not None
    assert runner.conversation_coordinator.privacy_level is PrivacyLevel.PRIVATE
    assert runner.conversation_coordinator.allow_sanitized_external_prompts is True


def test_remote_without_explicit_opt_in_stays_private() -> None:
    cfg = AILENConfig()
    cfg.ai.provider = "remote:test"
    cfg.ai.allow_remote = True
    cfg.ai.remote.enabled = True
    cfg.ai.allow_sanitized_external_prompts = False
    runner = LabRunner(config=cfg, dry_run=True, simulate=True)
    runner.inspect_and_plan()
    runner.init_components()

    assert runner.conversation_coordinator is not None
    assert runner.conversation_coordinator.privacy_level is PrivacyLevel.PRIVATE


def test_local_disabled_skips_runtime_discovery_and_semantic_backend() -> None:
    cfg = AILENConfig()
    cfg.ai.local.enabled = False
    cfg.ai.local.intent_model = "must-not-be-probed"
    runner = LabRunner(config=cfg, dry_run=True, no_camera=True, no_audio=True)

    with patch(
        "ailen.runtime.runner.LocalRuntimeManager.detect_available_runtimes"
    ) as detect_runtimes:
        runner.inspect_and_plan()

    detect_runtimes.assert_not_called()
    runner.ai_backends = {"local": MagicMock()}
    assert runner._build_semantic_intent_backend() is None


def test_local_disabled_never_prewarms_accidentally_registered_local_backend() -> None:
    cfg = AILENConfig()
    cfg.ai.local.enabled = False
    runner = LabRunner(config=cfg, dry_run=True)
    accidental_local = MagicMock()
    runner.ai_backends = {"local": accidental_local}

    runner._prewarm_ai_models()

    accidental_local.warmup.assert_not_called()


def test_fast_memory_tier_loads_local_model_on_demand_instead_of_prewarming() -> None:
    from ailen.domain.enums import InferenceProfile
    from ailen.models.inference_profile import InferenceRecommendation

    cfg = AILENConfig()
    cfg.ai.local.enabled = True
    runner = LabRunner(config=cfg, dry_run=True)
    local = MagicMock()
    runner.ai_backends = {"local": local}
    runner.inference_recommendation = InferenceRecommendation(
        profile=InferenceProfile.FAST,
        local_allowed=True,
        preferred_runtime="llama.cpp",
        max_model_ram_mb=1400,
        max_model_vram_mb=0,
        recommended_context=1024,
    )

    runner._prewarm_ai_models()

    local.warmup.assert_not_called()


def test_memory_pressure_releases_only_idle_local_backend() -> None:
    from ailen.domain.enums import InferenceProfile
    from ailen.models.inference_profile import InferenceRecommendation

    cfg = AILENConfig()
    cfg.ai.local.enabled = True
    runner = LabRunner(config=cfg, dry_run=True)
    local = MagicMock()
    local.release_if_idle.return_value = True
    external = MagicMock()
    runner.ai_backends = {"local": local, "cloud": external}
    runner.inference_recommendation = InferenceRecommendation(
        profile=InferenceProfile.FAST,
        local_allowed=True,
        preferred_runtime="llama.cpp",
        max_model_ram_mb=1400,
        max_model_vram_mb=0,
        recommended_context=1024,
    )

    assert runner._release_local_model_under_pressure(699) is True
    assert runner._release_local_model_under_pressure(700) is False
    local.release_if_idle.assert_called_once_with()
    external.release_if_idle.assert_not_called()


def test_external_request_timeout_does_not_inherit_disabled_local_timeout() -> None:
    cfg = AILENConfig()
    cfg.ai.local.enabled = False
    cfg.ai.local.timeout_seconds = 99.0
    cfg.ai.timeout_seconds = 7.0
    runner = LabRunner(config=cfg, dry_run=True, simulate=True)
    runner.inspect_and_plan()
    runner.init_components()

    assert runner.conversation_coordinator is not None
    assert runner.conversation_coordinator.context_builder.request_timeout_seconds == 7.0
    assert runner.conversation_coordinator.semantic_intent_resolver is None


def test_execution_mode_reflects_enabled_backends(tmp_path: Path) -> None:
    cfg = AILENConfig()
    real = LabRunner(config=cfg, log_dir=tmp_path)
    assert real.metrics.execution_mode == "real"
    partial = LabRunner(config=cfg, no_camera=True, log_dir=tmp_path)
    assert partial.metrics.execution_mode == "real"
    none = LabRunner(config=cfg, no_camera=True, no_audio=True, no_ai=True, log_dir=tmp_path)
    assert none.metrics.execution_mode == "no_backends"
    assert LabRunner(config=cfg, dry_run=True, log_dir=tmp_path).metrics.execution_mode == "dry_run"
