"""Fake baseline tools. Efectos simulados; deterministas para tests."""

from datetime import UTC, datetime
from typing import Any, ClassVar

from ailen.domain.enums import ErrorCode
from ailen.tools.contracts import ToolContext, ToolResult, validate_args


class ClockTool:
    """Hora actual UTC. Sin LLM, sin I/O."""

    name = "clock"
    schema: ClassVar[dict[str, Any]] = {
        "properties": {
            "format": {"type": "str", "required": False, "enum": ["iso", "time"]},
        }
    }
    permissions: ClassVar[list[str]] = []

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        args = validate_args(self.schema, validated_args)
        now = datetime.now(UTC)
        fmt = args.get("format", "iso")
        value = now.isoformat() if fmt == "iso" else now.strftime("%H:%M:%S UTC")
        return ToolResult(success=True, summary=f"Hora actual: {value}", data={"time": value})


class FakeVolumeTool:
    """Control de volumen simulado (0-100)."""

    name = "volume"
    schema: ClassVar[dict[str, Any]] = {
        "properties": {
            "level": {"type": "int", "required": True, "min": 0, "max": 100},
        }
    }
    permissions: ClassVar[list[str]] = ["audio.control"]

    def __init__(self) -> None:
        self.level = 80

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        args = validate_args(self.schema, validated_args)
        self.level = int(args["level"])
        return ToolResult(
            success=True,
            summary=f"Volumen ajustado a {self.level}",
            data={"level": self.level},
        )


class FakeNotesTool:
    """Notas en memoria volátil. Persistencia real vive en Memory (carril Core)."""

    name = "notes"
    schema: ClassVar[dict[str, Any]] = {
        "properties": {
            "action": {"type": "str", "required": True, "enum": ["add", "list"]},
            "text": {"type": "str", "required": False},
        }
    }
    permissions: ClassVar[list[str]] = ["memory.write"]

    def __init__(self) -> None:
        self._notes: list[str] = []

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        args = validate_args(self.schema, validated_args)
        if args["action"] == "add":
            text = (args.get("text") or "").strip()
            if not text:
                return ToolResult(
                    success=False,
                    summary="Falta el texto de la nota",
                    error_code=ErrorCode.TOOL_ARGS_INVALID,
                )
            self._notes.append(text)
            return ToolResult(success=True, summary="Nota guardada", data={"count": len(self._notes)})
        return ToolResult(
            success=True,
            summary=f"{len(self._notes)} notas",
            data={"notes": list(self._notes)},
        )


def build_fake_tools() -> list:
    """Return the baseline fake tool set."""
    return [ClockTool(), FakeVolumeTool(), FakeNotesTool()]
