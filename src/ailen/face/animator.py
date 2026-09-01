"""Deterministic face animator and pose generator for AILEN.

Computes visual eye, pupil, gaze, blink, mouth, and expression parameters
from assistant states, presence observations, and speech levels without coupling
to any graphical library.
"""

import math
import random
import time
from collections.abc import Callable

from ailen.domain.enums import AssistantState
from ailen.face.contracts import FACE_EXPRESSIONS
from ailen.face.models import FacePose


class FaceAnimator:
    """Computes smooth, natural facial poses based on interaction state.
    
    Features:
    - Non-periodic, natural pseudo-random blinking with jitter.
    - Target gaze tracking with smooth exponential interpolation.
    - Subtle micro-saccades and idle eye movements.
    - Dynamic mouth opening driven by speech energy levels.
    - Deterministic testing support via injectable clock and PRNG seed.
    """

    SUPPORTED_EXPRESSIONS = FACE_EXPRESSIONS

    def __init__(
        self,
        clock: Callable[[], float] | None = None,
        rng: random.Random | None = None,
        gaze_smoothing_speed: float = 8.0,
    ):
        self._clock = clock or time.monotonic
        # Producción: semilla no fija para que distintas instancias/arranques no
        # parpadeen con el mismo patrón. Tests pueden inyectar random.Random(seed).
        self._rng = rng or random.Random()
        self._gaze_smoothing_speed = gaze_smoothing_speed

        self._state: AssistantState = AssistantState.IDLE
        self._state_expression: str = "neutral"
        self._expression_override: str | None = None
        self._expression_expires_at: float | None = None
        self._speech_level: float = 0.0
        self._speech_started_at: float | None = None

        # Gaze targets and current smoothed values
        self._target_gaze_x: float = 0.0
        self._target_gaze_y: float = 0.0
        self._curr_gaze_x: float = 0.0
        self._curr_gaze_y: float = 0.0

        # Blink state
        self._last_blink_time: float = self._now()
        self._next_blink_interval: float = self._schedule_next_blink_interval()
        self._blink_duration: float = 0.18  # ~180 ms for full blink cycle

        self._last_update_time: float = self._now()

    def _now(self) -> float:
        return self._clock()

    @property
    def state(self) -> AssistantState:
        """Current interaction state used by the animator."""
        return self._state

    @property
    def speech_level(self) -> float:
        """Current normalized speech/mouth energy level."""
        return self._speech_level

    def _schedule_next_blink_interval(self) -> float:
        """Schedule next blink interval between 3.0 and 6.0 seconds."""
        return self._rng.uniform(3.0, 6.0)

    # -------------------------------------------------------------------------
    # Control Inputs
    # -------------------------------------------------------------------------

    def set_state(self, state: AssistantState) -> None:
        """Set interaction state and its canonical visual expression."""
        self._state = state
        expression_by_state = {
            AssistantState.BOOTING: "booting",
            AssistantState.IDLE: "neutral",
            AssistantState.ATTENTION: "attentive",
            AssistantState.LISTENING: "listening",
            AssistantState.PROCESSING: "thinking",
            AssistantState.TOOL: "working",
            AssistantState.SPEAKING: "speaking",
            AssistantState.SLEEP: "sleep",
            AssistantState.ERROR: "error",
            AssistantState.DEGRADED: "degraded",
        }
        self._state_expression = expression_by_state[state]
        if state in {
            AssistantState.BOOTING,
            AssistantState.SLEEP,
            AssistantState.ERROR,
            AssistantState.DEGRADED,
        }:
            self._expression_override = None
            self._expression_expires_at = None

    def set_gaze(self, x: float, y: float) -> None:
        """Set the target gaze coordinates normalized to [-1.0, 1.0]."""
        self._target_gaze_x = max(-1.0, min(1.0, x))
        self._target_gaze_y = max(-1.0, min(1.0, y))

    def set_speech_level(self, level: float) -> None:
        """Set current speech synthesis energy / mouth openness [0.0, 1.0]."""
        bounded = max(0.0, min(1.0, level))
        if bounded > 0.0 and self._speech_level <= 0.0:
            self._speech_started_at = self._now()
        elif bounded <= 0.0:
            self._speech_started_at = None
        self._speech_level = bounded

    def set_expression(self, expression: str, duration_seconds: float = 0.0) -> None:
        """Apply one bounded transient gesture without replacing interaction state."""
        clean = expression.strip().lower()
        if clean not in self.SUPPORTED_EXPRESSIONS:
            raise ValueError(f"unsupported face expression: {clean}")
        effective_duration = 5.0 if duration_seconds <= 0.0 else duration_seconds
        if not 0.5 <= effective_duration <= 10.0:
            raise ValueError("expression duration must be 0 (renderer default) or 0.5..10 seconds")
        self._expression_override = clean
        self._expression_expires_at = self._now() + effective_duration

    def sleep(self) -> None:
        """Put the face into sleep state."""
        self.set_state(AssistantState.SLEEP)

    def wake(self) -> None:
        """Wake the face from sleep."""
        self.set_state(AssistantState.IDLE)
        self._state_expression = "waking"

    def _effective_expression(self, now: float) -> str:
        """Resolve a transient gesture over state and expire it deterministically."""
        if (
            self._expression_override is not None
            and self._expression_expires_at is not None
            and now >= self._expression_expires_at
        ):
            self._expression_override = None
            self._expression_expires_at = None
        return self._expression_override or self._state_expression

    # -------------------------------------------------------------------------
    # Pose Computation / Update Loop
    # -------------------------------------------------------------------------

    def step(self, current_time: float | None = None) -> FacePose:
        """Update animation state and compute current FacePose."""
        now = current_time if current_time is not None else self._now()
        dt = max(0.0, now - self._last_update_time)
        self._last_update_time = now
        expression = self._effective_expression(now)

        # 1. Smooth gaze interpolation
        lerp_factor = min(1.0, dt * self._gaze_smoothing_speed) if dt > 0 else 0.0
        self._curr_gaze_x += (self._target_gaze_x - self._curr_gaze_x) * lerp_factor
        self._curr_gaze_y += (self._target_gaze_y - self._curr_gaze_y) * lerp_factor

        # 2. Sleeping state: eyes closed, no blinks, static
        if self._state == AssistantState.SLEEP or expression == "sleep":
            return FacePose(
                gaze_x=0.0,
                gaze_y=-0.2,
                left_eye_open=0.0,
                right_eye_open=0.0,
                pupil_size=0.3,
                mouth_open=0.0,
                mouth_width=0.4,
                expression="sleep",
                blink_progress=1.0,
                head_tilt=0.0,
                timestamp=now,
            )

        # 3. Blink computation
        blink_progress = 0.0
        time_since_blink = now - self._last_blink_time
        if time_since_blink >= self._next_blink_interval:
            blink_elapsed = time_since_blink - self._next_blink_interval
            if blink_elapsed <= self._blink_duration:
                # Half cosine wave for smooth close and open: 0 -> 1 -> 0
                phase = (blink_elapsed / self._blink_duration) * math.pi
                blink_progress = math.sin(phase)
            else:
                # Blink completed, schedule next
                self._last_blink_time = now
                self._next_blink_interval = self._schedule_next_blink_interval()

        # 4. Eye aperture based on state
        base_eye_open = 0.85
        pupil_size = 0.5
        mouth_width = 0.5
        head_tilt = 0.0

        if self._state == AssistantState.ATTENTION:
            base_eye_open = 0.95
            pupil_size = 0.6
        elif self._state == AssistantState.LISTENING:
            base_eye_open = 0.90
            pupil_size = 0.55
            head_tilt = 0.05
        elif self._state == AssistantState.PROCESSING:
            base_eye_open = 0.80
            pupil_size = 0.5
            head_tilt = -0.05
        elif self._state == AssistantState.ERROR:
            base_eye_open = 0.65
            mouth_width = 0.35
        elif self._state == AssistantState.DEGRADED:
            base_eye_open = 0.75
            mouth_width = 0.40

        expression_mouth_open = 0.0
        if expression == "happy":
            base_eye_open = 0.72
            pupil_size = 0.58
            mouth_width = 0.82
        elif expression == "curious":
            base_eye_open = 0.92
            pupil_size = 0.62
            head_tilt = 0.10
        elif expression == "surprised":
            base_eye_open = 1.0
            pupil_size = 0.68
            mouth_width = 0.42
            expression_mouth_open = 0.32
        elif expression == "confused":
            base_eye_open = 0.76
            pupil_size = 0.46
            mouth_width = 0.42
            head_tilt = -0.12
        elif expression == "focused":
            base_eye_open = 0.78
            pupil_size = 0.44
            mouth_width = 0.40

        elif expression == "sad":
            base_eye_open = 0.68
            pupil_size = 0.48
            mouth_width = 0.44
            head_tilt = -0.06
        elif expression == "skeptical":
            base_eye_open = 0.82
            pupil_size = 0.45
            mouth_width = 0.46
            head_tilt = -0.08
        elif expression == "excited":
            base_eye_open = 1.0
            pupil_size = 0.72
            mouth_width = 0.88
            expression_mouth_open = 0.22
            head_tilt = 0.06
        elif expression == "playful":
            base_eye_open = 0.84
            pupil_size = 0.62
            mouth_width = 0.74
            head_tilt = 0.12

        # Piper currently exposes one energy estimate per synthesized chunk.
        # Turn that bounded intensity into a deterministic articulation carrier
        # so the mouth keeps moving throughout playback without coupling Face
        # to PCM buffers, aplay, or the TTS backend.
        mouth_open = expression_mouth_open
        speech_elapsed = 0.0
        if self._speech_level > 0.0:
            speech_started_at = self._speech_started_at or now
            speech_elapsed = max(0.0, now - speech_started_at)
            syllable = 0.5 + 0.5 * math.sin(speech_elapsed * math.tau * 4.1)
            consonant = 0.5 + 0.5 * math.sin(
                speech_elapsed * math.tau * 7.3 + 0.8
            )
            articulation = 0.72 * syllable + 0.28 * consonant
            # The coordinator now updates speech_level from the real playback PCM
            # envelope. Keep only a subtle carrier here so phonetic motion remains
            # lively without overriding real pauses and energy changes.
            carrier = 0.78 + 0.22 * articulation
            gesture_energy = {
                "sad": 0.45,
                "focused": 0.62,
                "skeptical": 0.78,
                "confused": 0.88,
                "neutral": 1.00,
                "curious": 1.16,
                "happy": 1.28,
                "surprised": 1.38,
                "playful": 1.48,
                "excited": 1.62,
            }.get(expression, 1.0)
            mouth_open = 0.04 + 0.86 * self._speech_level * carrier
            mouth_width += 0.05 * gesture_energy * self._speech_level * math.sin(
                speech_elapsed * math.tau * (2.1 + 0.25 * gesture_energy) + 0.4
            )
            head_tilt += 0.045 * gesture_energy * math.sin(
                speech_elapsed * math.tau * (0.62 + 0.12 * gesture_energy)
            )
            base_eye_open += 0.025 * gesture_energy * math.sin(
                speech_elapsed * math.tau * (1.0 + 0.2 * gesture_energy)
            )
            pupil_size += 0.018 * gesture_energy * math.sin(
                speech_elapsed * math.tau * (1.45 + 0.2 * gesture_energy)
            )

        # Apply blink occlusion: eye_open decreases towards 0.0 as blink_progress increases
        eye_open = max(0.0, base_eye_open * (1.0 - blink_progress))
        left_eye_open = eye_open
        right_eye_open = eye_open
        if expression == "wink" and blink_progress < 0.15:
            left_eye_open = 0.04
            right_eye_open = max(right_eye_open, 0.85)
        elif expression == "skeptical":
            left_eye_open *= 0.62
            right_eye_open = min(1.0, right_eye_open * 1.08)
        elif expression == "playful":
            left_eye_open = min(1.0, left_eye_open * 1.06)
            right_eye_open *= 0.84

        # 6. Micro-saccades / subtle variation (when idle or listening)
        effective_gaze_x = self._curr_gaze_x
        effective_gaze_y = self._curr_gaze_y
        if self._state in (
            AssistantState.IDLE,
            AssistantState.LISTENING,
            AssistantState.SPEAKING,
        ):
            # Very gentle low-frequency micro wobble
            effective_gaze_x += 0.015 * math.sin(now * 0.8)
            effective_gaze_y += 0.010 * math.cos(now * 0.6)
        if self._speech_level > 0.0:
            effective_gaze_x += 0.018 * math.sin(speech_elapsed * math.tau * 0.9)
            effective_gaze_y += 0.012 * math.cos(speech_elapsed * math.tau * 1.1)

        return FacePose(
            gaze_x=max(-1.0, min(1.0, effective_gaze_x)),
            gaze_y=max(-1.0, min(1.0, effective_gaze_y)),
            left_eye_open=left_eye_open,
            right_eye_open=right_eye_open,
            pupil_size=max(0.0, min(1.0, pupil_size)),
            mouth_open=max(0.0, min(1.0, mouth_open)),
            mouth_width=max(0.0, min(1.0, mouth_width)),
            expression=expression,
            blink_progress=blink_progress,
            head_tilt=max(-1.0, min(1.0, head_tilt)),
            timestamp=now,
        )
