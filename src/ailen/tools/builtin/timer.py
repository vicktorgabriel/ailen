"""Timer service and tool for AILEN.

Provides in-memory, thread-safe timer creation, listing, and cancellation.
No external subprocesses.
See ADR-010.
"""

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, ClassVar

from ailen.domain.enums import ErrorCode, PrivacyLevel, SocialMode
from ailen.tools.contracts import ToolContext, ToolResult


@dataclass
class TimerEntry:
    """Represents an in-memory active or past timer."""

    timer_id: str
    duration_seconds: float
    created_at: float
    expires_at: float
    label: str
    status: str  # "ACTIVE", "EXPIRED", "CANCELLED"

    @property
    def remaining_seconds(self) -> float:
        if self.status != "ACTIVE":
            return 0.0
        rem = self.expires_at - time.monotonic()
        return max(0.0, rem)


class TimerService:
    """Thread-safe in-memory timer service managed by Core."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._timers: dict[str, TimerEntry] = {}

    def create_timer(self, duration_seconds: float, label: str = "") -> TimerEntry:
        """Create and register a new active timer."""
        now = time.monotonic()
        timer_id = f"tmr-{uuid.uuid4().hex[:8]}"
        entry = TimerEntry(
            timer_id=timer_id,
            duration_seconds=duration_seconds,
            created_at=now,
            expires_at=now + duration_seconds,
            label=label or f"Temporizador de {int(duration_seconds)}s",
            status="ACTIVE",
        )
        with self._lock:
            self._timers[timer_id] = entry
        return entry

    def list_timers(self, active_only: bool = True) -> list[TimerEntry]:
        """List active (or all) timers, updating expired statuses."""
        now = time.monotonic()
        with self._lock:
            for entry in self._timers.values():
                if entry.status == "ACTIVE" and now >= entry.expires_at:
                    entry.status = "EXPIRED"

            if active_only:
                return [t for t in self._timers.values() if t.status == "ACTIVE"]
            return list(self._timers.values())

    def cancel_timer(self, timer_id: str | None = None) -> bool:
        """Cancel a timer by ID, or cancel the most recent active timer if ID is None."""
        now = time.monotonic()
        with self._lock:
            # Update expired timers first
            for entry in self._timers.values():
                if entry.status == "ACTIVE" and now >= entry.expires_at:
                    entry.status = "EXPIRED"

            if timer_id:
                target_entry = self._timers.get(timer_id)
                if target_entry and target_entry.status == "ACTIVE":
                    target_entry.status = "CANCELLED"
                    return True
                return False

            # Cancel most recent active timer
            active = [t for t in self._timers.values() if t.status == "ACTIVE"]
            if active:
                active.sort(key=lambda t: t.created_at, reverse=True)
                active[0].status = "CANCELLED"
                return True
            return False

    def clear(self) -> None:
        """Clear all timers (primarily for testing)."""
        with self._lock:
            self._timers.clear()


class TimerTool:
    """Controlled timer tool allowing create, list, and cancel actions."""

    name: str = "timer"
    description: str = "Crea, lista o cancela temporizadores en memoria de manera determinista."
    intent_hints = ("temporizador", "timer", "alarma", "cuenta regresiva", "cronómetro", "cronometro")
    schema: ClassVar[dict[str, Any]] = {
        "properties": {
            "action": {
                "type": "str",
                "required": True,
                "enum": ["create", "list", "cancel"],
            },
            "seconds": {
                "type": "int",
                "required": False,
                "min": 1,
                "max": 86400,
            },
            "label": {
                "type": "str",
                "required": False,
                "max_len": 100,
            },
            "timer_id": {
                "type": "str",
                "required": False,
            },
        },
    }
    permissions: ClassVar[list[str]] = ["timer.manage"]
    allowed_modes: ClassVar[set[SocialMode]] = {
        SocialMode.HOME,
        SocialMode.WORKSHOP,
        SocialMode.PRIVATE,
    }
    privacy_level: PrivacyLevel = PrivacyLevel.PRIVATE
    requires_network: bool = False
    destructive: bool = False
    timeout_seconds: float = 2.0

    def __init__(self, service: TimerService | None = None) -> None:
        self.service = service or TimerService()

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        action = validated_args["action"]

        if action == "create":
            seconds = validated_args.get("seconds")
            if not seconds:
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="INVALID_ARGS",
                    message="Se requiere especificar la duración en segundos para el temporizador.",
                    error_code=ErrorCode.TOOL_ARGS_INVALID,
                )
            label = validated_args.get("label", "")
            entry = self.service.create_timer(duration_seconds=float(seconds), label=label)

            # Human friendly message
            if seconds >= 60 and seconds % 60 == 0:
                mins = int(seconds // 60)
                unit_str = f"{mins} {'minuto' if mins == 1 else 'minutos'}"
            else:
                unit_str = f"{seconds} segundos"

            msg = f"Temporizador de {unit_str} iniciado."
            return ToolResult(
                success=True,
                tool_name=self.name,
                status_code="OK",
                message=msg,
                summary=msg,
                data={
                    "timer_id": entry.timer_id,
                    "duration_seconds": entry.duration_seconds,
                    "label": entry.label,
                },
                requires_llm_summary=False,
            )

        if action == "list":
            active_timers = self.service.list_timers(active_only=True)
            if not active_timers:
                msg = "No hay temporizadores activos."
            elif len(active_timers) == 1:
                t = active_timers[0]
                msg = f"Hay 1 temporizador activo con {int(t.remaining_seconds)} segundos restantes."
            else:
                msg = f"Hay {len(active_timers)} temporizadores activos."

            return ToolResult(
                success=True,
                tool_name=self.name,
                status_code="OK",
                message=msg,
                summary=msg,
                data={
                    "count": len(active_timers),
                    "timers": [
                        {
                            "timer_id": t.timer_id,
                            "remaining_seconds": int(t.remaining_seconds),
                            "duration_seconds": t.duration_seconds,
                            "label": t.label,
                        }
                        for t in active_timers
                    ],
                },
                requires_llm_summary=False,
            )

        if action == "cancel":
            timer_id = validated_args.get("timer_id")
            cancelled = self.service.cancel_timer(timer_id)
            if cancelled:
                msg = "Temporizador cancelado."
                return ToolResult(
                    success=True,
                    tool_name=self.name,
                    status_code="OK",
                    message=msg,
                    summary=msg,
                    data={"cancelled": True},
                    requires_llm_summary=False,
                )
            msg = "No se encontró ningún temporizador activo para cancelar."
            return ToolResult(
                success=False,
                tool_name=self.name,
                status_code="NOT_FOUND",
                message=msg,
                summary=msg,
                data={"cancelled": False},
                requires_llm_summary=False,
            )

        return ToolResult(
            success=False,
            tool_name=self.name,
            status_code="INVALID_ARGS",
            message=f"Acción de temporizador desconocida: {action}",
            error_code=ErrorCode.TOOL_ARGS_INVALID,
        )
