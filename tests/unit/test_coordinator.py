"""Unit tests for InteractionCoordinator baseline."""

from ailen.core.coordinator import InteractionCoordinator
from ailen.core.events import EventBus
from ailen.core.social import SocialEngine
from ailen.core.state import StateManager
from ailen.domain.enums import AssistantState, EventType, SocialMode
from ailen.domain.social import SocialAction
from ailen.vision.contracts import PresenceObservation


class MockClock:
    """Deterministic controllable clock for coordinator testing."""

    def __init__(self, initial_time: float = 1000.0) -> None:
        self.current = initial_time

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def test_coordinator_full_presence_lifecycle() -> None:
    clock = MockClock(1000.0)
    state_mgr = StateManager(initial_state=AssistantState.IDLE)
    social_engine = SocialEngine(default_cooldown_seconds=60.0)
    event_bus = EventBus(record_history=True)

    coordinator = InteractionCoordinator(
        state_manager=state_mgr,
        social_engine=social_engine,
        event_bus=event_bus,
        mode=SocialMode.WORKSHOP,
        clock=clock,
    )

    # 1. Initially IDLE
    assert state_mgr.current_state == AssistantState.IDLE

    # 2. Person appears
    obs_appear = PresenceObservation(
        present=True,
        faces_count=1,
        primary_x_normalized=0.2,
        primary_y_normalized=-0.1,
    )
    decision1 = coordinator.handle_presence_observation(obs_appear)

    # 3. Transitions to ATTENTION
    assert state_mgr.current_state == AssistantState.ATTENTION

    # 4. Social engine decided GREET
    assert decision1.action == SocialAction.GREET
    assert decision1.reason_code == "WORKSHOP_GREETING_ALLOWED"
    assert decision1.greeting_intent == "workshop_ack"

    # 5. Event PRESENCE_DETECTED published
    assert len(event_bus.history) == 1
    assert event_bus.history[0].event_type == EventType.PRESENCE_DETECTED
    assert event_bus.history[0].payload["decision_action"] == "GREET"

    # 6. Immediate second observation within cooldown -> does not greet again
    clock.advance(10.0)  # Only 10s elapsed
    obs_continuous = PresenceObservation(present=True, faces_count=1)
    decision2 = coordinator.handle_presence_observation(obs_continuous)

    assert decision2.action == SocialAction.LOOK_AT
    assert decision2.reason_code in ("ALREADY_GREETED_PRESENCE", "COOLDOWN_ACTIVE")
    assert state_mgr.current_state == AssistantState.ATTENTION
    assert [e.event_type for e in event_bus.history].count(EventType.PRESENCE_DETECTED) == 1

    # 7. Person leaves
    obs_leave = PresenceObservation(present=False, faces_count=0)
    decision3 = coordinator.handle_presence_observation(obs_leave)

    # 8. Transitions back to IDLE and publishes PRESENCE_LOST
    assert state_mgr.current_state == AssistantState.IDLE
    assert decision3.action == SocialAction.STAY_SILENT
    assert event_bus.history[-1].event_type == EventType.PRESENCE_LOST


def test_coordinator_handles_sleep_wake() -> None:
    clock = MockClock(1000.0)
    state_mgr = StateManager(initial_state=AssistantState.SLEEP)
    social_engine = SocialEngine()
    event_bus = EventBus()

    coordinator = InteractionCoordinator(
        state_manager=state_mgr,
        social_engine=social_engine,
        event_bus=event_bus,
        mode=SocialMode.HOME,
        clock=clock,
    )

    # First observation while sleeping wakes the assistant without greeting yet.
    obs = PresenceObservation(present=True, faces_count=1)
    first = coordinator.handle_presence_observation(obs)
    assert first.action == SocialAction.WAKE
    assert first.reason_code == "PRESENCE_WAKE"
    assert state_mgr.current_state == AssistantState.ATTENTION

    # Once awake, the same presence can be evaluated for a greeting.
    second = coordinator.handle_presence_observation(obs)
    assert second.action == SocialAction.GREET
    assert second.greeting_intent == "casual_greeting"


def test_coordinator_mode_update() -> None:
    state_mgr = StateManager(initial_state=AssistantState.IDLE)
    social_engine = SocialEngine()
    event_bus = EventBus()

    coordinator = InteractionCoordinator(
        state_manager=state_mgr,
        social_engine=social_engine,
        event_bus=event_bus,
        mode=SocialMode.HOME,
    )

    assert coordinator.mode == SocialMode.HOME
    coordinator.set_mode(SocialMode.SHOP)
    assert coordinator.mode == SocialMode.SHOP
