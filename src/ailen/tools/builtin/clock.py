"""Clock tool for AILEN.

Provides deterministic local system time and date without calling any LLM.
See ADR-010.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any, ClassVar

from ailen.domain.enums import PrivacyLevel, SocialMode
from ailen.tools.contracts import ToolContext, ToolResult


class ClockTool:
    """Deterministic system clock tool."""

    name: str = "clock"
    description: str = "Obtiene la hora o fecha actual del sistema de manera determinista."
    schema: ClassVar[dict[str, Any]] = {
        "properties": {
            "format": {
                "type": "str",
                "required": False,
                "default": "time",
                "enum": ["time", "iso", "date", "full"],
            },
        },
    }
    permissions: ClassVar[list[str]] = []
    allowed_modes: ClassVar[set[SocialMode]] = set(SocialMode)
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC
    requires_network: bool = False
    destructive: bool = False
    timeout_seconds: float = 2.0

    def __init__(self, time_provider: Callable[[], datetime] | None = None) -> None:
        self.time_provider = time_provider or (lambda: datetime.now().astimezone())

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        now = self.time_provider()
        fmt = validated_args.get("format", "time")

        if fmt == "iso":
            formatted = now.isoformat()
            message = f"Fecha y hora ISO: {formatted}"
        elif fmt == "date":
            formatted = now.strftime("%Y-%m-%d")
            message = f"Hoy es {now.strftime('%d/%m/%Y')}."
        elif fmt == "full":
            formatted = now.strftime("%Y-%m-%d %H:%M:%S")
            message = f"Son las {now.strftime('%H:%M:%S')} del {now.strftime('%d/%m/%Y')}."
        else:  # "time"
            formatted = now.strftime("%H:%M")
            message = f"Son las {now.strftime('%H:%M')}."

        return ToolResult(
            success=True,
            tool_name=self.name,
            status_code="OK",
            message=message,
            summary=message,
            data={
                "time": formatted,
                "iso": now.isoformat(),
                "formatted": formatted,
                "hour": now.hour,
                "minute": now.minute,
                "second": now.second,
            },
            requires_llm_summary=False,
        )
