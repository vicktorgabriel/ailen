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
        self._expression: str = "neutral"
        self._speech_level: float = 0.0

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
        self._expression = expression_by_state[state]

    def set_gaze(self, x: float, y: float) -> None:
        """Set the target gaze coordinates normalized to [-1.0, 1.0]."""
        self._target_gaze_x = max(-1.0, min(1.0, x))
        self._target_gaze_y = max(-1.0, min(1.0, y))

    def set_speech_level(self, level: float) -> None:
        """Set current speech synthesis energy / mouth openness [0.0, 1.0]."""
        self._speech_level = max(0.0, min(1.0, level))

    def set_expression(self, expression: str) -> None:
        """Set a named expression hint."""
        self._expression = expression

    def sleep(self) -> None:
        """Put the face into sleep state."""
        self.set_state(AssistantState.SLEEP)

    def wake(self) -> None:
        """Wake the face from sleep."""
        self.set_state(AssistantState.IDLE)
        self._expression = "waking"

    # -------------------------------------------------------------------------
    # Pose Computation / Update Loop
    # -------------------------------------------------------------------------

    def step(self, current_time: float | None = None) -> FacePose:
        """Update animation state and compute current FacePose."""
        now = current_time if current_time is not None else self._now()
        dt = max(0.0, now - self._last_update_time)
        self._last_update_time = now

        # 1. Smooth gaze interpolation
        lerp_factor = min(1.0, dt * self._gaze_smoothing_speed) if dt > 0 else 0.0
        self._curr_gaze_x += (self._target_gaze_x - self._curr_gaze_x) * lerp_factor
        self._curr_gaze_y += (self._target_gaze_y - self._curr_gaze_y) * lerp_factor

        # 2. Sleeping state: eyes closed, no blinks, static
        if self._state == AssistantState.SLEEP or self._expression == "sleep":
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

        # Apply blink occlusion: eye_open decreases towards 0.0 as blink_progress increases
        eye_open = max(0.0, base_eye_open * (1.0 - blink_progress))

        # 5. Mouth aperture (driven by speech level when speaking or explicitly set)
        mouth_open = 0.0
        if self._state == AssistantState.SPEAKING or self._speech_level > 0.0:
            mouth_open = self._speech_level

        # 6. Micro-saccades / subtle variation (when idle or listening)
        effective_gaze_x = self._curr_gaze_x
        effective_gaze_y = self._curr_gaze_y
        if self._state in (AssistantState.IDLE, AssistantState.LISTENING):
            # Very gentle low-frequency micro wobble
            effective_gaze_x += 0.015 * math.sin(now * 0.8)
            effective_gaze_y += 0.010 * math.cos(now * 0.6)

        return FacePose(
            gaze_x=max(-1.0, min(1.0, effective_gaze_x)),
            gaze_y=max(-1.0, min(1.0, effective_gaze_y)),
            left_eye_open=eye_open,
            right_eye_open=eye_open,
            pupil_size=pupil_size,
            mouth_open=max(0.0, min(1.0, mouth_open)),
            mouth_width=mouth_width,
            expression=self._expression,
            blink_progress=blink_progress,
            head_tilt=head_tilt,
            timestamp=now,
        )
