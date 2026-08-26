"""Unit tests for AudioInteractionCoordinator and end-to-end audio pipeline."""

import threading
import time

from ailen.audio.contracts import AudioSegment, SpeechOutput, SpeechRequest, Transcript
from ailen.audio.coordinator import AudioInteractionCoordinator
from ailen.audio.fake import (
    FakeAudioInputBackend,
    FakeAudioOutputBackend,
    FakeSttBackend,
    FakeTtsBackend,
)
from ailen.audio.pcm import generate_silence_pcm, generate_tone_pcm
from ailen.audio.turn_gate import AudioTurnGate
from ailen.audio.vad import EnergyVad, UtteranceCollector
from ailen.core.events import EventBus
from ailen.core.state import StateManager
from ailen.domain.enums import AssistantState, EventType
from ailen.face.null import NullFaceController


class ControlledClock:
    """Deterministic clock for audio coordinator tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.time = start

    def __call__(self) -> float:
        return self.time

    def advance(self, dt: float) -> None:
        self.time += dt


def test_audio_coordinator_speech_capture_and_stt_transcription() -> None:
    clock = ControlledClock(1000.0)
    input_backend = FakeAudioInputBackend()
    stt_backend = FakeSttBackend(canned_text="comando de voz detectado")
    state_mgr = StateManager(initial_state=AssistantState.IDLE)
    face_ctrl = NullFaceController()
    event_bus = EventBus()
    vad = EnergyVad(threshold_rms=0.02, hangover_frames=0)
    collector = UtteranceCollector(
        vad=vad,
        frame_ms=20.0,
        min_speech_ms=40.0,
        silence_timeout_ms=60.0,
    )
    turn_gate = AudioTurnGate(settling_cooldown_seconds=0.1, clock=clock)

    coordinator = AudioInteractionCoordinator(
        audio_input=input_backend,
        stt=stt_backend,
        utterance_collector=collector,
        turn_gate=turn_gate,
        state_manager=state_mgr,
        face_controller=face_ctrl,
        event_bus=event_bus,
        clock=clock,
    )

    silence = generate_silence_pcm(20.0)
    voice = generate_tone_pcm(440.0, 20.0, amplitude=0.1)

    # 1. Feed silence -> stays IDLE
    coordinator.process_frame(silence)
    assert state_mgr.current_state == AssistantState.IDLE

    # 2. Feed voice frames (triggers LISTENING state)
    coordinator.process_frame(voice)
    coordinator.process_frame(voice)
    assert state_mgr.current_state == AssistantState.LISTENING
    assert face_ctrl.state == AssistantState.LISTENING

    # 3. Feed more voice
    coordinator.process_frame(voice)

    # 4. Feed silence frames to satisfy silence_timeout (3 frames = 60ms)
    coordinator.process_frame(silence)
    coordinator.process_frame(silence)
    seg, transcript = coordinator.process_frame(silence)

    # Utterance finalized and transcribed!
    assert seg is not None
    assert transcript is not None
    assert transcript.text == "comando de voz detectado"
    assert state_mgr.current_state == AssistantState.IDLE

    # Verify lightweight events emitted
    history = event_bus.history
    event_types = [e.event_type for e in history]
    assert EventType.VOICE_STARTED in event_types
    assert EventType.VOICE_ENDED in event_types
    assert EventType.SPEECH_CAPTURED in event_types
    assert EventType.TRANSCRIPT_READY in event_types


def test_audio_coordinator_speak_tts_and_mouth_sync() -> None:
    clock = ControlledClock(1000.0)
    output_backend = FakeAudioOutputBackend()
    tts_backend = FakeTtsBackend()
    state_mgr = StateManager(initial_state=AssistantState.IDLE)
    face_ctrl = NullFaceController()
    event_bus = EventBus()
    turn_gate = AudioTurnGate(settling_cooldown_seconds=0.2, clock=clock)

    coordinator = AudioInteractionCoordinator(
        audio_output=output_backend,
        tts=tts_backend,
        turn_gate=turn_gate,
        state_manager=state_mgr,
        face_controller=face_ctrl,
        event_bus=event_bus,
        clock=clock,
    )

    # Speak text
    output = coordinator.speak(text="Hola mundo", voice_id="es_ES-standard", rate=1.0)

    assert output.audio_data is not None
    assert len(output_backend.played_chunks) == 1
    assert state_mgr.current_state == AssistantState.IDLE
    assert face_ctrl.speech_level == 0.0

    # Verify event publication
    history = event_bus.history
    event_types = [e.event_type for e in history]
    assert EventType.SPEECH_STARTED in event_types
    assert EventType.SPEECH_FINISHED in event_types


def test_audio_coordinator_recovers_if_tts_backend_raises() -> None:
    class ExplodingTts:
        def health(self):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def synthesize(self, request: SpeechRequest) -> SpeechOutput:
            raise RuntimeError("tts boom")

    clock = ControlledClock(1000.0)
    gate = AudioTurnGate(settling_cooldown_seconds=0.0, clock=clock)
    state_mgr = StateManager(initial_state=AssistantState.IDLE)
    face_ctrl = NullFaceController()
    event_bus = EventBus()
    coordinator = AudioInteractionCoordinator(
        tts=ExplodingTts(),
        turn_gate=gate,
        state_manager=state_mgr,
        face_controller=face_ctrl,
        event_bus=event_bus,
        clock=clock,
    )

    output = coordinator.speak("hola")

    assert output.audio_data is None
    assert gate.is_listening_allowed() is True
    assert state_mgr.current_state == AssistantState.IDLE
    assert face_ctrl.speech_level == 0.0
    assert EventType.AUDIO_ERROR in [e.event_type for e in event_bus.history]


def test_audio_coordinator_recovers_if_stt_backend_raises() -> None:
    class ExplodingStt:
        def health(self):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def transcribe(self, segment: AudioSegment) -> Transcript:
            raise RuntimeError("stt boom")

    state_mgr = StateManager(initial_state=AssistantState.LISTENING)
    face_ctrl = NullFaceController()
    event_bus = EventBus()
    coordinator = AudioInteractionCoordinator(
        stt=ExplodingStt(),
        state_manager=state_mgr,
        face_controller=face_ctrl,
        event_bus=event_bus,
    )

    transcript = coordinator._handle_utterance_completed(
        AudioSegment(data=b"\x00\x00" * 160, duration_ms=20.0)
    )

    assert transcript.text == ""
    assert transcript.confidence is None
    assert state_mgr.current_state == AssistantState.IDLE
    assert EventType.AUDIO_ERROR in [e.event_type for e in event_bus.history]
    for event in event_bus.history:
        assert not any(isinstance(value, bytes) for value in event.payload.values())


def test_normal_stt_path_blocks_speaker_audio_while_speaking() -> None:
    clock = ControlledClock(1000.0)
    input_backend = FakeAudioInputBackend()
    turn_gate = AudioTurnGate(settling_cooldown_seconds=0.5, clock=clock)
    vad = EnergyVad(threshold_rms=0.02)
    collector = UtteranceCollector(vad=vad)

    coordinator = AudioInteractionCoordinator(
        audio_input=input_backend,
        utterance_collector=collector,
        turn_gate=turn_gate,
        clock=clock,
    )

    voice_frame = generate_tone_pcm(440.0, 20.0, amplitude=0.2)

    # While speaking is locked in turn gate:
    turn_gate.start_speaking()

    # Pass loud voice frames to coordinator
    for _ in range(5):
        seg, tr = coordinator.process_frame(voice_frame)
        assert seg is None
        assert tr is None

    # Utterance was never entered because frames were dropped by turn gate
    assert collector.is_in_utterance is False


def test_audio_coordinator_plays_streaming_tts_chunks_incrementally() -> None:
    class ChunkedTts:
        def health(self):  # type: ignore[no-untyped-def]
            return None

        def synthesize(self, request: SpeechRequest) -> SpeechOutput:
            raise AssertionError("blocking synthesize must not be used")

        def synthesize_chunks(self, request: SpeechRequest):  # type: ignore[no-untyped-def]
            yield SpeechOutput(audio_data=b"\x01\x00" * 100, sample_rate=22050, channels=1, duration_ms=4.5, latency_ms=20.0)
            yield SpeechOutput(audio_data=b"\x02\x00" * 100, sample_rate=22050, channels=1, duration_ms=4.5, latency_ms=35.0)

    output_backend = FakeAudioOutputBackend()
    event_bus = EventBus()
    coordinator = AudioInteractionCoordinator(
        audio_output=output_backend,
        tts=ChunkedTts(),
        event_bus=event_bus,
        state_manager=StateManager(initial_state=AssistantState.PROCESSING),
        face_controller=NullFaceController(),
    )

    out = coordinator.speak("Primera frase. Segunda frase.")
    assert len(output_backend.played_chunks) == 2
    assert out.audio_data == output_backend.played_chunks[0] + output_backend.played_chunks[1]
    assert out.latency_ms == 20.0
    assert [e.event_type for e in event_bus.history].count(EventType.SPEECH_STARTED) == 1


def test_audio_coordinator_prefetches_only_next_tts_chunk_during_playback() -> None:
    playback_started = threading.Event()
    second_ready = threading.Event()
    third_requested = threading.Event()

    class ChunkedTts:
        def health(self):  # type: ignore[no-untyped-def]
            return None

        def synthesize(self, request: SpeechRequest) -> SpeechOutput:
            raise AssertionError("blocking synthesize must not be used")

        def synthesize_chunks(self, request: SpeechRequest):  # type: ignore[no-untyped-def]
            del request
            yield SpeechOutput(audio_data=b"first", duration_ms=100.0)
            assert playback_started.wait(timeout=1.0)
            second_ready.set()
            yield SpeechOutput(audio_data=b"second", duration_ms=100.0)
            third_requested.set()
            yield SpeechOutput(audio_data=b"third", duration_ms=100.0)

    class ObservedOutput(FakeAudioOutputBackend):
        def play(  # type: ignore[override]
            self,
            audio_data: bytes,
            sample_rate: int = 16000,
            channels: int = 1,
            cancel_event: threading.Event | None = None,
        ) -> None:
            if audio_data == b"first":
                playback_started.set()
                assert second_ready.wait(timeout=1.0)
                assert third_requested.is_set() is False
            super().play(audio_data, sample_rate, channels, cancel_event)

    output = ObservedOutput()
    coordinator = AudioInteractionCoordinator(audio_output=output, tts=ChunkedTts())

    coordinator.speak("Tres frases.")

    assert output.played_chunks == [b"first", b"second", b"third"]


def test_streaming_tts_cancel_does_not_wait_for_inflight_prefetch() -> None:
    second_synthesis_started = threading.Event()
    release_second = threading.Event()
    coordinator_ref: list[AudioInteractionCoordinator] = []

    class SlowSecondChunkTts:
        def health(self):  # type: ignore[no-untyped-def]
            return None

        def synthesize(self, request: SpeechRequest) -> SpeechOutput:
            raise AssertionError("blocking synthesize must not be used")

        def synthesize_chunks(self, request: SpeechRequest):  # type: ignore[no-untyped-def]
            del request
            yield SpeechOutput(audio_data=b"first", duration_ms=100.0)
            second_synthesis_started.set()
            assert release_second.wait(timeout=1.0)
            yield SpeechOutput(audio_data=b"second", duration_ms=100.0)

    class CancellingOutput(FakeAudioOutputBackend):
        def play(  # type: ignore[override]
            self,
            audio_data: bytes,
            sample_rate: int = 16000,
            channels: int = 1,
            cancel_event: threading.Event | None = None,
        ) -> None:
            assert second_synthesis_started.wait(timeout=1.0)
            coordinator_ref[0]._speech_cancel.set()
            super().play(audio_data, sample_rate, channels, cancel_event)

    output = CancellingOutput()
    coordinator = AudioInteractionCoordinator(
        audio_output=output,
        tts=SlowSecondChunkTts(),
    )
    coordinator_ref.append(coordinator)

    started = time.monotonic()
    coordinator.speak("Dos frases.")
    elapsed = time.monotonic() - started
    release_second.set()

    assert elapsed < 0.2
    assert output.played_chunks == []

def test_barge_in_stops_playback_after_sustained_user_voice() -> None:
    output = FakeAudioOutputBackend()
    event_bus = EventBus()
    gate = AudioTurnGate(settling_cooldown_seconds=0.0)
    coordinator = AudioInteractionCoordinator(
        audio_output=output,
        stt=FakeSttBackend(canned_text="interrupción"),
        utterance_collector=UtteranceCollector(
            vad=EnergyVad(threshold_rms=0.02, hangover_frames=0),
            frame_ms=20.0,
            min_speech_ms=120.0,
            silence_timeout_ms=60.0,
        ),
        turn_gate=gate,
        event_bus=event_bus,
        interruption_enabled=True,
        interruption_threshold_rms=0.05,
        interruption_min_ms=60,
        frame_ms=20.0,
    )
    gate.start_speaking()
    voice = generate_tone_pcm(440.0, 20.0, amplitude=0.2)
    for _ in range(3):
        coordinator.process_frame(voice)

    assert coordinator._speech_cancel.is_set()
    assert output.stopped is True
    assert EventType.SPEECH_INTERRUPTED in [event.event_type for event in event_bus.history]


def test_short_noise_does_not_trigger_barge_in() -> None:
    output = FakeAudioOutputBackend()
    gate = AudioTurnGate(settling_cooldown_seconds=0.0)
    coordinator = AudioInteractionCoordinator(
        audio_output=output,
        turn_gate=gate,
        interruption_enabled=True,
        interruption_threshold_rms=0.05,
        interruption_min_ms=100,
        frame_ms=20.0,
    )
    gate.start_speaking()
    loud = generate_tone_pcm(440.0, 20.0, amplitude=0.2)
    quiet = generate_silence_pcm(20.0)
    coordinator.process_frame(loud)
    coordinator.process_frame(loud)
    coordinator.process_frame(quiet)
    assert coordinator._speech_cancel.is_set() is False
    assert output.stopped is False


def test_barge_in_calibrates_speaker_leak_before_interrupting() -> None:
    output = FakeAudioOutputBackend()
    gate = AudioTurnGate(settling_cooldown_seconds=0.0)
    coordinator = AudioInteractionCoordinator(
        audio_output=output,
        turn_gate=gate,
        interruption_enabled=True,
        interruption_threshold_rms=0.01,
        interruption_min_ms=40,
        interruption_calibration_ms=40,
        interruption_leak_multiplier=1.5,
        frame_ms=20.0,
    )
    gate.start_speaking()
    coordinator._playback_started = True
    speaker_leak = generate_tone_pcm(440.0, 20.0, amplitude=0.02)
    user_voice = generate_tone_pcm(300.0, 20.0, amplitude=0.20)

    coordinator.process_frame(speaker_leak)
    coordinator.process_frame(speaker_leak)
    assert coordinator._speech_cancel.is_set() is False

    coordinator.process_frame(user_voice)
    coordinator.process_frame(user_voice)
    assert coordinator._speech_cancel.is_set() is True
    assert output.stopped is True


def test_user_voice_during_calibration_window_can_interrupt() -> None:
    output = FakeAudioOutputBackend()
    gate = AudioTurnGate(settling_cooldown_seconds=0.0)
    coordinator = AudioInteractionCoordinator(
        audio_output=output,
        turn_gate=gate,
        interruption_enabled=True,
        interruption_threshold_rms=0.018,
        interruption_min_ms=40,
        interruption_calibration_ms=160,
        interruption_leak_multiplier=1.25,
        frame_ms=20.0,
    )
    gate.start_speaking()
    coordinator._playback_started = True
    user_voice = generate_tone_pcm(300.0, 20.0, amplitude=0.20)

    coordinator.process_frame(user_voice)
    coordinator.process_frame(user_voice)

    assert coordinator._speech_cancel.is_set() is True
    assert output.stopped is True
    assert coordinator._speaker_leak_peak_rms == 0.0


def test_interrupted_turn_keeps_buffering_until_processing_releases() -> None:
    gate = AudioTurnGate(settling_cooldown_seconds=0.0)
    coordinator = AudioInteractionCoordinator(
        turn_gate=gate,
        interruption_enabled=True,
        interruption_threshold_rms=0.01,
        interruption_min_ms=20,
        interruption_calibration_ms=0,
        frame_ms=20.0,
    )
    voice = generate_tone_pcm(300.0, 20.0, amplitude=0.20)
    gate.start_processing()
    gate.start_speaking()
    coordinator.process_frame(voice)
    assert coordinator._interruption_triggered is True

    gate.stop_speaking()
    before = len(coordinator._pending_interruption_frames)
    coordinator.process_frame(voice)
    assert len(coordinator._pending_interruption_frames) == before + 1


def test_interrupted_turn_buffers_through_gate_cooldown_and_reaches_stt() -> None:
    now = 0.0
    gate = AudioTurnGate(settling_cooldown_seconds=0.15, clock=lambda: now)
    coordinator = AudioInteractionCoordinator(
        stt=FakeSttBackend(canned_text="seguí escuchando"),
        utterance_collector=UtteranceCollector(
            vad=EnergyVad(threshold_rms=0.02, hangover_frames=0),
            frame_ms=20.0,
            min_speech_ms=40.0,
            silence_timeout_ms=60.0,
            pre_roll_ms=40.0,
        ),
        turn_gate=gate,
        interruption_enabled=True,
        interruption_threshold_rms=0.01,
        interruption_min_ms=20,
        interruption_calibration_ms=0,
        frame_ms=20.0,
    )
    voice = generate_tone_pcm(300.0, 20.0, amplitude=0.20)
    silence = generate_silence_pcm(20.0)
    gate.start_processing()
    gate.start_speaking()
    coordinator.process_frame(voice)
    gate.stop_speaking()
    gate.stop_processing()

    # These frames arrive after playback stopped but before the cooldown ends.
    for _ in range(4):
        coordinator.process_frame(voice)
    assert len(coordinator._pending_interruption_frames) >= 4

    now = 0.2
    transcript = None
    segment = None
    for frame in (silence, silence, silence):
        segment, transcript = coordinator.process_frame(frame)
        if transcript is not None:
            break

    assert segment is not None
    assert transcript is not None
    assert transcript.text == "seguí escuchando"


def test_pending_interruption_drain_keeps_frames_after_first_segment() -> None:
    gate = AudioTurnGate(settling_cooldown_seconds=0.0)
    coordinator = AudioInteractionCoordinator(
        stt=FakeSttBackend(canned_text="interrupción"),
        utterance_collector=UtteranceCollector(
            vad=EnergyVad(threshold_rms=0.02, hangover_frames=0),
            frame_ms=20.0,
            min_speech_ms=40.0,
            silence_timeout_ms=40.0,
            pre_roll_ms=40.0,
        ),
        turn_gate=gate,
        interruption_enabled=True,
        frame_ms=20.0,
    )
    voice = generate_tone_pcm(300.0, 20.0, amplitude=0.20)
    silence = generate_silence_pcm(20.0)
    coordinator._interruption_triggered = True
    coordinator._pending_interruption_frames.extend(
        [voice, voice, silence, silence, voice, voice, silence, silence]
    )

    first_segment, _ = coordinator.process_frame(silence)

    assert first_segment is not None
    assert coordinator._pending_interruption_frames
    second_segment, _ = coordinator.process_frame(silence)
    assert second_segment is not None
