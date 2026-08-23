"""Audio volume control service and tool for AILEN.

Supports Linux desktop/appliance audio mixers (PipeWire / PulseAudio / ALSA)
using explicit argument lists without `shell=True`.
If no mixer is present, gracefully returns UNAVAILABLE without faking success.
See ADR-010.
"""

import logging
import re
import shutil
import subprocess
from typing import Any, ClassVar, Protocol, runtime_checkable

from ailen.domain.enums import ErrorCode, PrivacyLevel, SocialMode
from ailen.tools.contracts import ToolContext, ToolResult

logger = logging.getLogger("ailen.tools.volume")


@runtime_checkable
class AudioVolumeService(Protocol):
    """Protocol for system audio volume controllers."""

    def get_volume(self) -> int | None:
        """Return current volume percentage (0..100) or None if unavailable."""
        ...

    def set_volume(self, level: int) -> bool:
        """Set volume percentage (0..100). Return True on success, False if unavailable."""
        ...

    def step_volume(self, delta: int) -> int | None:
        """Adjust volume by delta percentage. Return new volume or None if unavailable."""
        ...

    def mute(self) -> bool:
        """Mute the audio output. Return True on success, False if unavailable."""
        ...


class SystemAudioVolumeService:
    """Linux system volume service supporting wpctl, pactl, and amixer safely."""

    def __init__(self) -> None:
        self._backend = self._detect_backend()

    def _detect_backend(self) -> str | None:
        """Find the first available mixer binary on the system."""
        for binary in ("wpctl", "pactl", "amixer"):
            if shutil.which(binary) is not None:
                return binary
        return None

    @property
    def is_available(self) -> bool:
        return self._backend is not None

    def get_volume(self) -> int | None:
        if not self._backend:
            return None

        try:
            if self._backend == "wpctl":
                # Output like: "Volume: 0.65" or "Volume: 0.65 [MUTED]"
                res = subprocess.run(
                    ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                    capture_output=True,
                    text=True,
                    shell=False,
                    timeout=2.0,
                    check=True,
                )
                match = re.search(r"Volume:\s+([0-9.]+)", res.stdout)
                if match:
                    return int(float(match.group(1)) * 100)

            elif self._backend == "pactl":
                res = subprocess.run(
                    ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                    capture_output=True,
                    text=True,
                    shell=False,
                    timeout=2.0,
                    check=True,
                )
                match = re.search(r"(\d+)%", res.stdout)
                if match:
                    return int(match.group(1))

            elif self._backend == "amixer":
                res = subprocess.run(
                    ["amixer", "sget", "Master"],
                    capture_output=True,
                    text=True,
                    shell=False,
                    timeout=2.0,
                    check=True,
                )
                match = re.search(r"\[(\d+)%\]", res.stdout)
                if match:
                    return int(match.group(1))

        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to read system volume using %s: %s", self._backend, exc)

        return None

    def set_volume(self, level: int) -> bool:
        if not self._backend:
            return False

        clamped = max(0, min(100, level))
        try:
            if self._backend == "wpctl":
                val = f"{clamped / 100.0:.2f}"
                subprocess.run(
                    ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", val],
                    capture_output=True,
                    shell=False,
                    timeout=2.0,
                    check=True,
                )
                return True

            if self._backend == "pactl":
                val = f"{clamped}%"
                subprocess.run(
                    ["pactl", "set-sink-volume", "@DEFAULT_SINK@", val],
                    capture_output=True,
                    shell=False,
                    timeout=2.0,
                    check=True,
                )
                return True

            if self._backend == "amixer":
                val = f"{clamped}%"
                subprocess.run(
                    ["amixer", "sset", "Master", val],
                    capture_output=True,
                    shell=False,
                    timeout=2.0,
                    check=True,
                )
                return True

        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to set system volume using %s: %s", self._backend, exc)

        return False

    def step_volume(self, delta: int) -> int | None:
        current = self.get_volume()
        if current is None:
            return None
        target = max(0, min(100, current + delta))
        if self.set_volume(target):
            return target
        return None

    def mute(self) -> bool:
        if not self._backend:
            return False

        try:
            if self._backend == "wpctl":
                subprocess.run(
                    ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"],
                    capture_output=True,
                    shell=False,
                    timeout=2.0,
                    check=True,
                )
                return True
            if self._backend == "pactl":
                subprocess.run(
                    ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
                    capture_output=True,
                    shell=False,
                    timeout=2.0,
                    check=True,
                )
                return True
            if self._backend == "amixer":
                subprocess.run(
                    ["amixer", "sset", "Master", "mute"],
                    capture_output=True,
                    shell=False,
                    timeout=2.0,
                    check=True,
                )
                return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to mute system volume using %s: %s", self._backend, exc)

        return False


class FakeAudioVolumeService:
    """In-memory simulated audio volume service for tests and dry runs."""

    def __init__(self, initial_level: int = 60, available: bool = True) -> None:
        self.level: int = initial_level
        self.muted: bool = False
        self.available: bool = available

    def get_volume(self) -> int | None:
        if not self.available:
            return None
        return 0 if self.muted else self.level

    def set_volume(self, level: int) -> bool:
        if not self.available:
            return False
        self.level = max(0, min(100, level))
        self.muted = False
        return True

    def step_volume(self, delta: int) -> int | None:
        if not self.available:
            return None
        self.level = max(0, min(100, self.level + delta))
        self.muted = False
        return self.level

    def mute(self) -> bool:
        if not self.available:
            return False
        self.muted = True
        return True


class VolumeTool:
    """Deterministic system volume control tool."""

    name: str = "volume"
    description: str = "Controla el volumen del audio del sistema de forma segura."
    schema: ClassVar[dict[str, Any]] = {
        "properties": {
            "action": {
                "type": "str",
                "required": True,
                "enum": ["get", "set", "step_up", "step_down", "mute"],
            },
            "level": {
                "type": "int",
                "required": False,
                "min": 0,
                "max": 100,
            },
            "step": {
                "type": "int",
                "required": False,
                "min": 1,
                "max": 100,
                "default": 10,
            },
        },
    }
    permissions: ClassVar[list[str]] = ["audio.control"]
    allowed_modes: ClassVar[set[SocialMode]] = set(SocialMode)
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    requires_network: bool = False
    destructive: bool = False
    timeout_seconds: float = 2.0

    def __init__(self, service: AudioVolumeService | None = None) -> None:
        self.service = service if service is not None else SystemAudioVolumeService()

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        action = validated_args["action"]

        if action == "get":
            vol = self.service.get_volume()
            if vol is None:
                msg = "El control de volumen del sistema no está disponible."
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="UNAVAILABLE",
                    message=msg,
                    summary=msg,
                    error_code=ErrorCode.TOOL_UNAVAILABLE,
                )
            msg = f"El volumen actual es {vol}%."
            return ToolResult(
                success=True,
                tool_name=self.name,
                status_code="OK",
                message=msg,
                summary=msg,
                data={"level": vol},
                requires_llm_summary=False,
            )

        if action == "set":
            level = validated_args.get("level")
            if level is None:
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="INVALID_ARGS",
                    message="Se requiere especificar el nivel de volumen (0-100).",
                    error_code=ErrorCode.TOOL_ARGS_INVALID,
                )
            ok = self.service.set_volume(level)
            if not ok:
                msg = "No se pudo ajustar el volumen del sistema."
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="UNAVAILABLE",
                    message=msg,
                    summary=msg,
                    error_code=ErrorCode.TOOL_UNAVAILABLE,
                )
            msg = f"Listo, volumen al {level}%."
            return ToolResult(
                success=True,
                tool_name=self.name,
                status_code="OK",
                message=msg,
                summary=msg,
                data={"level": level},
                requires_llm_summary=False,
            )

        if action in {"step_up", "step_down"}:
            step = validated_args.get("step", 10)
            delta = step if action == "step_up" else -step
            new_vol = self.service.step_volume(delta)
            if new_vol is None:
                msg = "No se pudo cambiar el volumen del sistema."
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="UNAVAILABLE",
                    message=msg,
                    summary=msg,
                    error_code=ErrorCode.TOOL_UNAVAILABLE,
                )
            msg = f"Listo, volumen al {new_vol}%."
            return ToolResult(
                success=True,
                tool_name=self.name,
                status_code="OK",
                message=msg,
                summary=msg,
                data={"level": new_vol},
                requires_llm_summary=False,
            )

        if action == "mute":
            ok = self.service.mute()
            if not ok:
                msg = "No se pudo silenciar el audio del sistema."
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="UNAVAILABLE",
                    message=msg,
                    summary=msg,
                    error_code=ErrorCode.TOOL_UNAVAILABLE,
                )
            msg = "Audio silenciado."
            return ToolResult(
                success=True,
                tool_name=self.name,
                status_code="OK",
                message=msg,
                summary=msg,
                data={"muted": True},
                requires_llm_summary=False,
            )

        return ToolResult(
            success=False,
            tool_name=self.name,
            status_code="INVALID_ARGS",
            message=f"Acción de volumen desconocida: {action}",
            error_code=ErrorCode.TOOL_ARGS_INVALID,
        )
