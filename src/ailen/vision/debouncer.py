"""Temporal hysteresis for noisy presence observations."""

import time
from collections.abc import Callable

from ailen.vision.contracts import PresenceObservation


class VisionDebouncer:
    """Convert noisy frame-level detections into stable presence state.

    Legacy callers can keep using ``debounce_seconds`` symmetrically. Physical
    runtimes may opt into faster presence acquisition plus a short dropout grace
    while retaining a longer absence confirmation window.
    """

    def __init__(
        self,
        debounce_seconds: float = 2.0,
        clock: Callable[[], float] | None = None,
        *,
        presence_confirm_seconds: float | None = None,
        absence_confirm_seconds: float | None = None,
        dropout_grace_seconds: float = 0.0,
    ) -> None:
        if debounce_seconds < 0:
            raise ValueError("debounce_seconds must be >= 0")
        self.presence_confirm_seconds = (
            debounce_seconds if presence_confirm_seconds is None else presence_confirm_seconds
        )
        self.absence_confirm_seconds = (
            debounce_seconds if absence_confirm_seconds is None else absence_confirm_seconds
        )
        if self.presence_confirm_seconds < 0 or self.absence_confirm_seconds < 0:
            raise ValueError("presence/absence confirmation windows must be >= 0")
        if dropout_grace_seconds < 0:
            raise ValueError("dropout_grace_seconds must be >= 0")

        self.debounce_seconds = debounce_seconds
        self.dropout_grace_seconds = dropout_grace_seconds
        self._clock = clock or time.monotonic
        self._stable_observation = PresenceObservation(present=False)
        self._latest_raw: PresenceObservation | None = None
        self._candidate_presence = False
        self._candidate_start_time: float | None = None
        self._last_positive_time: float | None = None

    def _now(self) -> float:
        return self._clock()

    @property
    def stable_presence(self) -> bool:
        return self._stable_observation.present

    @property
    def latest_stable(self) -> PresenceObservation:
        return self._stable_observation

    @property
    def latest_raw(self) -> PresenceObservation | None:
        return self._latest_raw

    def reset(self) -> None:
        self._stable_observation = PresenceObservation(present=False)
        self._latest_raw = None
        self._candidate_presence = False
        self._candidate_start_time = None
        self._last_positive_time = None

    @staticmethod
    def _copy_observation(obs: PresenceObservation, *, present: bool | None = None) -> PresenceObservation:
        return PresenceObservation(
            present=obs.present if present is None else present,
            faces_count=obs.faces_count if (present is None or present) else 0,
            primary_x_normalized=obs.primary_x_normalized if (present is None or present) else None,
            primary_y_normalized=obs.primary_y_normalized if (present is None or present) else None,
            confidence=obs.confidence if (present is None or present) else None,
            timestamp=obs.timestamp,
        )

    def update(
        self,
        raw_obs: PresenceObservation,
        current_time: float | None = None,
    ) -> PresenceObservation:
        """Update stable presence with asymmetric confirmation and dropout grace."""
        now = current_time if current_time is not None else self._now()
        self._latest_raw = raw_obs

        if not self._stable_observation.present:
            if raw_obs.present:
                if self._candidate_start_time is None or not self._candidate_presence:
                    self._candidate_presence = True
                    self._candidate_start_time = now
                self._last_positive_time = now
                if now - self._candidate_start_time >= self.presence_confirm_seconds:
                    self._stable_observation = self._copy_observation(raw_obs, present=True)
                    self._candidate_start_time = None
                    self._candidate_presence = True
                return self._stable_observation

            # A short detector miss does not erase an in-progress presence
            # candidate. This is essential for lightweight Haar detectors.
            if (
                self._candidate_presence
                and self._candidate_start_time is not None
                and self._last_positive_time is not None
                and now - self._last_positive_time <= self.dropout_grace_seconds
            ):
                return self._stable_observation

            self._candidate_presence = False
            self._candidate_start_time = None
            self._last_positive_time = None
            return self._stable_observation

        # Stable present: positive frames update gaze immediately.
        if raw_obs.present:
            self._stable_observation = self._copy_observation(raw_obs, present=True)
            self._candidate_presence = True
            self._candidate_start_time = None
            self._last_positive_time = now
            return self._stable_observation

        # Stable present -> absence requires a continuous absence window.
        if self._candidate_presence or self._candidate_start_time is None:
            self._candidate_presence = False
            self._candidate_start_time = now

        if now - self._candidate_start_time >= self.absence_confirm_seconds:
            self._stable_observation = self._copy_observation(raw_obs, present=False)
            self._candidate_start_time = None
            self._last_positive_time = None

        return self._stable_observation
