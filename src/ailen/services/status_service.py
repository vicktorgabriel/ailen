"""Status service combining health, diagnostics, and runtime state."""

from typing import Any

from ailen.core.diagnostics import HardwareDiagnostics
from ailen.core.health import HealthService
from ailen.domain.models import HardwareReport, HealthReport, RuntimeState


class StatusService:
    """Application service providing unified status, health, and hardware info."""

    def __init__(
        self,
        health_service: HealthService,
        diagnostics: HardwareDiagnostics | None = None,
    ):
        self.health_service = health_service
        self.diagnostics = diagnostics or HardwareDiagnostics()
        self._cached_hardware_report: HardwareReport | None = None

    def get_runtime_state(self) -> RuntimeState:
        """Get the latest runtime state."""
        return self.health_service.get_runtime_state()

    def get_health_report(self) -> HealthReport:
        """Get the current aggregated health report."""
        return self.health_service.get_health_report()

    def get_hardware_report(self, refresh: bool = False) -> HardwareReport:
        """Get the hardware discovery report (cached or fresh)."""
        if self._cached_hardware_report is None or refresh:
            self._cached_hardware_report = self.diagnostics.run()
        return self._cached_hardware_report

    def get_dashboard_summary(self) -> dict[str, Any]:
        """Get unified JSON summary suitable for web dashboard / API."""
        runtime = self.get_runtime_state()
        health = self.get_health_report()
        hw = self.get_hardware_report()

        return {
            "version": runtime.version,
            "node_id": runtime.node_id,
            "profile": runtime.profile.value,
            "assistant_state": runtime.assistant_state.value,
            "uptime_seconds": runtime.uptime_seconds,
            "health": {
                "overall": health.status.value,
                "components": {k: v.value for k, v in health.components.items()},
            },
            "services": {
                "internet": runtime.internet_status.value,
                "lan_brain": runtime.lan_brain_status.value,
                "cloud": runtime.cloud_status.value,
                "camera": runtime.camera_status.value,
                "microphone": runtime.microphone_status.value,
                "speaker": runtime.speaker_status.value,
                "memory": runtime.memory_status.value,
            },
            "hardware": {
                "cpu": f"{hw.cpu.model} ({hw.cpu.cores_physical}C/{hw.cpu.cores_logical}T)",
                "ram_mb": hw.memory.total_mb,
                "ram_available_mb": hw.memory.available_mb,
                "disk_free_gb": hw.disk.free_gb,
                "gpu": hw.gpu.name,
                "cameras_count": len(hw.cameras),
                "audio_in_count": len(hw.audio_inputs),
                "audio_out_count": len(hw.audio_outputs),
                "recommended_profile": hw.recommended_profile.value,
            },
            "updated_at": runtime.updated_at,
        }
