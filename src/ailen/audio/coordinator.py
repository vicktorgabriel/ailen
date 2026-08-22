"""Audio Interaction Coordinator for AILEN.

Coordinates microphone capture, VAD utterance collection, STT transcription,
TTS synthesis, audio output playback, half-duplex turn gating, and face mouth sync.
"""

import logging
import threading
import time
from collections.abc import Callable

from ailen.audio.contracts import (
    AudioInputBackend,
    AudioOutputBackend,
    AudioSegment,
    SpeechOutput,
    SpeechRequest,
    SttBackend,
    Transcript,
    TtsBackend,
)
from ailen.audio.fake import (
    FakeAudioInputBackend,
    FakeAudioOutputBackend,
    FakeSttBackend,
    FakeTtsBackend,
)
from ailen.audio.pcm import compute_pcm_rms
from ailen.audio.turn_gate import AudioTurnGate
from ailen.audio.vad import EnergyVad, UtteranceCollector
from ailen.core.events import EventBus
from ailen.core.state import StateManager
from ailen.domain.enums import AssistantState, EventType
from ailen.face.contracts import FaceController

logger = logging.getLogger(__name__)


class AudioInteractionCoordinator:
    """Orchestrates audio input/output, VAD, STT, TTS, state transitions, and face levels."""

    def __init__(
        self,
        audio_input: AudioInputBackend | None = None,
        audio_output: AudioOutputBackend | None = None,
        stt: SttBackend | None = None,
        tts: TtsBackend | None = None,
        utterance_collector: UtteranceCollector | None = None,
        turn_gate: AudioTurnGate | None = None,
        state_manager: StateManager | None = None,
        face_controller: FaceController | None = None,
        event_bus: EventBus | None = None,
        clock: Callable[[], float] | None = None,
        auto_reset_after_stt: bool = True,
    ) -> None:
        self.audio_input = audio_input or FakeAudioInputBackend()
        self.audio_output = audio_output or FakeAudioOutputBackend()
        self.stt = stt or FakeSttBackend()
        self.tts = tts or FakeTtsBackend()
        self.collector = utterance_collector or UtteranceCollector(vad=EnergyVad())
        self.turn_gate = turn_gate or AudioTurnGate()
        self.state_manager = state_manager
        self.face_controller = face_controller
        self.event_bus = event_bus
        self._clock = clock or time.monotonic
        self.auto_reset_after_stt = auto_reset_after_stt

        self._running = False
        self._loop_thread: threading.Thread | None = None
        self._last_transcript: Transcript | None = None
        self._lock = threading.Lock()

    @property
    def last_transcript(self) -> Transcript | None:
        """Return the most recent STT transcript."""
        with self._lock:
            return self._last_transcript

    # -------------------------------------------------------------------------
    # Lifecycle Management
    # -------------------------------------------------------------------------

    def start(self) -> None:
        """Start audio input and background capture/processing loop."""
        if self._running:
            return

        try:
            self.audio_input.start()
        except Exception as exc:
            logger.exception("Audio input failed to start")
            self._publish_audio_error("input_start", exc)
            return

        self._running = True
        self._loop_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._loop_thread.start()

    def stop(self) -> None:
        """Stop background capture loop and audio devices."""
        self._running = False
        # Stop input first so a backend blocked in read_frame can release its pipe/device.
        try:
            self.audio_input.stop()
        except Exception as exc:
            logger.exception("Audio input failed to stop")
            self._publish_audio_error("input_stop", exc)

        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=1.0)
        self._loop_thread = None

        try:
            self.audio_output.stop()
        except Exception as exc:
            logger.exception("Audio output failed to stop")
            self._publish_audio_error("output_stop", exc)
        self.collector.reset()

    # -------------------------------------------------------------------------
    # Frame Processing & Ingestion
    # -------------------------------------------------------------------------

    def process_frame(self, raw_frame: bytes | None) -> tuple[AudioSegment | None, Transcript | None]:
        """Process a single PCM frame through turn gate, VAD, and STT pipeline.

        Returns tuple of (completed_segment, transcript) if speech completed, or (None, None).
        """
        # 1. Half-duplex filtering
        frame = self.turn_gate.filter_frame(raw_frame)
        if frame is None:
            return None, None

        was_in_utterance = self.collector.is_in_utterance

        # 2. Utterance collector step
        segment, _ = self.collector.process_frame(frame)

        # 3. State transitions for Voice onset
        if not was_in_utterance and self.collector.is_in_utterance:
            self._handle_voice_started()

        # 4. Utterance completed
        if segment is not None:
            transcript = self._handle_utterance_completed(segment)
            return segment, transcript

        return None, None

    def _capture_loop(self) -> None:
        """Background thread reading and processing microphone frames."""
        while self._running:
            try:
                frame = self.audio_input.read_frame(timeout_seconds=0.05)
                if frame is not None:
                    self.process_frame(frame)
                else:
                    time.sleep(0.01)
            except Exception as exc:
                logger.exception("Audio capture loop failed")
                self._publish_audio_error("capture_loop", exc)
                self._running = False

    # -------------------------------------------------------------------------
    # Event and State Handlers
    # -------------------------------------------------------------------------

    def _publish_audio_error(self, stage: str, exc: Exception | str) -> None:
        """Publish lightweight audio failure metadata; never PCM or secrets."""
        if self.event_bus:
            self.event_bus.create_and_publish(
                event_type=EventType.AUDIO_ERROR,
                source="audio_coordinator",
                payload={"stage": stage, "error": type(exc).__name__ if isinstance(exc, Exception) else str(exc)},
            )

    def _handle_voice_started(self) -> None:
        """Handle transition when voice activity starts."""
        if self.state_manager and self.state_manager.current_state in {
            AssistantState.PROCESSING,
            AssistantState.SPEAKING,
            AssistantState.TOOL,
        }:
            return
        if self.state_manager:
            try:
                self.state_manager.transition_to(AssistantState.LISTENING, reason="voice_detected")
            except Exception as e:  # noqa: BLE001
                logger.debug("Ignored state transition to LISTENING: %s", e)

        if self.face_controller:
            self.face_controller.set_state(AssistantState.LISTENING)

        if self.event_bus:
            self.event_bus.create_and_publish(
                event_type=EventType.VOICE_STARTED,
                source="audio_coordinator",
                payload={"timestamp": self._clock()},
            )

    def _handle_utterance_completed(self, segment: AudioSegment) -> Transcript:
        """Handle finalized utterance segment, trigger STT, and publish events."""
        if self.event_bus:
            self.event_bus.create_and_publish(
                event_type=EventType.VOICE_ENDED,
                source="audio_coordinator",
                payload={"duration_ms": segment.duration_ms},
            )
            self.event_bus.create_and_publish(
                event_type=EventType.SPEECH_CAPTURED,
                source="audio_coordinator",
                payload={
                    "duration_ms": segment.duration_ms,
                    "sample_rate": segment.sample_rate,
                    "channels": segment.channels,
                },
            )

        # Transition to PROCESSING while STT transcribes
        if self.state_manager:
            try:
                self.state_manager.transition_to(AssistantState.PROCESSING, reason="stt_transcribing")
            except Exception as e:  # noqa: BLE001
                logger.debug("Ignored state transition to PROCESSING: %s", e)

        if self.face_controller:
            self.face_controller.set_state(AssistantState.PROCESSING)

        # Execute STT transcription. A backend failure must not strand the state machine.
        try:
            transcript = self.stt.transcribe(segment)
        except Exception as exc:
            logger.exception("STT backend failed")
            self._publish_audio_error("stt", exc)
            transcript = Transcript(text="", language="es", confidence=None, latency_ms=0.0)

        with self._lock:
            self._last_transcript = transcript

        if self.event_bus:
            self.event_bus.create_and_publish(
                event_type=EventType.TRANSCRIPT_READY,
                source="audio_coordinator",
                payload={
                    "text": transcript.text,
                    "confidence": transcript.confidence,
                    "latency_ms": transcript.latency_ms,
                },
            )

        # Standalone STT demos return to IDLE. A full conversation pipeline can
        # keep PROCESSING until AI/TTS completes to avoid a misleading idle face.
        if self.auto_reset_after_stt:
            if self.state_manager:
                try:
                    self.state_manager.transition_to(AssistantState.IDLE, reason="transcription_complete")
                except Exception as e:  # noqa: BLE001
                    logger.debug("Ignored state transition to IDLE: %s", e)

            if self.face_controller:
                self.face_controller.set_state(AssistantState.IDLE)

        return transcript

    # -------------------------------------------------------------------------
    # Speech Output (TTS) & Mouth Synchronization
    # -------------------------------------------------------------------------

    def speak(
        self,
        text: str,
        voice_id: str = "es_ES-standard",
        rate: float = 1.0,
        volume: float = 1.0,
    ) -> SpeechOutput:
        """Synthesize and play speech while blocking input and animating mouth."""
        if not text.strip():
            return SpeechOutput(duration_ms=0.0)

        # 1. Block incoming mic frames (Half-Duplex)
        self.turn_gate.start_speaking()

        # 2. Update state to SPEAKING
        prev_state = AssistantState.IDLE
        if self.state_manager:
            prev_state = self.state_manager.current_state
            try:
                self.state_manager.transition_to(AssistantState.SPEAKING, reason="tts_speaking")
            except Exception as e:  # noqa: BLE001
                logger.debug("Ignored state transition to SPEAKING: %s", e)

        restore_state = prev_state

        if self.face_controller:
            self.face_controller.set_state(AssistantState.SPEAKING)

        if self.event_bus:
            self.event_bus.create_and_publish(
                event_type=EventType.SPEECH_STARTED,
                source="audio_coordinator",
                payload={"text_len": len(text), "voice_id": voice_id},
            )

        req = SpeechRequest(text=text, voice_id=voice_id, rate=rate, volume=volume)
        output = SpeechOutput(duration_ms=0.0)
        success = False

        try:
            output = self.tts.synthesize(req)
            if output.audio_data:
                # Coarse MVP mouth sync: one normalized level for the blocking playback.
                rms = compute_pcm_rms(output.audio_data)
                mouth_level = min(1.0, max(0.2, rms * 2.5)) if rms > 0.01 else 0.0

                if self.face_controller:
                    self.face_controller.set_speech_level(mouth_level)

                self.audio_output.play(
                    output.audio_data,
                    sample_rate=output.sample_rate,
                    channels=output.channels,
                )
            success = output.audio_data is not None
        except Exception as exc:
            logger.exception("TTS/playback failed")
            self._publish_audio_error("tts_or_playback", exc)
            output = SpeechOutput(audio_data=None, duration_ms=0.0, latency_ms=0.0)
        finally:
            # 3. Clean up mouth and return to previous state
            if self.face_controller:
                self.face_controller.set_speech_level(0.0)
                self.face_controller.set_state(restore_state)

            if self.state_manager:
                try:
                    self.state_manager.transition_to(restore_state, reason="tts_finished")
                except Exception as e:  # noqa: BLE001
                    logger.debug("Ignored state transition back: %s", e)

            # 4. Unblock mic input with settling cooldown
            self.turn_gate.stop_speaking()

            if self.event_bus:
                self.event_bus.create_and_publish(
                    event_type=EventType.SPEECH_FINISHED,
                    source="audio_coordinator",
                    payload={
                        "duration_ms": output.duration_ms,
                        "latency_ms": output.latency_ms,
                        "success": success,
                    },
                )

        return output
