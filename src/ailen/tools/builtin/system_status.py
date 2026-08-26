"""System status tool for AILEN.

Provides sanitized hardware and health telemetry (CPU, RAM, GPU, audio, uptime)
without exposing sensitive secrets, paths, or tokens.
See ADR-010.
"""

from typing import Any, ClassVar

from ailen.domain.enums import PrivacyLevel, SocialMode
from ailen.hardware.detector import HardwareDetector
from ailen.tools.contracts import ToolContext, ToolResult


class SystemStatusTool:
    """Sanitized system health and hardware diagnostics tool."""

    name: str = "system_status"
    description: str = "Informa el estado de hardware, CPU, memoria y salud del sistema de forma segura."
    intent_hints = ("sistema", "hardware", "cpu", "ram", "memoria", "batería", "bateria", "carga")
    schema: ClassVar[dict[str, Any]] = {
        "properties": {
            "detailed": {
                "type": "bool",
                "required": False,
                "default": False,
            },
        },
    }
    permissions: ClassVar[list[str]] = ["system.diagnose"]
    allowed_modes: ClassVar[set[SocialMode]] = {
        SocialMode.HOME,
        SocialMode.WORKSHOP,
        SocialMode.PRIVATE,
    }
    privacy_level: PrivacyLevel = PrivacyLevel.RESTRICTED
    requires_network: bool = False
    destructive: bool = False
    timeout_seconds: float = 3.0

    def __init__(self, detector: HardwareDetector | None = None) -> None:
        self.detector = detector or HardwareDetector()

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        report = self.detector.detect()
        detailed = validated_args.get("detailed", False)

        # Extract sanitized metrics
        cpu_model = report.cpu.model if report.cpu else "Desconocido"
        cpu_cores = (report.cpu.physical_cores or report.cpu.logical_cores or 1) if report.cpu else 1
        ram_gb = f"{report.ram.total_gb:.1f}" if report.ram and report.ram.total_gb else "Desconocida"
        ram_avail_gb = f"{report.ram.available_gb:.1f}" if report.ram and report.ram.available_gb else "Desconocida"

        gpu_present = bool(report.gpus)
        gpu_name = f"{report.gpus[0].vendor} {report.gpus[0].model}".strip() if report.gpus else "Integrada / Sin GPU dedicada"
        audio_in_count = len(report.audio_inputs)
        audio_out_count = len(report.audio_outputs)
        os_distro = report.os_distribution or report.os_name or "Linux"

        # Build human readable message
        msg = f"Sistema operativo {os_distro}. CPU {cpu_cores} núcleos ({cpu_model}). RAM total {ram_gb} GB, disponible {ram_avail_gb} GB."
        if gpu_present:
            msg += f" GPU: {gpu_name}."

        sanitized_data: dict[str, Any] = {
            "os": os_distro,
            "os_version": report.os_version,
            "cpu_cores": cpu_cores,
            "cpu_model": cpu_model,
            "ram_total_gb": report.ram.total_gb if report.ram else None,
            "ram_available_gb": report.ram.available_gb if report.ram else None,
            "gpu_present": gpu_present,
            "gpu_name": gpu_name,
            "audio_inputs": audio_in_count,
            "audio_outputs": audio_out_count,
        }

        if detailed and report.disk:
            sanitized_data["disk"] = {
                "total_mb": report.disk.total_mb,
                "free_gb": report.disk.free_gb,
            }

        return ToolResult(
            success=True,
            tool_name=self.name,
            status_code="OK",
            message=msg,
            summary=msg,
            data=sanitized_data,
            requires_llm_summary=False,
        )
