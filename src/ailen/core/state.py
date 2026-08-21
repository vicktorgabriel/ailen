"""Assistant interaction state machine for AILEN."""

import logging
from collections.abc import Callable

from ailen.domain.enums import AssistantState, EventType
from ailen.domain.models import CoreEvent

logger = logging.getLogger("ailen.core.state")

# Allowed state transitions
VALID_TRANSITIONS: dict[AssistantState, set[AssistantState]] = {
    AssistantState.BOOTING: {
        AssistantState.IDLE,
        AssistantState.ERROR,
        AssistantState.DEGRADED,
    },
    AssistantState.IDLE: {
        AssistantState.ATTENTION,
        AssistantState.LISTENING,
        AssistantState.SPEAKING,
        AssistantState.SLEEP,
        AssistantState.ERROR,
        AssistantState.DEGRADED,
    },
    AssistantState.ATTENTION: {
        AssistantState.IDLE,
        AssistantState.LISTENING,
        AssistantState.PROCESSING,
        AssistantState.SPEAKING,
        AssistantState.SLEEP,
        AssistantState.ERROR,
    },
    AssistantState.LISTENING: {
        AssistantState.PROCESSING,
        AssistantState.IDLE,
        AssistantState.ATTENTION,
        AssistantState.ERROR,
    },
    AssistantState.PROCESSING: {
        AssistantState.TOOL,
        AssistantState.SPEAKING,
        AssistantState.IDLE,
        AssistantState.ERROR,
    },
    AssistantState.TOOL: {
        AssistantState.PROCESSING,
        AssistantState.SPEAKING,
        AssistantState.IDLE,
        AssistantState.ERROR,
    },
    AssistantState.SPEAKING: {
        AssistantState.IDLE,
        AssistantState.ATTENTION,
        AssistantState.LISTENING,
        AssistantState.ERROR,
    },
    AssistantState.SLEEP: {
        AssistantState.IDLE,
        AssistantState.ATTENTION,
        AssistantState.ERROR,
    },
    AssistantState.ERROR: {
        AssistantState.BOOTING,
        AssistantState.IDLE,
        AssistantState.DEGRADED,
        AssistantState.SLEEP,
    },
    AssistantState.DEGRADED: {
        AssistantState.IDLE,
        AssistantState.ATTENTION,
        AssistantState.LISTENING,
        AssistantState.ERROR,
        AssistantState.SLEEP,
    },
}


class StateManager:
    """Manages assistant interaction state transitions and event emission."""

    def __init__(self, initial_state: AssistantState = AssistantState.BOOTING):
        self._current_state = initial_state
        self._listeners: list[Callable[[AssistantState, AssistantState], None]] = []

    @property
    def current_state(self) -> AssistantState:
        """Return the current assistant state."""
        return self._current_state

    def add_listener(self, listener: Callable[[AssistantState, AssistantState], None]) -> None:
        """Register a callback for state change notifications."""
        self._listeners.append(listener)

    def transition_to(self, new_state: AssistantState, reason: str | None = None) -> bool:
        """Attempt to transition to a new state. Returns True if transition succeeded."""
        if new_state == self._current_state:
            return True

        valid_targets = VALID_TRANSITIONS.get(self._current_state, set())
        if new_state not in valid_targets:
            logger.warning(
                "Invalid state transition attempted: %s -> %s (reason: %s)",
                self._current_state.value,
                new_state.value,
                reason or "none",
            )
            return False

        old_state = self._current_state
        self._current_state = new_state
        logger.info(
            "State changed: %s -> %s (reason: %s)",
            old_state.value,
            new_state.value,
            reason or "none",
        )

        for listener in self._listeners:
            try:
                listener(old_state, new_state)
            except Exception:
                logger.exception("Error in state change listener")

        return True

    def create_event(self, event_id: str, event_type: EventType, payload: dict) -> CoreEvent:
        """Create a standard CoreEvent."""
        return CoreEvent(
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            source="state_manager",
        )
