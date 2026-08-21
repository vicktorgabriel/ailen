"""Domain protocols and contracts for AILEN."""

from typing import Protocol, runtime_checkable

from ailen.domain.models import (
    CoreEvent,
    HardwareReport,
    HealthReport,
    RuntimeState,
)


@runtime_checkable
class HealthCheckable(Protocol):
    """Protocol for components that report health status."""
    def health(self) -> HealthReport:
        """Return component health report."""
        ...


@runtime_checkable
class StatusProvider(Protocol):
    """Protocol for services providing runtime state."""
    def get_runtime_state(self) -> RuntimeState:
        """Get the current observable runtime state."""
        ...


@runtime_checkable
class DiagnosticsProvider(Protocol):
    """Protocol for hardware diagnostics provider."""
    def run_diagnostics(self) -> HardwareReport:
        """Run best-effort hardware discovery and return report."""
        ...


@runtime_checkable
class EventPublisher(Protocol):
    """Protocol for publishing core events."""
    def publish(self, event: CoreEvent) -> None:
        """Publish a core domain event."""
        ...


@runtime_checkable
class EventSubscriber(Protocol):
    """Protocol for subscribing to core events."""
    def on_event(self, event: CoreEvent) -> None:
        """Handle received core domain event."""
        ...
