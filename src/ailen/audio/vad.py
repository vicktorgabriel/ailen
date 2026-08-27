"""Voice Activity Detection (VAD) and Utterance Collection for AILEN.

Provides energy/RMS-based voice detection and temporal utterance grouping
without requiring heavy external machine learning dependencies.
"""

import importlib.util
from collections import deque
from enum import Enum

from ailen.audio.contracts import AudioSegment, VadResult, VoiceActivityDetector
from ailen.audio.pcm import compute_pcm_duration_ms, compute_pcm_rms


class VadProfile(str, Enum):
    """VAD responsiveness and silence cutoff profile."""
    CONSERVATIVE = "conservative"  # silence_timeout_ms=700, min_speech_ms=250
    NORMAL = "normal"              # silence_timeout_ms=500, min_speech_ms=200
    FAST = "fast"                  # silence_timeout_ms=350, min_speech_ms=150


def get_vad_profile_timings(profile: VadProfile | str) -> tuple[float, float, float]:
    """Return (silence_timeout_ms, min_speech_ms, pre_roll_ms) for a given profile."""
    prof_str = str(profile.value if isinstance(profile, Enum) else profile).lower()
    if prof_str == "fast":
        return 350.0, 150.0, 150.0
    if prof_str == "conservative":
        return 700.0, 250.0, 200.0
    # Default: NORMAL
    return 500.0, 200.0, 200.0


class EnergyVad(VoiceActivityDetector):
    """Lightweight pure-Python Energy/RMS-based Voice Activity Detector."""

    def __init__(
        self,
        threshold_rms: float = 0.02,
        hangover_frames: int = 15,
    ) -> None:
        """Initialize Energy VAD.

        :param threshold_rms: Normalized RMS threshold [0.0..1.0] above which a frame is voice.
        :param hangover_frames: Number of hangover frames to prevent clipping short inter-word pauses.
        """
        self.threshold_rms = threshold_rms
        self.hangover_frames = hangover_frames
        self._hangover_counter = 0

    def process_frame(self, frame: bytes) -> VadResult:
        """Analyze a PCM frame and return VadResult."""
        rms = compute_pcm_rms(frame)
        energy = rms * rms
        is_trigger = rms >= self.threshold_rms

        if is_trigger:
            self._hangover_counter = self.hangover_frames
            is_speech = True
        elif self._hangover_counter > 0:
            self._hangover_counter -= 1
            is_speech = True
        else:
            is_speech = False

        return VadResult(
            is_speech=is_speech,
            rms=rms,
            energy=energy,
            is_trigger=is_trigger,
        )

    def reset(self) -> None:
        """Reset hangover counters."""
        self._hangover_counter = 0


class WebRtcVad(VoiceActivityDetector):
    """WebRTC voice classifier with a short output hangover for fluent speech."""

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_ms: float = 20.0,
        mode: int = 2,
        hangover_frames: int = 4,
        min_rms: float = 0.0,
    ) -> None:
        if sample_rate not in {8000, 16000, 32000, 48000}:
            raise ValueError("WebRTC VAD requires 8/16/32/48 kHz audio")
        if int(frame_ms) not in {10, 20, 30} or frame_ms != int(frame_ms):
            raise ValueError("WebRTC VAD requires 10, 20, or 30 ms frames")
        if mode not in {0, 1, 2, 3}:
            raise ValueError("WebRTC VAD mode must be 0..3")
        if importlib.util.find_spec("webrtcvad") is None:
            raise RuntimeError("webrtcvad-wheels is not installed")

        webrtcvad = importlib.import_module("webrtcvad")

        self.sample_rate = sample_rate
        self.frame_ms = int(frame_ms)
        self.mode = mode
        self.hangover_frames = max(0, hangover_frames)
        self.min_rms = max(0.0, min(1.0, min_rms))
        self._vad = webrtcvad.Vad(mode)
        self._hangover_counter = 0

    def process_frame(self, frame: bytes) -> VadResult:
        rms = compute_pcm_rms(frame)
        energy = rms * rms
        is_trigger = bool(self._vad.is_speech(frame, self.sample_rate)) and rms >= self.min_rms

        if is_trigger:
            self._hangover_counter = self.hangover_frames
            is_speech = True
        elif self._hangover_counter > 0:
            self._hangover_counter -= 1
            is_speech = True
        else:
            is_speech = False

        return VadResult(
            is_speech=is_speech,
            rms=rms,
            energy=energy,
            is_trigger=is_trigger,
        )

    def reset(self) -> None:
        self._hangover_counter = 0


class UtteranceCollector:
    """Collects PCM frames into complete AudioSegments based on VAD activity.

    Handles:
    - Pre-roll circular buffer to prevent cutting off the onset of words.
    - Continuous speech accumulation.
    - Silence timeout (post-roll) before concluding an utterance.
    - Minimum speech duration validation (discarding short transient clicks).
    - Maximum utterance timeout (protecting against runaway recording).
    """

    def __init__(
        self,
        vad: VoiceActivityDetector | None = None,
        sample_rate: int = 16000,
        channels: int = 1,
        frame_ms: float = 20.0,
        min_speech_ms: float = 250.0,
        silence_timeout_ms: float = 700.0,
        max_utterance_seconds: float = 15.0,
        pre_roll_ms: float = 200.0,
        profile: VadProfile | str | None = None,
    ) -> None:
        self.vad = vad or EnergyVad()
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_ms = frame_ms

        if profile is not None:
            silence_timeout_ms, min_speech_ms, pre_roll_ms = get_vad_profile_timings(profile)

        self.min_speech_ms = min_speech_ms
        self.silence_timeout_ms = silence_timeout_ms
        self.max_utterance_seconds = max_utterance_seconds

        # Buffer configurations
        self._pre_roll_frame_count = max(1, int(pre_roll_ms / frame_ms))
        self._silence_frames_needed = max(1, int(silence_timeout_ms / frame_ms))
        self._min_speech_frames_needed = max(1, int(min_speech_ms / frame_ms))
        self._max_frames = int((max_utterance_seconds * 1000.0) / frame_ms)

        # Internal state
        self._pre_roll_buffer: deque[bytes] = deque(maxlen=self._pre_roll_frame_count)
        self._collected_frames: list[bytes] = []
        self._is_in_utterance = False
        self._speech_evidence_frames = 0
        self._consecutive_silence_frames = 0
        self._last_vad_result: VadResult | None = None

    @property
    def is_in_utterance(self) -> bool:
        """Return True if currently accumulating speech."""
        return self._is_in_utterance

    @property
    def last_vad_result(self) -> VadResult | None:
        """Return the VAD decision for the most recently processed frame."""
        return self._last_vad_result

    def process_frame(self, frame: bytes) -> tuple[AudioSegment | None, bool]:
        """Process a single PCM frame.

        Returns a tuple:
        - `segment`: Completed `AudioSegment` if an utterance just finished, or None.
        - `is_active_speech`: True if the current frame is considered active voice.
        """
        vad_res = self.vad.process_frame(frame)
        self._last_vad_result = vad_res

        if not self._is_in_utterance:
            # IDLE state: maintain pre-roll ring buffer
            self._pre_roll_buffer.append(frame)

            # A detector hangover may bridge short low-energy gaps in natural
            # speech, but only actual threshold crossings count toward the
            # minimum evidence required to start an utterance.
            is_start_evidence = (
                vad_res.is_trigger
                if vad_res.is_trigger is not None
                else vad_res.is_speech
            )
            if is_start_evidence:
                self._speech_evidence_frames += 1
                if self._speech_evidence_frames >= self._min_speech_frames_needed:
                    # Speech confirmed! Transition to active utterance
                    self._is_in_utterance = True
                    self._consecutive_silence_frames = 0
                    self._collected_frames = list(self._pre_roll_buffer)
            else:
                # Start evidence must be consecutive classifier positives.
                # Hangover bridges an existing utterance but cannot assemble
                # disconnected workshop noises into a new one.
                self._speech_evidence_frames = 0

            return None, self._is_in_utterance

        # Currently in active utterance
        self._collected_frames.append(frame)

        if vad_res.is_speech:
            self._consecutive_silence_frames = 0
        else:
            self._consecutive_silence_frames += 1

        # Check termination conditions:
        # 1. Sustained silence after speech
        # 2. Maximum utterance length reached
        is_silence_timeout = self._consecutive_silence_frames >= self._silence_frames_needed
        is_max_length_reached = len(self._collected_frames) >= self._max_frames

        if is_silence_timeout or is_max_length_reached:
            completed_segment = self._build_segment()
            self.reset()
            return completed_segment, False

        return None, True

    def _build_segment(self) -> AudioSegment:
        """Combine accumulated frames into an AudioSegment."""
        raw_pcm = b"".join(self._collected_frames)
        duration_ms = compute_pcm_duration_ms(
            data_len_bytes=len(raw_pcm),
            sample_rate=self.sample_rate,
            channels=self.channels,
        )
        return AudioSegment(
            data=raw_pcm,
            sample_rate=self.sample_rate,
            channels=self.channels,
            duration_ms=duration_ms,
        )

    def reset(self) -> None:
        """Reset utterance collector to initial state."""
        self._is_in_utterance = False
        self._speech_evidence_frames = 0
        self._consecutive_silence_frames = 0
        self._collected_frames.clear()
        self._pre_roll_buffer.clear()
        self._last_vad_result = None
        self.vad.reset()
