"""Health monitoring and RuntimeState service for AILEN."""

import time

from ailen.domain.enums import (
    AssistantState,
    DeviceProfile,
    ErrorCode,
    ServiceStatus,
)
from ailen.domain.models import HealthReport, RuntimeState
from ailen.version import __version__


class HealthService:
    """Aggregates system health and tracks runtime state."""

    def __init__(self, node_id: str = "ailen-node-01", profile: DeviceProfile = DeviceProfile.HYBRID):
        self.node_id = node_id
        self.profile = profile
        self._start_time = time.time()
        self._assistant_state = AssistantState.BOOTING
        self._component_statuses: dict[str, ServiceStatus] = {
            "core": ServiceStatus.HEALTHY,
            "memory": ServiceStatus.HEALTHY,
            "display": ServiceStatus.HEALTHY,
            "audio": ServiceStatus.HEALTHY,
            "vision": ServiceStatus.HEALTHY,
            "ai": ServiceStatus.HEALTHY,
            "internet": ServiceStatus.UNKNOWN,
            "lan_brain": ServiceStatus.DISABLED,
        }
        self._last_error: ErrorCode | None = None

    def set_assistant_state(self, state: AssistantState) -> None:
        """Update current assistant interaction state."""
        self._assistant_state = state

    def set_component_status(self, component: str, status: ServiceStatus) -> None:
        """Update health status of a subsystem component."""
        self._component_statuses[component] = status

    def set_last_error(self, error_code: ErrorCode | None) -> None:
        """Record the most recent operational error code."""
        self._last_error = error_code

    @property
    def uptime_seconds(self) -> float:
        """Get total runtime uptime in seconds."""
        return round(time.time() - self._start_time, 2)

    def get_runtime_state(self) -> RuntimeState:
        """Generate current public RuntimeState model."""
        return RuntimeState(
            version=__version__,
            node_id=self.node_id,
            profile=self.profile,
            assistant_state=self._assistant_state,
            uptime_seconds=self.uptime_seconds,
            internet_status=self._component_statuses.get("internet", ServiceStatus.UNKNOWN),
            lan_brain_status=self._component_statuses.get("lan_brain", ServiceStatus.DISABLED),
            cloud_status=self._component_statuses.get("ai", ServiceStatus.UNKNOWN),
            camera_status=self._component_statuses.get("vision", ServiceStatus.UNKNOWN),
            microphone_status=self._component_statuses.get("audio", ServiceStatus.UNKNOWN),
            speaker_status=self._component_statuses.get("audio", ServiceStatus.UNKNOWN),
            memory_status=self._component_statuses.get("memory", ServiceStatus.UNKNOWN),
            last_error_code=self._last_error,
        )

    def get_health_report(self) -> HealthReport:
        """Generate aggregated health report."""
        # Calculate overall status
        statuses = list(self._component_statuses.values())
        if any(s == ServiceStatus.UNHEALTHY for s in statuses):
            overall = ServiceStatus.UNHEALTHY
        elif any(s == ServiceStatus.DEGRADED for s in statuses):
            overall = ServiceStatus.DEGRADED
        else:
            overall = ServiceStatus.HEALTHY

        return HealthReport(
            status=overall,
            components=dict(self._component_statuses),
            details={
                "uptime_seconds": self.uptime_seconds,
                "assistant_state": self._assistant_state.value,
                "node_id": self.node_id,
                "version": __version__,
            },
        )
