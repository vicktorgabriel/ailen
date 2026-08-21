"""Unit tests for EventBus and core event dispatching."""

from ailen.core.events import EventBus, generate_correlation_id
from ailen.domain.contracts import EventSubscriber
from ailen.domain.enums import EventType
from ailen.domain.models import CoreEvent


class DummySubscriber(EventSubscriber):
    """Test subscriber implementing EventSubscriber protocol."""

    def __init__(self) -> None:
        self.received: list[CoreEvent] = []

    def on_event(self, event: CoreEvent) -> None:
        self.received.append(event)


def test_event_bus_typed_subscription() -> None:
    bus = EventBus()
    received_presence: list[CoreEvent] = []
    received_state: list[CoreEvent] = []

    bus.subscribe(EventType.PRESENCE_DETECTED, lambda e: received_presence.append(e))
    bus.subscribe(EventType.STATE_CHANGED, lambda e: received_state.append(e))

    evt1 = bus.create_and_publish(EventType.PRESENCE_DETECTED, {"present": True})
    evt2 = bus.create_and_publish(EventType.STATE_CHANGED, {"state": "ATTENTION"})

    assert len(received_presence) == 1
    assert received_presence[0].event_id == evt1.event_id
    assert len(received_state) == 1
    assert received_state[0].event_id == evt2.event_id


def test_event_bus_global_subscription() -> None:
    bus = EventBus()
    all_events: list[CoreEvent] = []

    bus.subscribe(None, lambda e: all_events.append(e))

    bus.create_and_publish(EventType.PRESENCE_DETECTED, {})
    bus.create_and_publish(EventType.SPEECH_STARTED, {})
    bus.create_and_publish(EventType.SPEECH_FINISHED, {})

    assert len(all_events) == 3


def test_event_bus_unsubscribe() -> None:
    bus = EventBus()
    received: list[CoreEvent] = []

    unsub = bus.subscribe(EventType.WAKE_DETECTED, lambda e: received.append(e))
    bus.create_and_publish(EventType.WAKE_DETECTED, {"wake": True})
    assert len(received) == 1

    unsub()
    bus.create_and_publish(EventType.WAKE_DETECTED, {"wake": True})
    assert len(received) == 1


def test_event_bus_protocol_subscriber() -> None:
    bus = EventBus()
    dummy = DummySubscriber()

    bus.subscribe(EventType.INTENT_RESOLVED, dummy)
    bus.create_and_publish(EventType.INTENT_RESOLVED, {"intent": "greet"})

    assert len(dummy.received) == 1
    assert dummy.received[0].event_type == EventType.INTENT_RESOLVED

    bus.unsubscribe(EventType.INTENT_RESOLVED, dummy)
    bus.create_and_publish(EventType.INTENT_RESOLVED, {"intent": "goodbye"})
    assert len(dummy.received) == 1


def test_event_bus_error_isolation() -> None:
    bus = EventBus()
    safe_received: list[CoreEvent] = []

    def failing_subscriber(event: CoreEvent) -> None:
        raise RuntimeError("Subscriber explosion!")

    def safe_subscriber(event: CoreEvent) -> None:
        safe_received.append(event)

    bus.subscribe(EventType.ERROR, failing_subscriber)
    bus.subscribe(EventType.ERROR, safe_subscriber)

    evt = bus.create_and_publish(EventType.ERROR, {"error": "test"})

    # Even though failing_subscriber raised an exception, safe_subscriber still receives the event
    assert len(safe_received) == 1
    assert safe_received[0].event_id == evt.event_id


def test_event_bus_history_tracking() -> None:
    bus = EventBus(record_history=True, max_history=3)

    for i in range(5):
        bus.create_and_publish(EventType.STATE_CHANGED, {"step": i})

    assert len(bus.history) == 3
    assert bus.history[-1].payload == {"step": 4}

    bus.clear_history()
    assert len(bus.history) == 0


def test_generate_correlation_id() -> None:
    cid1 = generate_correlation_id()
    cid2 = generate_correlation_id("custom")

    assert cid1.startswith("corr-")
    assert cid2.startswith("custom-")
    assert cid1 != cid2
