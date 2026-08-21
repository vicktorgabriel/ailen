"""Unit tests for VisionDebouncer temporal presence filtering."""

import pytest

from ailen.vision.contracts import PresenceObservation
from ailen.vision.debouncer import VisionDebouncer


class ControllableClock:
    """Controllable clock for debouncer tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.current = start

    def __call__(self) -> float:
        return self.current

    def advance(self, dt: float) -> None:
        self.current += dt


def test_debouncer_confirms_presence_after_threshold() -> None:
    clock = ControllableClock(0.0)
    debouncer = VisionDebouncer(debounce_seconds=2.0, clock=clock)

    # Initial state: absent
    assert debouncer.stable_presence is False

    # Raw presence appears at t=0.0
    raw_seen = PresenceObservation(present=True, faces_count=1, primary_x_normalized=0.3, primary_y_normalized=0.1)
    obs1 = debouncer.update(raw_seen)
    # At t=0.0 (< 2.0s elapsed), stable presence remains False
    assert obs1.present is False
    assert debouncer.stable_presence is False

    # Advance clock to 1.5s (< 2.0s)
    clock.advance(1.5)
    obs2 = debouncer.update(raw_seen)
    assert obs2.present is False
    assert debouncer.stable_presence is False

    # Advance clock to 2.1s (>= 2.0s)
    clock.advance(0.6)
    obs3 = debouncer.update(raw_seen)
    # Debounce window satisfied -> stable presence is confirmed!
    assert obs3.present is True
    assert debouncer.stable_presence is True
    assert obs3.primary_x_normalized == 0.3


def test_debouncer_rejects_single_frame_flicker() -> None:
    clock = ControllableClock(0.0)
    debouncer = VisionDebouncer(debounce_seconds=2.0, clock=clock)

    # False positive flicker: 1 frame of presence at t=0.0
    raw_flicker = PresenceObservation(present=True, faces_count=1)
    debouncer.update(raw_flicker)
    assert debouncer.stable_presence is False

    # Immediate drop back to absence at t=0.1s
    clock.advance(0.1)
    raw_absent = PresenceObservation(present=False)
    debouncer.update(raw_absent)
    assert debouncer.stable_presence is False

    # Advance past 2.0s: still absent
    clock.advance(2.5)
    obs = debouncer.update(raw_absent)
    assert obs.present is False
    assert debouncer.stable_presence is False


def test_debouncer_loss_debounce() -> None:
    clock = ControllableClock(0.0)
    debouncer = VisionDebouncer(debounce_seconds=2.0, clock=clock)

    # Establish stable presence
    raw_present = PresenceObservation(present=True, faces_count=1)
    debouncer.update(raw_present)
    clock.advance(2.1)
    debouncer.update(raw_present)
    assert debouncer.stable_presence is True

    # Person momentarily lost (e.g. 0.5s dropout)
    raw_absent = PresenceObservation(present=False)
    clock.advance(0.5)
    debouncer.update(raw_absent)
    # Still considered stably present during dropout (< 2.0s)
    assert debouncer.stable_presence is True

    # Person reappears at t=0.8s: stable presence was never broken
    clock.advance(0.3)
    debouncer.update(raw_present)
    assert debouncer.stable_presence is True

    # Person permanently leaves
    clock.advance(0.1)
    debouncer.update(raw_absent)
    assert debouncer.stable_presence is True

    # After 2.0s of continuous absence, presence is confirmed lost
    clock.advance(2.1)
    final_obs = debouncer.update(raw_absent)
    assert final_obs.present is False
    assert debouncer.stable_presence is False


def test_debouncer_real_time_coordinate_tracking_while_present() -> None:
    clock = ControllableClock(0.0)
    debouncer = VisionDebouncer(debounce_seconds=1.0, clock=clock)

    # Establish stable presence
    raw1 = PresenceObservation(present=True, primary_x_normalized=0.1, primary_y_normalized=0.2)
    debouncer.update(raw1)
    clock.advance(1.2)
    stable1 = debouncer.update(raw1)
    assert stable1.present is True
    assert stable1.primary_x_normalized == 0.1

    # While stable presence is active, coordinates update immediately on every frame
    clock.advance(0.1)
    raw2 = PresenceObservation(present=True, primary_x_normalized=0.7, primary_y_normalized=-0.4)
    stable2 = debouncer.update(raw2)
    assert stable2.present is True
    assert stable2.primary_x_normalized == 0.7
    assert stable2.primary_y_normalized == -0.4


def test_debouncer_rejects_negative_window() -> None:
    with pytest.raises(ValueError):
        VisionDebouncer(debounce_seconds=-0.01)


def test_debouncer_reset() -> None:
    clock = ControllableClock(0.0)
    debouncer = VisionDebouncer(debounce_seconds=1.0, clock=clock)

    raw = PresenceObservation(present=True)
    debouncer.update(raw)
    clock.advance(1.5)
    debouncer.update(raw)
    assert debouncer.stable_presence is True

    debouncer.reset()
    assert debouncer.stable_presence is False
    assert debouncer.latest_raw is None
