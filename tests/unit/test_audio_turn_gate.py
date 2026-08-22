"""Unit tests for Half-Duplex AudioTurnGate."""

from ailen.audio.turn_gate import AudioTurnGate, GateState


class ControllableClock:
    """Deterministic clock for turn gate testing."""

    def __init__(self, start: float = 100.0) -> None:
        self.time = start

    def __call__(self) -> float:
        return self.time

    def advance(self, dt: float) -> None:
        self.time += dt


def test_turn_gate_initial_state_allows_listening_even_at_clock_zero() -> None:
    clock = ControllableClock(0.0)
    gate = AudioTurnGate(settling_cooldown_seconds=0.2, clock=clock)
    assert gate.is_listening_allowed() is True


def test_turn_gate_initial_state_and_frame_pass() -> None:
    clock = ControllableClock(100.0)
    gate = AudioTurnGate(settling_cooldown_seconds=0.2, clock=clock)

    assert gate.state == GateState.LISTENING_ALLOWED
    assert gate.is_listening_allowed() is True

    frame = b"\x01\x02\x03\x04"
    assert gate.filter_frame(frame) == frame
    assert gate.filter_frame(None) is None


def test_turn_gate_blocks_during_speech() -> None:
    clock = ControllableClock(100.0)
    gate = AudioTurnGate(settling_cooldown_seconds=0.2, clock=clock)

    # Start speaking
    gate.start_speaking()
    assert gate.state == GateState.SPEAKING_BLOCKED
    assert gate.is_listening_allowed() is False

    frame = b"\x01\x02\x03\x04"
    # While speaking, frames are rejected
    assert gate.filter_frame(frame) is None


def test_turn_gate_settling_cooldown_after_speech() -> None:
    clock = ControllableClock(100.0)
    gate = AudioTurnGate(settling_cooldown_seconds=0.2, clock=clock)

    gate.start_speaking()
    clock.advance(1.5)  # Speaking for 1.5s
    gate.stop_speaking()

    # Immediately after stop (0.0s elapsed into 0.2s cooldown): still blocked
    assert gate.state == GateState.LISTENING_ALLOWED
    assert gate.is_listening_allowed() is False
    assert gate.filter_frame(b"audio") is None

    # Advance 0.1s (< 0.2s cooldown): still blocked
    clock.advance(0.1)
    assert gate.is_listening_allowed() is False

    # Advance past 0.2s cooldown (total 0.25s since stop): unblocked!
    clock.advance(0.15)
    assert gate.is_listening_allowed() is True
    assert gate.filter_frame(b"audio") == b"audio"


def test_turn_gate_processing_and_speaking_blockers_are_nested() -> None:
    clock = ControllableClock(100.0)
    gate = AudioTurnGate(settling_cooldown_seconds=0.2, clock=clock)

    gate.start_processing()
    assert gate.is_listening_allowed() is False

    gate.start_speaking()
    gate.stop_speaking()
    assert gate.is_listening_allowed() is False  # processing still owns the gate

    gate.stop_processing()
    assert gate.is_listening_allowed() is False  # settling cooldown
    clock.advance(0.21)
    assert gate.is_listening_allowed() is True
