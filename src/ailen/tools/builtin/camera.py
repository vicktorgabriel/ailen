"""Controlled generic camera-management tool."""

from typing import Any, ClassVar

from ailen.domain.enums import ErrorCode, PrivacyLevel, SocialMode
from ailen.tools.contracts import ToolContext, ToolResult
from ailen.vision.control import CameraControl


class CameraTool:
    name = "camera"
    description = "Consulta o cambia funciones controlables de la cámara, incluido día/noche/infrarrojo."
    intent_hints = (
        "cámara", "camara", "infrarrojo", "infrarrojos", "visión nocturna", "vision nocturna",
        "modo noche", "modo día", "modo dia", "night", "daynight", "ir",
    )
    schema: ClassVar[dict[str, Any]] = {
        "properties": {
            "action": {
                "type": "str",
                "required": True,
                "enum": ["status", "set_daynight"],
            },
            "mode": {
                "type": "str",
                "required": False,
                "enum": ["auto", "day", "night"],
            },
        }
    }
    permissions: ClassVar[list[str]] = ["camera.control"]
    allowed_modes: ClassVar[set[SocialMode]] = {SocialMode.HOME, SocialMode.WORKSHOP, SocialMode.PRIVATE}
    privacy_level = PrivacyLevel.PRIVATE
    requires_network = False
    destructive = False
    timeout_seconds = 5.0

    def __init__(self, control: CameraControl | None) -> None:
        self.control = control

    @property
    def is_available(self) -> bool:
        return bool(self.control is not None and self.control.is_available)

    def is_side_effecting(self, arguments: dict[str, Any]) -> bool:
        return arguments.get("action") != "status"

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        del context
        if not self.is_available or self.control is None:
            return ToolResult(
                success=False,
                tool_name=self.name,
                status_code="UNAVAILABLE",
                message="El control de cámara no está disponible.",
                error_code=ErrorCode.TOOL_UNAVAILABLE,
            )
        try:
            action = str(validated_args["action"])
            if action == "status":
                status = self.control.get_status()
                message = f"La cámara está en modo {status.daynight_mode}."
            else:
                mode = str(validated_args.get("mode") or "").strip().lower()
                if not mode:
                    return ToolResult(
                        success=False,
                        tool_name=self.name,
                        status_code="INVALID_ARGUMENT",
                        message="Falta indicar auto, day o night.",
                        error_code=ErrorCode.TOOL_ARGS_INVALID,
                    )
                status = self.control.set_daynight_mode(mode)
                labels = {"auto": "automático", "day": "día", "night": "noche/infrarrojo"}
                message = f"Cámara en modo {labels[status.daynight_mode]}."
            return ToolResult(
                success=True,
                tool_name=self.name,
                status_code="OK",
                message=message,
                data={"daynight_mode": status.daynight_mode},
                requires_llm_summary=False,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                tool_name=self.name,
                status_code="ERROR",
                message=f"No pude cambiar el modo de la cámara: {type(exc).__name__}.",
                error_code=ErrorCode.CAMERA_UNAVAILABLE,
            )
