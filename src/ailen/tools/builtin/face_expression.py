"""Controlled facial expression tool for AILEN's local avatar."""

from typing import Any, ClassVar

from ailen.domain.enums import ErrorCode, PrivacyLevel, SocialMode
from ailen.face.animator import FaceAnimator
from ailen.face.contracts import FaceController
from ailen.tools.contracts import ToolContext, ToolResult


class FaceExpressionTool:
    name = "face_expression"
    description = "Cambia la expresión visible de la cara de Ailén cuando el display facial está activo."
    intent_hints = (
        "gesto", "gestos", "gesticular", "cara", "rostro", "ojos", "boca",
        "sonreí", "sonrei", "guiñá", "guina", "expresión", "expresion",
        "alegre", "curiosa", "sorprendida", "confundida",
    )
    schema: ClassVar[dict[str, Any]] = {
        "properties": {
            "expression": {
                "type": "str",
                "required": True,
                "enum": list(FaceAnimator.SUPPORTED_EXPRESSIONS),
            },
            "duration_seconds": {
                "type": "float",
                "default": 5.0,
                "min": 0.5,
                "max": 10.0,
            },
        }
    }
    permissions: ClassVar[list[str]] = ["display.expression"]
    allowed_modes: ClassVar[set[SocialMode]] = set(SocialMode)
    privacy_level = PrivacyLevel.PUBLIC
    requires_network = False
    destructive = False
    timeout_seconds = 1.0

    def __init__(self, controller: FaceController) -> None:
        self.controller = controller

    @property
    def is_available(self) -> bool:
        provider = getattr(self.controller, "capabilities", None)
        if not callable(provider):
            return False
        try:
            return any(item.key == "face.expression" and item.available for item in provider())
        except Exception:  # noqa: BLE001
            return False

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        del context
        if not self.is_available:
            msg = "La cara gráfica no está activa."
            return ToolResult(
                success=False,
                tool_name=self.name,
                status_code="UNAVAILABLE",
                message=msg,
                error_code=ErrorCode.TOOL_UNAVAILABLE,
            )
        expression = str(validated_args["expression"])
        duration_seconds = float(validated_args.get("duration_seconds", 5.0))
        self.controller.set_expression(expression, duration_seconds)
        labels = {
            "neutral": "neutral",
            "happy": "alegre",
            "curious": "curiosa",
            "surprised": "sorprendida",
            "confused": "confundida",
            "wink": "guiñando",
            "focused": "concentrada",
            "sad": "triste",
            "skeptical": "escéptica",
            "excited": "entusiasmada",
            "playful": "juguetona",
        }
        msg = f"Listo, expresión {labels[expression]}."
        return ToolResult(
            success=True,
            tool_name=self.name,
            status_code="OK",
            message=msg,
            data={"expression": expression, "duration_seconds": duration_seconds},
            requires_llm_summary=False,
        )
