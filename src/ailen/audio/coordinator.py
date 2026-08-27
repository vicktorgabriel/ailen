"""Audio Interaction Coordinator for AILEN.

Coordinates microphone capture, VAD utterance collection, STT transcription,
TTS synthesis, audio output playback, half-duplex turn gating, and face mouth sync.
"""

import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from ailen.audio.contracts import (
    AudioFrameProcessor,
    AudioInputBackend,
    AudioOutputBackend,
    AudioSegment,
    SpeechOutput,
    SpeechRequest,
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

        frame_for_processing = raw_frame
        if self.frame_processor is not None:
            try:
                frame_for_processing = self.frame_processor.process(raw_frame)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Audio frame cleanup failed; using raw PCM: %s", exc)
                self._publish_audio_error("frame_processor", exc)
                frame_for_processing = raw_frame
            self._observe_rms("mic_raw", compute_pcm_rms(frame_for_processing))
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
        self._speech_cancel.set()
        stop_started = self._clock()
        self.audio_output.stop()
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
        stt_ended = self._clock()
        logger.info(
            "audio_timing utterance_id=%s stage=stt_end timestamp_monotonic=%.6f "
            "duration_ms=%.1f backend_latency_ms=%.1f transcript_chars=%d",
            utterance_id,
            stt_ended,
            (stt_ended - stt_started) * 1000.0,
            transcript.latency_ms,
            len(transcript.text),
        )

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
                    "utterance_id": utterance_id,
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
    ) -> SpeechOutput:
        """Synthesize and play speech while blocking input and animating mouth.

        If the backend exposes StreamingTtsBackend, sentence PCM chunks are
        played as they become available. SPEECH_STARTED means the first playable
        PCM buffer is about to be submitted to the audio output backend.
        """
        if not text.strip():
            return SpeechOutput(duration_ms=0.0)

        self._speech_cancel.clear()
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
        speech_requested = self._clock()
        logger.info(
            "audio_timing stage=tts_request timestamp_monotonic=%.6f text_chars=%d",
            speech_requested,
            len(text),
        )
        self.turn_gate.start_speaking()
        prev_state = self.state_manager.current_state if self.state_manager else AssistantState.IDLE
        restore_state = prev_state
        speech_rate = self.default_speech_rate if rate is None else rate
        req = SpeechRequest(text=text, voice_id=voice_id, rate=speech_rate, volume=volume)
        output = SpeechOutput(duration_ms=0.0)
        success = False
        speech_started = False

        def start_playback(first_output: SpeechOutput) -> None:
            nonlocal speech_started
            if speech_started:
                return
            speech_started = True
            self._playback_started = True
            logger.info(
                "audio_timing stage=first_pcm_submit timestamp_monotonic=%.6f "
                "request_to_pcm_ms=%.1f chunk_latency_ms=%.1f",
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
                    },
                )

        def play_chunk(
            chunk: SpeechOutput,
            chunk_index: int,
            gap_ms: float | None,
            prefetch_lead_ms: float | None = None,
        ) -> None:
            if not chunk.audio_data:
                return
            logger.info(
                "audio_timing stage=tts_chunk_ready timestamp_monotonic=%.6f "
                "chunk=%d synthesis_latency_ms=%.1f audio_duration_ms=%.1f "
                "gap_ms=%s prefetch_lead_ms=%s",
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
                        if envelope_stop.is_set() or self._speech_cancel.is_set():
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
                    cancel_event=self._speech_cancel,
                )
            finally:
                envelope_stop.set()
                if envelope_thread is not None:
                    envelope_thread.join(timeout=0.15)
                if face_controller:
                    face_controller.set_speech_level(0.0)
            logger.info(
                "audio_timing stage=tts_chunk_played timestamp_monotonic=%.6f chunk=%d",
                self._clock(),
                chunk_index,
            )

        try:
            if isinstance(self.tts, StreamingTtsBackend):
                streaming_tts = self.tts
                combined = bytearray()
                total_duration_ms = 0.0
                first_audio_latency_ms = 0.0
                sample_rate = 22050
                channels = 1
                previous_playback_ended: float | None = None
                ready_chunks: queue.Queue[object] = queue.Queue(maxsize=4)
                synthesis_stop = threading.Event()
                stream_end = object()

                def synthesis_cancelled() -> bool:
                    return synthesis_stop.is_set() or self._speech_cancel.is_set()

                def queue_prefetch(item: object) -> bool:
                    while not synthesis_cancelled():
                        try:
                            ready_chunks.put(item, timeout=0.05)
                            return True
                        except queue.Full:
                            continue
                    return False

                def synthesize_ahead() -> None:
                    try:
                        chunks = iter(streaming_tts.synthesize_chunks(req))
                        while not synthesis_cancelled():
                            try:
                                chunk = next(chunks)
                            except StopIteration:
                                queue_prefetch(stream_end)
                                return
                            if synthesis_cancelled():
                                logger.info(
                                    "audio_timing stage=tts_prefetch_discarded "
                                    "timestamp_monotonic=%.6f",
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
                    except Exception as exc:  # noqa: BLE001
                        if not synthesis_cancelled():
                            queue_prefetch(exc)

                synthesis_thread = threading.Thread(
                    target=synthesize_ahead,
                    name="ailen-tts-prefetch",
                    daemon=True,
                )
                synthesis_thread.start()
                chunk_index = 0
                try:
                    while not self._speech_cancel.is_set():
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
                        if self._speech_cancel.is_set():
                            break
                        combined.extend(chunk.audio_data)
                        total_duration_ms += chunk.duration_ms
                        sample_rate = chunk.sample_rate
                        channels = chunk.channels
                finally:
                    synthesis_stop.set()
                output = SpeechOutput(
                    audio_data=bytes(combined) if combined else None,
                    sample_rate=sample_rate,
                    channels=channels,
                    duration_ms=total_duration_ms,
                    latency_ms=first_audio_latency_ms,
                )
            else:
                output = self.tts.synthesize(req)
                if not self._speech_cancel.is_set():
                    play_chunk(output, 1, None)
            success = bool(output.audio_data)
        except Exception as exc:
            logger.exception("TTS/playback failed")
            self._publish_audio_error("tts_or_playback", exc)
            output = SpeechOutput(audio_data=None, duration_ms=0.0, latency_ms=0.0)
        finally:
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
                    },
                )

        return output
