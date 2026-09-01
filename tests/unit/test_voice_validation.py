"""Tests for the RAM-only guided physical voice validation harness."""

import threading

from ailen.audio import voice_validation
from ailen.audio.fake import FakeAudioInputBackend, FakeSttBackend
from ailen.audio.level import AudioProcessorChain, CaptureLevelProcessor
from ailen.audio.pcm import generate_silence_pcm, generate_tone_pcm
from ailen.audio.stt_quality import SttQualityEvaluator
from ailen.audio.vad import EnergyVad, UtteranceCollector
from ailen.audio.voice_validation import (
    BargeInTrialResult,
    VoiceSampleResult,
    VoiceValidationCase,
    capture_voice_sample,
    character_error_rate,
    default_voice_validation_cases,
    recommend_voice_configuration,
    run_physical_barge_in_trial,
    summarize_barge_in_trial,
)
from ailen.core.events import EventBus
from ailen.domain.enums import EventType


def test_character_error_rate_normalizes_spanish_text() -> None:
    assert character_error_rate("Hola, cómo va", "hola cómo va") == 0.0
    assert character_error_rate("sí", "no") == 1.0


def test_capture_sample_keeps_only_text_and_metrics_not_pcm() -> None:
    backend = FakeAudioInputBackend()
    voice = generate_tone_pcm(440.0, 20.0, amplitude=0.2)
    silence = generate_silence_pcm(20.0)
    backend.push_frames([voice] * 4 + [silence] * 3)
    collector = UtteranceCollector(
        vad=EnergyVad(threshold_rms=0.02, hangover_frames=0),
        frame_ms=20.0,
        min_speech_ms=40.0,
        silence_timeout_ms=40.0,
        pre_roll_ms=20.0,
    )

    result = capture_voice_sample(
        case=VoiceValidationCase("short", "hola mundo", "voz normal"),
        device="fake",
        vad_mode=2,
        silence_timeout_ms=40,
        audio_input=backend,
        collector=collector,
        stt=FakeSttBackend(canned_text="hola mundo"),
        quality=SttQualityEvaluator(),
        max_wait_seconds=0.5,
    )

    raw = result.to_dict()
    assert result.status == "ok"
    assert result.recognized_text == "hola mundo"
    assert result.wer == 0.0
    assert result.cer == 0.0
    assert result.frame_count > 0
    assert "pcm" not in raw
    assert "audio_data" not in raw


def test_capture_sample_uses_observed_default_source_hint() -> None:
    backend = FakeAudioInputBackend()
    backend.effective_device = "default"
    voice = generate_tone_pcm(440.0, 20.0, amplitude=0.2)
    silence = generate_silence_pcm(20.0)
    backend.push_frames([voice] * 4 + [silence] * 3)
    collector = UtteranceCollector(
        vad=EnergyVad(threshold_rms=0.02, hangover_frames=0),
        frame_ms=20.0,
        min_speech_ms=40.0,
        silence_timeout_ms=40.0,
        pre_roll_ms=20.0,
    )

    result = capture_voice_sample(
        case=VoiceValidationCase("source", "hola mundo", "voz normal"),
        device="default",
        effective_source_hint="pipewire:easyeffects_source",
        vad_mode=2,
        silence_timeout_ms=40,
        audio_input=backend,
        collector=collector,
        stt=FakeSttBackend(canned_text="hola mundo"),
        quality=SttQualityEvaluator(),
        max_wait_seconds=0.5,
    )

    assert result.effective_source == "pipewire:easyeffects_source"


def test_capture_sample_times_out_honestly_without_voice() -> None:
    backend = FakeAudioInputBackend()
    collector = UtteranceCollector(
        vad=EnergyVad(threshold_rms=0.02, hangover_frames=0),
        min_speech_ms=40.0,
        silence_timeout_ms=40.0,
    )

    result = capture_voice_sample(
        case=VoiceValidationCase("none", "hola", "sin audio"),
        device="fake",
        vad_mode=3,
        silence_timeout_ms=40,
        audio_input=backend,
        collector=collector,
        stt=FakeSttBackend(canned_text="hola"),
        quality=SttQualityEvaluator(),
        max_wait_seconds=0.01,
    )

    assert result.status == "timeout"
    assert result.recognized_text == ""
    assert result.confidence is None


def test_timeout_keeps_all_silence_stage_metrics_without_pcm() -> None:
    backend = FakeAudioInputBackend()
    silence = generate_silence_pcm(20.0)
    backend.push_frames([silence] * 3)
    collector = UtteranceCollector(
        vad=EnergyVad(threshold_rms=0.02, hangover_frames=0),
        min_speech_ms=40.0,
        silence_timeout_ms=40.0,
    )

    result = capture_voice_sample(
        case=VoiceValidationCase("timeout-stages", "hola", "silencio"),
        device="fake",
        vad_mode=2,
        silence_timeout_ms=40,
        audio_input=backend,
        collector=collector,
        stt=FakeSttBackend(canned_text="hola"),
        quality=SttQualityEvaluator(),
        frame_processor=AudioProcessorChain(
            [CaptureLevelProcessor(capture_gain_db=6.0)]
        ),
        silence_seconds=0.04,
        max_wait_seconds=0.01,
    )

    assert result.status == "timeout"
    assert result.raw_noise_rms is not None
    assert result.gained_noise_rms is not None
    assert result.processed_noise_rms is not None
    assert result.raw_noise_peak is not None
    assert result.gained_noise_peak is not None
    assert result.processed_noise_peak is not None
    assert "pcm" not in result.to_dict()


def test_capture_sample_measures_silence_voice_gain_snr_and_false_triggers() -> None:
    backend = FakeAudioInputBackend()
    silence = generate_silence_pcm(20.0)
    voice = generate_tone_pcm(440.0, 20.0, amplitude=0.08)
    backend.push_frames([silence] * 2 + [voice] * 4 + [silence] * 3)
    collector = UtteranceCollector(
        vad=EnergyVad(threshold_rms=0.02, hangover_frames=0),
        frame_ms=20.0,
        min_speech_ms=40.0,
        silence_timeout_ms=40.0,
        pre_roll_ms=20.0,
    )
    ready: list[bool] = []

    result = capture_voice_sample(
        case=VoiceValidationCase("distance", "hola mundo", "75 cm"),
        device="pipewire:test",
        vad_mode=2,
        silence_timeout_ms=40,
        audio_input=backend,
        collector=collector,
        stt=FakeSttBackend(canned_text="hola mundo"),
        quality=SttQualityEvaluator(),
        frame_processor=AudioProcessorChain(
            [CaptureLevelProcessor(capture_gain_db=6.0)]
        ),
        silence_seconds=0.04,
        distance_cm=75,
        on_speech_ready=lambda: ready.append(True),
        max_wait_seconds=0.5,
    )

    assert result.status == "ok"
    assert ready == [True]
    assert result.effective_source == "pipewire:test"
    assert result.distance_cm == 75
    assert result.gained_voice_rms is not None
    assert result.raw_voice_rms is not None
    assert result.gained_voice_rms > result.raw_voice_rms
    assert result.raw_noise_peak is not None
    assert result.gained_noise_peak is not None
    assert result.processed_noise_peak is not None
    assert result.raw_voice_peak is not None
    assert result.gained_voice_peak is not None
    assert result.processed_voice_peak is not None
    assert result.snr_raw_db is not None
    assert result.snr_gained_db is not None
    assert result.snr_processed_db is not None
    assert result.silence_false_trigger_frames == 0
    assert result.recommended_auto_gain_gate_rms is not None
    assert result.raw_noise_rms is not None
    assert result.recommended_auto_gain_gate_rms > result.raw_noise_rms
    assert "pcm" not in result.to_dict()


def test_default_matrix_has_rioplatense_pauses_and_side_effect_command() -> None:
    cases = default_voice_validation_cases()
    assert 10 <= len(cases) <= 15
    assert any("pausa" in case.instruction.lower() for case in cases)
    assert any("volumen" in case.expected_text.lower() for case in cases)
    assert any(case.expected_text.lower() in {"sí", "no"} for case in cases)


def test_recommendation_penalizes_truncation_and_empty_transcripts() -> None:
    def result(mode: int, silence: int, *, wer: float, truncated: bool = False) -> VoiceSampleResult:
        return VoiceSampleResult(
            case_id=f"{mode}-{silence}",
            expected_text="hola",
            recognized_text="hola" if wer == 0 else "",
            device="default",
            vad_mode=mode,
            silence_timeout_ms=silence,
            status="ok" if wer == 0 else "empty_transcript",
            wer=wer,
            cer=wer,
            truncated=truncated,
        )

    recommendation = recommend_voice_configuration([
        result(3, 380, wer=0.0, truncated=True),
        result(2, 500, wer=0.0),
        result(2, 500, wer=0.0),
        result(3, 600, wer=1.0),
    ])

    assert recommendation is not None
    assert recommendation["vad_mode"] == 2
    assert recommendation["silence_timeout_ms"] == 500
    assert recommendation["requires_human_confirmation"] is True


def test_recommendation_carries_silence_derived_agc_gate_without_persisting() -> None:
    samples = [
        VoiceSampleResult(
            case_id=f"gate-{index}",
            expected_text="hola",
            recognized_text="hola",
            device="pipewire:test",
            vad_mode=2,
            silence_timeout_ms=500,
            status="ok",
            wer=0.0,
            cer=0.0,
            recommended_auto_gain_gate_rms=gate,
        )
        for index, gate in enumerate((0.006, 0.008), start=1)
    ]

    recommendation = recommend_voice_configuration(samples)

    assert recommendation is not None
    assert recommendation["auto_gain_noise_gate_rms"] == 0.007
    assert recommendation["requires_human_confirmation"] is True


def test_recommendation_keeps_processing_profiles_separate() -> None:
    raw = VoiceSampleResult(
        case_id="raw",
        expected_text="hola",
        recognized_text="",
        device="pipewire:test",
        vad_mode=2,
        silence_timeout_ms=500,
        status="empty_transcript",
        processing_profile="raw",
        wer=1.0,
        cer=1.0,
    )
    full = VoiceSampleResult(
        case_id="full",
        expected_text="hola",
        recognized_text="hola",
        device="pipewire:test",
        vad_mode=2,
        silence_timeout_ms=500,
        status="ok",
        processing_profile="full",
        wer=0.0,
        cer=0.0,
    )

    recommendation = recommend_voice_configuration([raw, full])

    assert recommendation is not None
    assert recommendation["processing_profile"] == "full"


def test_voice_sample_console_summary_exposes_every_capture_stage() -> None:
    result = VoiceSampleResult(
        case_id="stages",
        expected_text="hola",
        recognized_text="hola",
        device="pipewire:test",
        effective_source="pipewire:effective",
        vad_mode=2,
        silence_timeout_ms=500,
        status="ok",
        raw_noise_rms=0.003,
        gained_noise_rms=0.004,
        processed_noise_rms=0.002,
        raw_voice_rms=0.04,
        gained_voice_rms=0.08,
        processed_voice_rms=0.07,
        raw_noise_peak=0.006,
        gained_noise_peak=0.009,
        processed_noise_peak=0.005,
        raw_voice_peak=0.12,
        gained_voice_peak=0.24,
        processed_voice_peak=0.20,
        snr_raw_db=22.5,
        snr_gained_db=26.0,
        snr_processed_db=30.9,
        clipping_ratio=0.0001,
        applied_gain_db=6.0,
        silence_false_trigger_frames=2,
    )

    summary = voice_validation.format_voice_sample_result(result)

    for token in (
        "source=pipewire:effective",
        "noise_rms(raw/gained/processed)=0.003/0.004/0.002",
        "voice_rms(raw/gained/processed)=0.04/0.08/0.07",
        "noise_peak(raw/gained/processed)=0.006/0.009/0.005",
        "voice_peak(raw/gained/processed)=0.12/0.24/0.2",
        "snr_db(raw/gained/processed)=22.5/26.0/30.9",
        "applied_gain_db=6.0",
        "false_vad=2",
    ):
        assert token in summary


def test_barge_in_summary_requires_both_preserved_frames_and_interrupted_transcript() -> None:
    result = summarize_barge_in_trial(
        phase="middle",
        expected_text="ahora te interrumpo",
        interruption={
            "buffered_frames": 7,
            "playback_stop_ms": 8.0,
            "logical_generation_cancelled": True,
            "synthesizer_draining": True,
        },
        transcript={
            "text": "ahora te interrumpo",
            "confidence": 0.83,
            "interrupted": True,
            "engine": "vosk",
        },
        synthesis_drained={"cancelled": True, "stale": False},
        speech_finished={"interrupted": True},
        speech_thread_alive=False,
    )

    assert isinstance(result, BargeInTrialResult)
    assert result.status == "passed"
    assert result.frames_preserved is True
    assert result.transcript_interrupted is True
    assert result.wer == 0.0
    assert result.no_aec is True


def test_barge_in_trial_observes_real_event_sequence_without_persisting_pcm() -> None:
    bus = EventBus()
    release_speech = threading.Event()

    class SyntheticCoordinator:
        event_bus = bus

        def speak(self, _text: str, *, turn_id: str):
            bus.create_and_publish(
                EventType.SPEECH_STARTED,
                payload={"turn_id": turn_id, "speech_generation": 3},
            )
            release_speech.wait(timeout=1.0)
            bus.create_and_publish(
                EventType.SPEECH_FINISHED,
                payload={"turn_id": turn_id, "interrupted": True},
            )

        @staticmethod
        def cancel_active_speech(*, reason: str) -> bool:
            del reason
            release_speech.set()
            return True

    def trigger_events(_phase: str, _expected: str) -> None:
        bus.create_and_publish(
            EventType.SPEECH_INTERRUPTED,
            payload={
                "turn_id": "barge-middle-test",
                "buffered_frames": 5,
                "playback_stop_ms": 6.0,
                "logical_generation_cancelled": True,
                "synthesizer_draining": False,
            },
        )
        bus.create_and_publish(
            EventType.TRANSCRIPT_READY,
            payload={
                "text": "cambiemos de tema",
                "confidence": 0.9,
                "engine": "vosk",
                "interrupted": True,
            },
        )
        bus.create_and_publish(
            EventType.SPEECH_SYNTHESIS_DRAINED,
            payload={
                "turn_id": "barge-middle-test",
                "cancelled": True,
                "stale": False,
            },
        )
        release_speech.set()

    result = run_physical_barge_in_trial(
        coordinator=SyntheticCoordinator(),  # type: ignore[arg-type]
        phase="middle",
        expected_text="cambiemos de tema",
        cue_delay_seconds=0.0,
        timeout_seconds=1.0,
        turn_id="barge-middle-test",
        on_cue=trigger_events,
    )

    assert result.status == "passed"
    assert result.recognized_text == "cambiemos de tema"
    assert "pcm" not in result.to_dict()
    assert "audio_data" not in result.to_dict()
