"""Temporal debouncer for presence observations.

Filters out transient frame flickers, short dropouts, and single-frame false positives
using configurable presence_debounce_seconds.
"""

import time
from collections.abc import Callable

from ailen.vision.contracts import PresenceObservation


class VisionDebouncer:
    """Temporal presence debouncer separating raw observations from stable state.
    
    Prevents flapping between presence and absence during camera capture.
    """

    def __init__(
        self,
        debounce_seconds: float = 2.0,
        clock: Callable[[], float] | None = None,
    ):
        if debounce_seconds < 0:
            raise ValueError("debounce_seconds must be >= 0")
        self.debounce_seconds = debounce_seconds
        self._clock = clock or time.monotonic
        self._stable_observation = PresenceObservation(present=False)
        self._latest_raw: PresenceObservation | None = None
        self._candidate_presence: bool = False
        self._candidate_start_time: float | None = None

    def _now(self) -> float:
        return self._clock()

    @property
    def stable_presence(self) -> bool:
        """Return True if stable debounced presence is confirmed."""
        return self._stable_observation.present

    @property
    def latest_stable(self) -> PresenceObservation:
        """Return the current stable debounced observation."""
        return self._stable_observation

    @property
    def latest_raw(self) -> PresenceObservation | None:
        """Return the most recent raw instantaneous observation."""
        return self._latest_raw

    def reset(self) -> None:
        """Reset debouncer state to absent."""
        self._stable_observation = PresenceObservation(present=False)
        self._latest_raw = None
        self._candidate_presence = False
        self._candidate_start_time = None

    def update(
        self,
        raw_obs: PresenceObservation,
        current_time: float | None = None,
    ) -> PresenceObservation:
        """Process a raw presence observation and return the updated stable observation."""
        now = current_time if current_time is not None else self._now()
        self._latest_raw = raw_obs

        # Case 1: Raw presence disagrees with stable presence
        if raw_obs.present != self._stable_observation.present:
            # Check if this is a new candidate state or continuing candidate
            if self._candidate_presence != raw_obs.present or self._candidate_start_time is None:
                self._candidate_presence = raw_obs.present
                self._candidate_start_time = now

            elapsed = now - self._candidate_start_time
            if elapsed >= self.debounce_seconds:
                # Debounce duration satisfied -> update stable presence state
                self._stable_observation = PresenceObservation(
                    present=raw_obs.present,
                    faces_count=raw_obs.faces_count,
                    primary_x_normalized=raw_obs.primary_x_normalized,
                    primary_y_normalized=raw_obs.primary_y_normalized,
                    confidence=raw_obs.confidence,
                    timestamp=raw_obs.timestamp,
                )
                self._candidate_start_time = None
        else:
            # Case 2: Raw presence agrees with stable state -> reset any candidate timer
            self._candidate_start_time = None
            self._candidate_presence = raw_obs.present

            # If currently present, track continuous coordinates and count in real time
            if self._stable_observation.present and raw_obs.present:
                self._stable_observation = PresenceObservation(
                    present=True,
                    faces_count=raw_obs.faces_count,
                    primary_x_normalized=raw_obs.primary_x_normalized,
                    primary_y_normalized=raw_obs.primary_y_normalized,
                    confidence=raw_obs.confidence,
                    timestamp=raw_obs.timestamp,
                )

        return self._stable_observation
