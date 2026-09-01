"""Audio Interaction Coordinator for AILEN.

Coordinates microphone capture, VAD utterance collection, STT transcription,
TTS synthesis, audio output playback, half-duplex turn gating, and face mouth sync.
"""

import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from itertools import chain

from ailen.audio.contracts import (
    AudioFrameProcessor,
    AudioInputBackend,
    AudioOutputBackend,
    AudioSegment,
    SpeechOutput,
    SpeechRequest,
    StagedAudioFrameProcessor,
    StreamingTtsBackend,
    SttBackend,
    Transcript,
    TtsBackend,
    VoiceActivityDetector,
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
from ailen.core.capabilities import CapabilityDescriptor
from ailen.core.events import EventBus
from ailen.core.state import StateManager
from ailen.domain.enums import AssistantState, EventType
from ailen.face.contracts import FaceController

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ReadySpeechChunk:
    output: SpeechOutput
    ready_monotonic: float


@dataclass(frozen=True)
class _SpeechGeneration:
    generation_id: int
    turn_id: str
    cancel_event: threading.Event


class AudioInteractionCoordinator:
    """Orchestrates audio input/output, VAD, STT, TTS, state transitions, and face levels."""

    def __init__(
        self,
        audio_input: AudioInputBackend | None = None,
        audio_output: AudioOutputBackend | None = None,
        frame_processor: AudioFrameProcessor | None = None,
        stt: SttBackend | None = None,
        tts: TtsBackend | None = None,
        utterance_collector: UtteranceCollector | None = None,
        turn_gate: AudioTurnGate | None = None,
        state_manager: StateManager | None = None,
        face_controller: FaceController | None = None,
        event_bus: EventBus | None = None,
        clock: Callable[[], float] | None = None,
        auto_reset_after_stt: bool = True,
        interruption_enabled: bool = False,
        interruption_threshold_rms: float = 0.02,
        interruption_min_ms: int = 120,
        interruption_calibration_ms: int = 160,
        interruption_leak_multiplier: float = 1.25,
        interruption_vad: VoiceActivityDetector | None = None,
        default_speech_rate: float = 1.0,
        frame_ms: float = 20.0,
    ) -> None:
        self.audio_input = audio_input or FakeAudioInputBackend()
        self.audio_output = audio_output or FakeAudioOutputBackend()
        self.frame_processor = frame_processor
        self.stt = stt or FakeSttBackend()
        self.tts = tts or FakeTtsBackend()
        self.collector = utterance_collector or UtteranceCollector(vad=EnergyVad())
        self.turn_gate = turn_gate or AudioTurnGate()
        self.state_manager = state_manager
        self.face_controller = face_controller
        self.event_bus = event_bus
        self._clock = clock or time.monotonic
        self.auto_reset_after_stt = auto_reset_after_stt
        self.interruption_enabled = interruption_enabled
        self.interruption_threshold_rms = max(0.001, min(1.0, interruption_threshold_rms))
        self.interruption_leak_multiplier = max(1.0, interruption_leak_multiplier)
        self.interruption_vad = interruption_vad
        self.default_speech_rate = max(0.5, min(1.8, default_speech_rate))
        self._interruption_frames_required = max(1, round(interruption_min_ms / frame_ms))
        self._interruption_calibration_frames = max(0, round(interruption_calibration_ms / frame_ms))
        self._interruption_calibration_seen = 0
        self._speaker_leak_peak_rms = 0.0
        if self.interruption_vad is not None:
            self.interruption_vad.reset()
        self._playback_started = False
        self._interruption_voice_frames = 0
        self._interruption_buffer: deque[bytes] = deque(
            maxlen=max(self._interruption_frames_required * 3, self._interruption_frames_required)
        )
        self._pending_interruption_frames: deque[bytes] = deque()
        self._interruption_triggered = False
        self._speech_cancel = threading.Event()
        self._last_speech_interrupted = False
        self._speech_lifecycle_lock = threading.RLock()
        self._tts_synthesis_lock = threading.Lock()
        self._tts_drain_lock = threading.Lock()
        self._tts_drain_threads: set[int] = set()
        self._speech_generation_sequence = 0
        self._active_speech_generation: _SpeechGeneration | None = None
        self._active_speech_running = False

        self._running = False
        self._loop_thread: threading.Thread | None = None
        self._last_transcript: Transcript | None = None
        self._lock = threading.Lock()
        self._last_vad_speech = False
        self._utterance_started_monotonic: float | None = None
        self._utterance_id: str | None = None
        self._utterance_sequence = 0
        self._rms_samples: dict[str, deque[float]] = {}
        self._last_rms_report_monotonic = self._clock()

    def capabilities(self) -> list[CapabilityDescriptor]:
        return [
            CapabilityDescriptor(
                key="speech.conversation",
                description="escuchar voz, transcribirla y responder hablando",
                available=self._running,
                source="audio",
            ),
            CapabilityDescriptor(
                key="speech.interrupt",
                description="ser interrumpida por la voz del usuario mientras habla",
                available=self._running and self.interruption_enabled,
                source="audio",
            ),
        ]

    @property
    def last_speech_interrupted(self) -> bool:
        """Whether the most recent spoken response was stopped by user barge-in."""
        return self._last_speech_interrupted

    @property
    def speech_cancelled(self) -> bool:
        """Whether barge-in cancelled the active speech/generation turn."""
        with self._speech_lifecycle_lock:
            return self._speech_cancel.is_set()

    @property
    def active_tts_drains(self) -> int:
        """Number of TTS workers still draining an uncancellable backend call."""
        with self._tts_drain_lock:
            return len(self._tts_drain_threads)

    def cancel_active_speech(self, *, reason: str = "cancelled") -> bool:
        """Cancel playback/logical generation without claiming ONNX was aborted."""
        with self._speech_lifecycle_lock:
            generation = self._active_speech_generation
            if generation is None or not self._active_speech_running:
                generation = None
                # Preserve the coordinator-level cancellation signal for
                # playback that was already marked SPEAKING by a lower layer
                # before a generation record existed. A future generation
                # replaces this alias with its own isolated event.
                self._speech_cancel.set()
            else:
                generation.cancel_event.set()
        if generation is None:
            # Barge-in can be exercised while an output process was started by
            # a lower layer before the speech lifecycle became observable.
            self.audio_output.stop()
            return False
        requested = self._clock()
        self.audio_output.stop()
        stopped = self._clock()
        logger.info(
            "audio_timing turn_id=%s speech_generation=%d stage=playback_stop "
            "timestamp_monotonic=%.6f stop_latency_ms=%.1f reason=%s",
            generation.turn_id,
            generation.generation_id,
            stopped,
            (stopped - requested) * 1000.0,
            reason,
        )
        logger.info(
            "audio_timing turn_id=%s speech_generation=%d stage=generation_stop "
            "timestamp_monotonic=%.6f logical_only=true reason=%s",
            generation.turn_id,
            generation.generation_id,
            requested,
            reason,
        )
        return True

    def _begin_speech_generation(self, turn_id: str | None) -> _SpeechGeneration:
        previous: _SpeechGeneration | None = None
        with self._speech_lifecycle_lock:
            if self._active_speech_running and self._active_speech_generation is not None:
                previous = self._active_speech_generation
                previous.cancel_event.set()
            self._speech_generation_sequence += 1
            generation = _SpeechGeneration(
                generation_id=self._speech_generation_sequence,
                turn_id=turn_id or f"speech-{self._speech_generation_sequence}",
                cancel_event=threading.Event(),
            )
            self._active_speech_generation = generation
            self._active_speech_running = True
            # Compatibility for existing audio/barge-in observers. Workers
            # always capture their generation-local event and never read this
            # alias after a newer turn begins.
            self._speech_cancel = generation.cancel_event
        if previous is not None:
            try:
                self.audio_output.stop()
            except Exception as exc:  # noqa: BLE001
                self._publish_audio_error("supersede_playback_stop", exc)
            logger.info(
                "audio_timing turn_id=%s speech_generation=%d stage=generation_stop "
                "timestamp_monotonic=%.6f logical_only=true reason=superseded",
                previous.turn_id,
                previous.generation_id,
                self._clock(),
            )
        return generation

    def _is_current_speech_generation(self, generation_id: int) -> bool:
        with self._speech_lifecycle_lock:
            return bool(
                self._active_speech_generation is not None
                and self._active_speech_generation.generation_id == generation_id
            )

    def _finish_speech_generation(self, generation_id: int) -> None:
        with self._speech_lifecycle_lock:
            if (
                self._active_speech_generation is not None
                and self._active_speech_generation.generation_id == generation_id
            ):
                self._active_speech_running = False

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
        if self.frame_processor is not None:
            self.frame_processor.reset()

    # -------------------------------------------------------------------------
    # Frame Processing & Ingestion
    # -------------------------------------------------------------------------

    def process_frame(self, raw_frame: bytes | None) -> tuple[AudioSegment | None, Transcript | None]:
        """Process a single PCM frame through turn gate, VAD, and STT pipeline.

        Returns tuple of (completed_segment, transcript) if speech completed, or (None, None).
        """
        if raw_frame is None:
            return None, None

        self._observe_rms("mic_raw", compute_pcm_rms(raw_frame))
        frame_for_processing = raw_frame
        if self.frame_processor is not None:
            try:
                if isinstance(self.frame_processor, StagedAudioFrameProcessor):
                    stages = self.frame_processor.process_with_stages(raw_frame)
                    if not stages:
                        raise ValueError("staged audio processor returned no frames")
                    frame_for_processing = stages[-1][1]
                    for stage_name, stage_frame in stages[1:]:
                        self._observe_rms(
                            f"mic_after_{stage_name}",
                            compute_pcm_rms(stage_frame),
                        )
                else:
                    frame_for_processing = self.frame_processor.process(raw_frame)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Audio frame cleanup failed; using raw PCM: %s", exc)
                self._publish_audio_error("frame_processor", exc)
                frame_for_processing = raw_frame
        self._observe_rms("mic_clean", compute_pcm_rms(frame_for_processing))

        # Normal STT remains isolated from speaker output, but cleaned microphone
        # audio can still request a barge-in while TTS is playing.
        if self.turn_gate.is_speaking:
            if self.interruption_enabled:
                self._inspect_barge_in(frame_for_processing)
            return None, None

        if self._interruption_triggered:
            # Once barge-in fires, every subsequent microphone frame belongs to
            # that user turn. Keep buffering through the previous processing
            # blocker and its settling cooldown instead of opening a 150 ms hole.
            if self.turn_gate.is_processing or not self.turn_gate.is_listening_allowed():
                self._observe_rms("barge_buffered", compute_pcm_rms(frame_for_processing))
                self._pending_interruption_frames.append(frame_for_processing)
                return None, None

            # Drain incrementally. Clearing the deque up front discarded all
            # frames after the first completed segment, including the tail of a
            # real interruption or a second utterance already captured.
            self._pending_interruption_frames.append(frame_for_processing)
            while self._pending_interruption_frames:
                buffered_frame = self._pending_interruption_frames.popleft()
                result = self._process_listening_frame(buffered_frame)
                if result[0] is not None:
                    return result
            return None, None

        frame = self.turn_gate.filter_frame(frame_for_processing)
        if frame is None:
            phase = "processing_blocked" if self.turn_gate.is_processing else "cooldown_blocked"
            self._observe_rms(phase, compute_pcm_rms(frame_for_processing))
            return None, None

        return self._process_listening_frame(frame)

    def _process_listening_frame(
        self, frame: bytes
    ) -> tuple[AudioSegment | None, Transcript | None]:
        was_in_utterance = self.collector.is_in_utterance
        segment, _ = self.collector.process_frame(frame)
        vad_result = self.collector.last_vad_result
        rms = vad_result.rms if vad_result is not None else compute_pcm_rms(frame)
        vad_speech = bool(vad_result and vad_result.is_speech)
        self._observe_rms("user_voice" if vad_speech else "idle", rms)
        if vad_speech != self._last_vad_speech:
            logger.info(
                "audio_timing stage=vad_%s timestamp_monotonic=%.6f rms=%.5f trigger=%s",
                "speech_on" if vad_speech else "speech_off",
                self._clock(),
                rms,
                vad_result.is_trigger if vad_result is not None else None,
            )
            self._last_vad_speech = vad_speech
        if not was_in_utterance and self.collector.is_in_utterance:
            self._utterance_sequence += 1
            self._utterance_id = f"utterance-{self._utterance_sequence}"
            self._utterance_started_monotonic = self._clock()
            logger.info(
                "audio_timing utterance_id=%s stage=utterance_start "
                "timestamp_monotonic=%.6f rms=%.5f",
                self._utterance_id,
                self._utterance_started_monotonic,
                rms,
            )
            self._handle_voice_started()
        if segment is not None:
            ended = self._clock()
            wall_ms = (
                (ended - self._utterance_started_monotonic) * 1000.0
                if self._utterance_started_monotonic is not None
                else None
            )
            frame_count = round(segment.duration_ms / self.collector.frame_ms)
            logger.info(
                "audio_timing utterance_id=%s stage=utterance_end "
                "timestamp_monotonic=%.6f pcm_duration_ms=%.1f wall_duration_ms=%s frames=%d",
                self._utterance_id,
                ended,
                segment.duration_ms,
                f"{wall_ms:.1f}" if wall_ms is not None else "unknown",
                frame_count,
            )
            return segment, self._handle_utterance_completed(segment)
        return None, None

    def _inspect_barge_in(self, frame: bytes) -> None:
        rms = compute_pcm_rms(frame)
        self._observe_rms("tts_mic", rms)
        if self._interruption_triggered:
            self._pending_interruption_frames.append(frame)
            return

        if (
            self._playback_started
            and self._interruption_calibration_seen < self._interruption_calibration_frames
        ):
            self._interruption_calibration_seen += 1
            # Calibrate only energy close to the configured leakage floor. A
            # much louder opening frame may already be the user; treating it as
            # leakage raises the adaptive threshold above that same voice and
            # makes an immediate interruption impossible.
            calibration_ceiling = (
                self.interruption_threshold_rms * self.interruption_leak_multiplier
            )
            if rms < calibration_ceiling:
                self._speaker_leak_peak_rms = max(self._speaker_leak_peak_rms, rms)
                return

        effective_threshold = max(
            self.interruption_threshold_rms,
            self._speaker_leak_peak_rms * self.interruption_leak_multiplier,
        )
        classified_voice = True
        if self.interruption_vad is not None:
            voice_result = self.interruption_vad.process_frame(frame)
            classified_voice = bool(voice_result.is_trigger)
        if rms < effective_threshold or not classified_voice:
            self._interruption_voice_frames = 0
            self._interruption_buffer.clear()
            return

        self._interruption_voice_frames += 1
        self._interruption_buffer.append(frame)
        if self._interruption_voice_frames < self._interruption_frames_required:
            return

        self._interruption_triggered = True
        self._last_speech_interrupted = True
        self._pending_interruption_frames.extend(self._interruption_buffer)
        with self._speech_lifecycle_lock:
            interrupted_generation = self._active_speech_generation
        stop_started = self._clock()
        logical_generation_cancelled = self.cancel_active_speech(reason="barge_in")
        stop_ended = self._clock()
        logger.info(
            "audio_timing stage=barge_in_trigger timestamp_monotonic=%.6f "
            "rms=%.5f threshold=%.5f stop_latency_ms=%.1f buffered_frames=%d",
            stop_started,
            rms,
            effective_threshold,
            (stop_ended - stop_started) * 1000.0,
            len(self._pending_interruption_frames),
        )
        if self.event_bus:
            self.event_bus.create_and_publish(
                event_type=EventType.SPEECH_INTERRUPTED,
                source="audio_coordinator",
                payload={
                    "rms": round(rms, 4),
                    "threshold": round(effective_threshold, 4),
                    "turn_id": (
                        interrupted_generation.turn_id
                        if interrupted_generation is not None
                        else None
                    ),
                    "speech_generation": (
                        interrupted_generation.generation_id
                        if interrupted_generation is not None
                        else None
                    ),
                    "buffered_frames": len(self._pending_interruption_frames),
                    "playback_stop_ms": (stop_ended - stop_started) * 1000.0,
                    "logical_generation_cancelled": logical_generation_cancelled,
                    "synthesizer_draining": self.active_tts_drains > 0,
                },
            )

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

    def _observe_rms(self, phase: str, rms: float) -> None:
        """Aggregate bounded RMS diagnostics without logging PCM or every frame."""
        samples = self._rms_samples.setdefault(phase, deque(maxlen=500))
        samples.append(rms)
        now = self._clock()
        if now - self._last_rms_report_monotonic < 5.0:
            return
        self._last_rms_report_monotonic = now
        for sample_phase, phase_samples in sorted(self._rms_samples.items()):
            if not phase_samples:
                continue
            values = sorted(phase_samples)
            p50 = values[len(values) // 2]
            p95 = values[min(len(values) - 1, int(len(values) * 0.95))]
            logger.info(
                "audio_rms phase=%s timestamp_monotonic=%.6f frames=%d "
                "avg=%.5f p50=%.5f p95=%.5f max=%.5f",
                sample_phase,
                now,
                len(values),
                sum(values) / len(values),
                p50,
                p95,
                values[-1],
            )
            phase_samples.clear()

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
        utterance_id = self._utterance_id
        audio_ended = self._clock()
        if self.event_bus:
            self.event_bus.create_and_publish(
                event_type=EventType.VOICE_ENDED,
                source="audio_coordinator",
                payload={
                    "duration_ms": segment.duration_ms,
                    "utterance_id": utterance_id,
                    "audio_end_monotonic": audio_ended,
                },
            )
            self.event_bus.create_and_publish(
                event_type=EventType.SPEECH_CAPTURED,
                source="audio_coordinator",
                payload={
                    "duration_ms": segment.duration_ms,
                    "sample_rate": segment.sample_rate,
                    "channels": segment.channels,
                    "utterance_id": utterance_id,
                    "frame_count": round(segment.duration_ms / self.collector.frame_ms),
                    "truncated": segment.truncated,
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
        stt_started = self._clock()
        logger.info(
            "audio_timing utterance_id=%s stage=stt_start timestamp_monotonic=%.6f",
            utterance_id,
            stt_started,
        )
        try:
            transcript = self.stt.transcribe(segment)
        except Exception as exc:
            logger.exception("STT backend failed")
            self._publish_audio_error("stt", exc)
            transcript = Transcript(text="", language="es", confidence=None, latency_ms=0.0)
        transcript = replace(
            transcript,
            audio_duration_ms=segment.duration_ms,
            utterance_id=utterance_id,
            interrupted=self._interruption_triggered,
            truncated=segment.truncated,
        )
        stt_ended = self._clock()
        logger.info(
            "audio_timing utterance_id=%s stage=stt_end timestamp_monotonic=%.6f "
            "duration_ms=%.1f backend_latency_ms=%.1f transcript_chars=%d confidence=%s",
            utterance_id,
            stt_ended,
            (stt_ended - stt_started) * 1000.0,
            transcript.latency_ms,
            len(transcript.text),
            "unknown" if transcript.confidence is None else f"{transcript.confidence:.3f}",
        )

        with self._lock:
            self._last_transcript = transcript

        if self.event_bus:
            self.event_bus.create_and_publish(
                event_type=EventType.TRANSCRIPT_READY,
                source="audio_coordinator",
                payload={
                    "text": transcript.text,
                    "language": transcript.language,
                    "confidence": transcript.confidence,
                    "latency_ms": transcript.latency_ms,
                    "engine": transcript.engine,
                    "audio_duration_ms": transcript.audio_duration_ms,
                    "utterance_id": utterance_id,
                    "interrupted": transcript.interrupted,
                    "truncated": transcript.truncated,
                    "alternatives": [
                        {"text": item.text, "confidence": item.confidence}
                        for item in transcript.alternatives
                    ],
                    "audio_end_monotonic": audio_ended,
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
        rate: float | None = None,
        volume: float = 1.0,
        emotion: str = "neutral",
        expressiveness: float = 0.6,
        turn_id: str | None = None,
    ) -> SpeechOutput:
        """Synthesize and play one text as a cancelable speech turn."""
        if not text.strip():
            return SpeechOutput(duration_ms=0.0)
        speech_rate = self.default_speech_rate if rate is None else rate
        return self.speak_requests(
            (
                SpeechRequest(
                    text=text,
                    voice_id=voice_id,
                    rate=speech_rate,
                    volume=volume,
                    emotion=emotion,
                    expressiveness=max(0.0, min(1.0, expressiveness)),
                ),
            ),
            turn_id=turn_id,
        )

    def speak_requests(
        self,
        requests: Iterable[SpeechRequest],
        *,
        turn_id: str | None = None,
    ) -> SpeechOutput:
        """Synthesize incremental text requests as one cancelable speech turn.

        If the backend exposes StreamingTtsBackend, sentence PCM chunks are
        played as they become available. SPEECH_STARTED means the first playable
        PCM buffer is about to be submitted. The iterable may block while the
        LLM produces its next phrase; only one decoded PCM chunk is prefetched.
        """
        request_iterator = (request for request in requests if request.text.strip())
        try:
            first_request = next(request_iterator)
        except StopIteration:
            return SpeechOutput(duration_ms=0.0)

        generation = self._begin_speech_generation(turn_id)
        turn_cancel = generation.cancel_event
        self._last_speech_interrupted = False
        self._interruption_voice_frames = 0
        self._interruption_buffer.clear()
        self._pending_interruption_frames.clear()
        self._interruption_triggered = False
        self._interruption_calibration_seen = 0
        self._speaker_leak_peak_rms = 0.0
        if self.interruption_vad is not None:
            self.interruption_vad.reset()
        self._playback_started = False

        text = first_request.text
        voice_id = first_request.voice_id
        speech_requested = self._clock()
        logger.info(
            "audio_timing turn_id=%s speech_generation=%d stage=tts_request "
            "timestamp_monotonic=%.6f text_chars=%d",
            generation.turn_id,
            generation.generation_id,
            speech_requested,
            len(text),
        )
        self.turn_gate.start_speaking()
        prev_state = self.state_manager.current_state if self.state_manager else AssistantState.IDLE
        restore_state = prev_state
        all_requests = chain((first_request,), request_iterator)
        output = SpeechOutput(duration_ms=0.0)
        success = False
        speech_started = False

        def start_playback(first_output: SpeechOutput) -> None:
            nonlocal speech_started
            if speech_started:
                return
            if turn_cancel.is_set() or not self._is_current_speech_generation(
                generation.generation_id
            ):
                return
            speech_started = True
            self._playback_started = True
            logger.info(
                "audio_timing turn_id=%s speech_generation=%d stage=first_pcm_submit "
                "timestamp_monotonic=%.6f "
                "request_to_pcm_ms=%.1f chunk_latency_ms=%.1f",
                generation.turn_id,
                generation.generation_id,
                self._clock(),
                (self._clock() - speech_requested) * 1000.0,
                first_output.latency_ms,
            )
            if self.state_manager:
                try:
                    self.state_manager.transition_to(AssistantState.SPEAKING, reason="tts_playback_started")
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Ignored state transition to SPEAKING: %s", exc)
            if self.face_controller:
                self.face_controller.set_state(AssistantState.SPEAKING)
            if self.event_bus:
                self.event_bus.create_and_publish(
                    event_type=EventType.SPEECH_STARTED,
                    source="audio_coordinator",
                    payload={
                        "text_len": len(text),
                        "voice_id": voice_id,
                        "first_audio_latency_ms": first_output.latency_ms,
                        "request_to_pcm_ms": (
                            self._clock() - speech_requested
                        ) * 1000.0,
                        "turn_id": generation.turn_id,
                        "speech_generation": generation.generation_id,
                        "expression_requested": first_request.emotion,
                    },
                )

        def play_chunk(
            chunk: SpeechOutput,
            chunk_index: int,
            gap_ms: float | None,
            prefetch_lead_ms: float | None = None,
        ) -> None:
            if (
                not chunk.audio_data
                or turn_cancel.is_set()
                or not self._is_current_speech_generation(generation.generation_id)
            ):
                return
            logger.info(
                "audio_timing turn_id=%s speech_generation=%d stage=tts_chunk_ready "
                "timestamp_monotonic=%.6f "
                "chunk=%d synthesis_latency_ms=%.1f audio_duration_ms=%.1f "
                "gap_ms=%s prefetch_lead_ms=%s",
                generation.turn_id,
                generation.generation_id,
                self._clock(),
                chunk_index,
                chunk.latency_ms,
                chunk.duration_ms,
                f"{gap_ms:.1f}" if gap_ms is not None else "first",
                (
                    f"{prefetch_lead_ms:.1f}"
                    if prefetch_lead_ms is not None
                    else "first"
                ),
            )
            start_playback(chunk)
            if turn_cancel.is_set() or not self._is_current_speech_generation(
                generation.generation_id
            ):
                return
            envelope_stop = threading.Event()
            envelope_thread: threading.Thread | None = None
            face_controller = self.face_controller
            if face_controller:
                pcm = chunk.audio_data
                bytes_per_frame = max(2, chunk.channels * 2)
                window_frames = max(1, round(chunk.sample_rate * 0.033))
                window_bytes = max(bytes_per_frame, window_frames * bytes_per_frame)

                def animate_speech_envelope() -> None:
                    for offset in range(0, len(pcm), window_bytes):
                        if envelope_stop.is_set() or turn_cancel.is_set():
                            break
                        window = pcm[offset : offset + window_bytes]
                        rms = compute_pcm_rms(window)
                        level = min(1.0, rms * 5.0) if rms >= 0.002 else 0.0
                        face_controller.set_speech_level(level)
                        if envelope_stop.wait(timeout=len(window) / float(chunk.sample_rate * bytes_per_frame)):
                            break

                envelope_thread = threading.Thread(
                    target=animate_speech_envelope,
                    name="ailen-face-speech-envelope",
                    daemon=True,
                )
                envelope_thread.start()
            try:
                self.audio_output.play(
                    chunk.audio_data,
                    sample_rate=chunk.sample_rate,
                    channels=chunk.channels,
                    cancel_event=turn_cancel,
                )
            finally:
                envelope_stop.set()
                if envelope_thread is not None:
                    envelope_thread.join(timeout=0.15)
                if face_controller:
                    face_controller.set_speech_level(0.0)
            logger.info(
                "audio_timing turn_id=%s speech_generation=%d stage=tts_chunk_played "
                "timestamp_monotonic=%.6f chunk=%d",
                generation.turn_id,
                generation.generation_id,
                self._clock(),
                chunk_index,
            )

        try:
            combined = bytearray()
            total_duration_ms = 0.0
            first_audio_latency_ms = 0.0
            sample_rate = 22050
            channels = 1
            stream_format: tuple[int, int] | None = None
            combined_compatible = True
            previous_playback_ended: float | None = None
            ready_chunks: queue.Queue[object] = queue.Queue(maxsize=1)
            synthesis_stop = threading.Event()
            stream_end = object()

            def synthesis_cancelled() -> bool:
                return bool(
                    synthesis_stop.is_set()
                    or turn_cancel.is_set()
                    or not self._is_current_speech_generation(generation.generation_id)
                )

            def queue_prefetch(item: object) -> bool:
                while not synthesis_cancelled():
                    try:
                        ready_chunks.put(item, timeout=0.05)
                        return True
                    except queue.Full:
                        continue
                return False

            def synthesize_ahead() -> None:
                thread_key = id(threading.current_thread())
                with self._tts_drain_lock:
                    self._tts_drain_threads.add(thread_key)
                drain_published = False

                def publish_drained() -> None:
                    nonlocal drain_published
                    if drain_published:
                        return
                    drain_published = True
                    cancelled = turn_cancel.is_set()
                    stale = not self._is_current_speech_generation(
                        generation.generation_id
                    )
                    logger.info(
                        "audio_timing turn_id=%s speech_generation=%d "
                        "stage=stale_tts_drain_complete timestamp_monotonic=%.6f "
                        "cancelled=%s stale=%s",
                        generation.turn_id,
                        generation.generation_id,
                        self._clock(),
                        cancelled,
                        stale,
                    )
                    try:
                        if self.event_bus:
                            self.event_bus.create_and_publish(
                                event_type=EventType.SPEECH_SYNTHESIS_DRAINED,
                                source="audio_coordinator",
                                payload={
                                    "turn_id": generation.turn_id,
                                    "speech_generation": generation.generation_id,
                                    "cancelled": cancelled,
                                    "stale": stale,
                                },
                            )
                    except Exception:
                        logger.exception("Failed to publish TTS drain event")
                    finally:
                        # Observers must see the drain event before the public
                        # count reaches zero.
                        with self._tts_drain_lock:
                            self._tts_drain_threads.discard(thread_key)
                try:
                    for request_index, request in enumerate(all_requests, start=1):
                        if synthesis_cancelled():
                            return
                        logger.info(
                            "audio_timing turn_id=%s speech_generation=%d "
                            "stage=tts_phrase_request timestamp_monotonic=%.6f "
                            "phrase=%d text_chars=%d emotion=%s",
                            generation.turn_id,
                            generation.generation_id,
                            self._clock(),
                            request_index,
                            len(request.text),
                            request.emotion,
                        )
                        acquired = False
                        while not synthesis_cancelled():
                            acquired = self._tts_synthesis_lock.acquire(timeout=0.05)
                            if acquired:
                                break
                        if not acquired:
                            return
                        try:
                            outputs: Iterable[SpeechOutput]
                            if isinstance(self.tts, StreamingTtsBackend):
                                outputs = self.tts.synthesize_chunks(request)
                            else:
                                outputs = (self.tts.synthesize(request),)
                            for chunk in outputs:
                                if synthesis_cancelled():
                                    logger.info(
                                        "audio_timing turn_id=%s speech_generation=%d "
                                        "stage=tts_prefetch_discarded "
                                        "timestamp_monotonic=%.6f",
                                        generation.turn_id,
                                        generation.generation_id,
                                        self._clock(),
                                    )
                                    return
                                if not queue_prefetch(
                                    _ReadySpeechChunk(
                                        output=chunk,
                                        ready_monotonic=self._clock(),
                                    )
                                ):
                                    return
                        finally:
                            if synthesis_cancelled():
                                # Keep the non-concurrent backend lock until the
                                # stale/cancelled drain is observable. A newer
                                # generation cannot overtake this lifecycle edge.
                                publish_drained()
                            self._tts_synthesis_lock.release()
                    queue_prefetch(stream_end)
                except Exception as exc:  # noqa: BLE001
                    if not synthesis_cancelled():
                        queue_prefetch(exc)
                finally:
                    publish_drained()

            synthesis_thread = threading.Thread(
                target=synthesize_ahead,
                name="ailen-tts-prefetch",
                daemon=True,
            )
            synthesis_thread.start()
            chunk_index = 0
            try:
                while not turn_cancel.is_set():
                    try:
                        item = ready_chunks.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    if item is stream_end:
                        break
                    if isinstance(item, Exception):
                        raise item
                    if not isinstance(item, _ReadySpeechChunk):
                        raise TypeError("Unexpected TTS prefetch result")

                    chunk = item.output
                    if not chunk.audio_data:
                        continue
                    chunk_index += 1
                    if not combined:
                        first_audio_latency_ms = chunk.latency_ms
                    if previous_playback_ended is None:
                        gap_ms = None
                        prefetch_lead_ms = None
                    else:
                        gap_ms = max(
                            0.0,
                            (item.ready_monotonic - previous_playback_ended) * 1000.0,
                        )
                        prefetch_lead_ms = max(
                            0.0,
                            (previous_playback_ended - item.ready_monotonic) * 1000.0,
                        )
                    play_chunk(chunk, chunk_index, gap_ms, prefetch_lead_ms)
                    previous_playback_ended = self._clock()
                    if turn_cancel.is_set():
                        break
                    chunk_format = (chunk.sample_rate, chunk.channels)
                    if stream_format is None:
                        stream_format = chunk_format
                        sample_rate, channels = chunk_format
                    elif chunk_format != stream_format:
                        combined_compatible = False
                    if combined_compatible:
                        combined.extend(chunk.audio_data)
                    total_duration_ms += chunk.duration_ms
            finally:
                synthesis_stop.set()
                synthesis_thread.join(timeout=0.05 if turn_cancel.is_set() else 0.25)
                if synthesis_thread.is_alive():
                    logger.info(
                        "audio_timing turn_id=%s speech_generation=%d "
                        "stage=tts_synthesizer_draining timestamp_monotonic=%.6f "
                        "backend_cancel_supported=false",
                        generation.turn_id,
                        generation.generation_id,
                        self._clock(),
                    )
            output = SpeechOutput(
                audio_data=bytes(combined) if combined and combined_compatible else None,
                sample_rate=sample_rate,
                channels=channels,
                duration_ms=total_duration_ms,
                latency_ms=first_audio_latency_ms,
            )
            success = (speech_started or bool(output.audio_data)) and not turn_cancel.is_set()
        except Exception as exc:
            logger.exception("TTS/playback failed")
            self._publish_audio_error("tts_or_playback", exc)
            output = SpeechOutput(audio_data=None, duration_ms=0.0, latency_ms=0.0)
        finally:
            if self._is_current_speech_generation(generation.generation_id):
                if self.face_controller:
                    self.face_controller.set_speech_level(0.0)
                    self.face_controller.set_state(restore_state)

                if self.state_manager:
                    try:
                        self.state_manager.transition_to(restore_state, reason="tts_finished")
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("Ignored state transition back: %s", exc)

                self.turn_gate.stop_speaking()

                if self.event_bus:
                    self.event_bus.create_and_publish(
                        event_type=EventType.SPEECH_FINISHED,
                        source="audio_coordinator",
                        payload={
                            "duration_ms": output.duration_ms,
                            "latency_ms": output.latency_ms,
                            "success": success,
                            "interrupted": self._last_speech_interrupted,
                            "speech_generation": generation.generation_id,
                            "turn_id": generation.turn_id,
                            "synthesizer_draining": self.active_tts_drains > 0,
                        },
                    )
                self._finish_speech_generation(generation.generation_id)

        return output
