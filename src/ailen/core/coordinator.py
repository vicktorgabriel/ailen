"""Interaction Coordinator baseline for AILEN.

Coordinates presence observations, StateManager transitions, SocialEngine decisions,
EventBus event publications, and FaceController reactions without coupling to hardware or real STT/TTS.
"""

import logging
import time
from collections.abc import Callable

from ailen.core.events import EventBus
from ailen.core.social import SocialEngine
from ailen.core.state import StateManager
from ailen.domain.enums import AssistantState, EventType, SocialMode
from ailen.domain.social import SocialAction, SocialContext, SocialDecision
from ailen.face.contracts import FaceController
from ailen.vision.contracts import PresenceObservation
from ailen.vision.debouncer import VisionDebouncer

logger = logging.getLogger("ailen.core.coordinator")


class InteractionCoordinator:
    """Orchestrates presence input, assistant state machine, social decisions, and face animations."""

    def __init__(
        self,
        state_manager: StateManager,
        social_engine: SocialEngine,
        event_bus: EventBus,
        mode: SocialMode = SocialMode.WORKSHOP,
        face_controller: FaceController | None = None,
        debouncer: VisionDebouncer | None = None,
        clock: Callable[[], float] | None = None,
    ):
        self.state_manager = state_manager
        self.social_engine = social_engine
        self.event_bus = event_bus
        self.face_controller = face_controller
        self.debouncer = debouncer
        self._mode = mode
        self._clock = clock or time.monotonic
        self._current_presence: bool = False
        self._last_greeting_at: float | None = None
        self._presence_session_greeted: bool = False

    @property
    def mode(self) -> SocialMode:
        """Return current social operating mode."""
        return self._mode

    def set_mode(self, mode: SocialMode) -> None:
        """Update active social mode."""
        self._mode = mode

    def _now(self) -> float:
        """Return current timestamp from injected clock."""
        return self._clock()

    def handle_raw_presence_observation(self, raw_obs: PresenceObservation) -> SocialDecision:
        """Process a raw (undebounced) observation through the debouncer if configured."""
        if self.debouncer:
            stable_obs = self.debouncer.update(raw_obs, current_time=self._now())
            return self.handle_presence_observation(stable_obs)
        return self.handle_presence_observation(raw_obs)

    def handle_presence_observation(self, obs: PresenceObservation) -> SocialDecision:
        """Process a normalized presence observation and trigger appropriate state, events, and face updates."""
        current_time = self._now()

        if obs.present:
            # Detect new stable presence transition separately from greeting state.
            was_present = self._current_presence
            is_new = not was_present or not self._presence_session_greeted
            self._current_presence = True

            # Preserve the pre-transition sleep state so SocialEngine can emit WAKE.
            was_sleeping = self.state_manager.current_state == AssistantState.SLEEP
            if was_sleeping:
                self.state_manager.transition_to(AssistantState.ATTENTION, reason="presence_wake")
            elif self.state_manager.current_state == AssistantState.IDLE:
                self.state_manager.transition_to(AssistantState.ATTENTION, reason="presence_detected")

            # Check if busy in conversation/processing
            conv_active = self.state_manager.current_state in (
                AssistantState.LISTENING,
                AssistantState.PROCESSING,
                AssistantState.TOOL,
                AssistantState.SPEAKING,
            )

            ctx = SocialContext(
                mode=self._mode,
                presence_state=True,
                conversation_active=conv_active,
                last_greeting_at=self._last_greeting_at,
                current_time=current_time,
                people_count_estimate=obs.faces_count or 1,
                is_new_presence=is_new,
                sleep_state=was_sleeping,
                greeting_cooldown_seconds=self.social_engine.default_cooldown_seconds,
                gaze_x=obs.primary_x_normalized,
                gaze_y=obs.primary_y_normalized,
            )

            decision = self.social_engine.evaluate(ctx)

            # Record greeting cooldown and session greeting flag if greeting allowed
            if decision.action == SocialAction.GREET:
                self._last_greeting_at = current_time
                self._presence_session_greeted = True

            # Update Face controller if attached
            if self.face_controller:
                self.face_controller.set_state(self.state_manager.current_state)
                if obs.primary_x_normalized is not None and obs.primary_y_normalized is not None:
                    self.face_controller.set_gaze(obs.primary_x_normalized, obs.primary_y_normalized)
                if decision.expression_hint:
                    self.face_controller.set_expression(decision.expression_hint)

            # Presence events represent transitions, not every camera observation.
            if not was_present:
                self.event_bus.create_and_publish(
                    event_type=EventType.PRESENCE_DETECTED,
                    payload={
                        "present": True,
                        "faces_count": obs.faces_count,
                        "decision_action": decision.action.value,
                        "reason_code": decision.reason_code,
                        "greeting_intent": decision.greeting_intent,
                        "expression_hint": decision.expression_hint,
                    },
                    source="interaction_coordinator",
                )

            return decision

        else:
            # Presence is lost
            was_present = self._current_presence
            self._current_presence = False
            self._presence_session_greeted = False

            if was_present:
                # If currently in ATTENTION, drop back to IDLE
                if self.state_manager.current_state == AssistantState.ATTENTION:
                    self.state_manager.transition_to(AssistantState.IDLE, reason="presence_lost")

                self.event_bus.create_and_publish(
                    event_type=EventType.PRESENCE_LOST,
                    payload={"present": False},
                    source="interaction_coordinator",
                )

            ctx = SocialContext(
                mode=self._mode,
                presence_state=False,
                current_time=current_time,
                sleep_state=(self.state_manager.current_state == AssistantState.SLEEP),
            )
            decision = self.social_engine.evaluate(ctx)

            # Update Face controller on presence loss
            if self.face_controller:
                self.face_controller.set_state(self.state_manager.current_state)
                self.face_controller.set_gaze(0.0, 0.0)

            return decision
