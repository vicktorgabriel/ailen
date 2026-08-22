"""Unit tests for AudioInteractionCoordinator and end-to-end audio pipeline."""

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


def test_audio_coordinator_half_duplex_blocks_mic_while_speaking() -> None:
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
