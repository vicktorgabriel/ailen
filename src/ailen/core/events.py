"""Lightweight in-memory event bus and event dispatching for AILEN Core."""

import logging
import uuid
from collections.abc import Callable
from typing import Any

from ailen.domain.contracts import EventPublisher, EventSubscriber
from ailen.domain.enums import EventType
from ailen.domain.models import CoreEvent

logger = logging.getLogger("ailen.core.events")

EventCallback = Callable[[CoreEvent], None]


def generate_correlation_id(prefix: str = "corr") -> str:
    """Generate a unique correlation ID for tracing an interaction chain."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class EventBus(EventPublisher):
    """Lightweight, deterministic in-memory event bus.
    
    Provides:
    - Typed or wildcard event subscription.
    - Subscriber error isolation (one broken subscriber does not abort others).
    - Optional event history tracking for deterministic tests and observability.
    - Correlation ID generation and tracking.
    """

    def __init__(self, record_history: bool = True, max_history: int = 100):
        self._typed_subscribers: dict[EventType, list[EventCallback]] = {}
        self._global_subscribers: list[EventCallback] = []
        self._record_history = record_history
        self._max_history = max_history
        self._history: list[CoreEvent] = []

    @property
    def history(self) -> list[CoreEvent]:
        """Return shallow copy of recorded event history."""
        return list(self._history)

    def clear_history(self) -> None:
        """Clear recorded event history."""
        self._history.clear()

    def subscribe(
        self,
        event_type: EventType | None,
        subscriber: EventCallback | EventSubscriber,
    ) -> Callable[[], None]:
        """Register a subscriber for a specific event type or all events.
        
        Args:
            event_type: Specific EventType, or None for all events.
            subscriber: Callable receiving CoreEvent or an EventSubscriber instance.
            
        Returns:
            An unsubscribe function for convenient cleanup.
        """
        callback: EventCallback
        if isinstance(subscriber, EventSubscriber):
            callback = subscriber.on_event
        else:
            callback = subscriber

        if event_type is None:
            self._global_subscribers.append(callback)

            def _unsub_global() -> None:
                self.unsubscribe(None, callback)

            return _unsub_global

        if event_type not in self._typed_subscribers:
            self._typed_subscribers[event_type] = []
        self._typed_subscribers[event_type].append(callback)

        def _unsub_typed() -> None:
            self.unsubscribe(event_type, callback)

        return _unsub_typed

    def unsubscribe(
        self,
        event_type: EventType | None,
        subscriber: EventCallback | EventSubscriber,
    ) -> bool:
        """Unregister a subscriber. Returns True if successfully removed."""
        callback: EventCallback
        if isinstance(subscriber, EventSubscriber):
            callback = subscriber.on_event
        else:
            callback = subscriber

        if event_type is None:
            if callback in self._global_subscribers:
                self._global_subscribers.remove(callback)
                return True
            return False

        if event_type in self._typed_subscribers and callback in self._typed_subscribers[event_type]:
            self._typed_subscribers[event_type].remove(callback)
            return True
        return False

    def publish(self, event: CoreEvent) -> None:
        """Publish an event to all matched subscribers with error isolation."""
        if self._record_history:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history.pop(0)

        # Collect targets (global subscribers first, then type-specific subscribers)
        targets: list[EventCallback] = list(self._global_subscribers)
        if event.event_type in self._typed_subscribers:
            targets.extend(self._typed_subscribers[event.event_type])

        for callback in targets:
            try:
                callback(event)
            except Exception:
                logger.exception(
                    "Error executing event subscriber for event %s (id: %s, source: %s)",
                    event.event_type.value,
                    event.event_id,
                    event.source,
                )

    def create_and_publish(
        self,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        source: str = "core",
    ) -> CoreEvent:
        """Helper to create and publish a CoreEvent in one step."""
        event_id = f"evt-{uuid.uuid4().hex[:12]}"
        event = CoreEvent(
            event_id=event_id,
            event_type=event_type,
            payload=payload or {},
            source=source,
            correlation_id=correlation_id,
        )
        self.publish(event)
        return event
