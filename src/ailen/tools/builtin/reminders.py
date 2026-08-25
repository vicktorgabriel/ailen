"""Persistent reminder tool and low-cost scheduler for AILEN."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any, ClassVar

from ailen.core.events import EventBus
from ailen.domain.enums import ErrorCode, EventType, PrivacyLevel, SocialMode
from ailen.domain.models import ReminderItem
from ailen.memory.repository import MemoryRepository
from ailen.tools.contracts import ToolContext, ToolResult
from ailen.tools.reminder_time import parse_reminder_when

logger = logging.getLogger("ailen.tools.reminders")


class ReminderService:
    """Poll persistent reminders and publish due events without doing audio I/O."""

    def __init__(
        self,
        repository: MemoryRepository,
        event_bus: EventBus | None = None,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self.repository = repository
        self.event_bus = event_bus
        self.poll_interval_seconds = max(0.5, poll_interval_seconds)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="ailen-reminders",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=max(1.0, self.poll_interval_seconds + 0.5))
        self._thread = None

    def poll_once(self, now_iso: str | None = None) -> list[ReminderItem]:
        """Publish all reminders due at/before ``now_iso`` and mark them notified."""
        boundary = now_iso or datetime.now(UTC).isoformat()
        due = self.repository.list_due_reminders(boundary, limit=50)
        published: list[ReminderItem] = []
        for reminder in due:
            try:
                if self.event_bus is not None:
                    self.event_bus.create_and_publish(
                        EventType.REMINDER_DUE,
                        payload={
                            "reminder_id": reminder.reminder_id,
                            "content": reminder.content,
                            "due_at": reminder.due_at,
                        },
                        source="reminder_service",
                    )
                self.repository.mark_reminder_notified(reminder.reminder_id, notified_at=boundary)
                published.append(reminder)
            except Exception:
                logger.exception("Could not dispatch reminder %s", reminder.reminder_id)
        return published

    def _run(self) -> None:
        while not self._stop_event.wait(self.poll_interval_seconds):
            try:
                self.poll_once()
            except Exception:
                logger.exception("Reminder scheduler poll failed")


class RemindersTool:
    """Create, list and cancel persistent time-anchored reminders."""

    name: str = "reminders"
    description: str = "Crea, lista o cancela recordatorios persistentes con fecha u hora explícita."
    schema: ClassVar[dict[str, Any]] = {
        "properties": {
            "action": {
                "type": "str",
                "required": True,
                "enum": ["create", "list", "cancel"],
            },
            "text": {"type": "str", "required": False, "max_len": 1000},
            "when": {"type": "str", "required": False, "max_len": 100},
            "reminder_id": {"type": "str", "required": False, "max_len": 100},
            "limit": {"type": "int", "required": False, "min": 1, "max": 50, "default": 10},
        },
    }
    permissions: ClassVar[list[str]] = ["memory.write", "memory.read"]
    allowed_modes: ClassVar[set[SocialMode]] = {
        SocialMode.HOME,
        SocialMode.WORKSHOP,
        SocialMode.PRIVATE,
    }
    privacy_level: PrivacyLevel = PrivacyLevel.PRIVATE
    requires_network: bool = False
    destructive: bool = False
    timeout_seconds: float = 2.0

    def __init__(self, repository: MemoryRepository | None = None) -> None:
        self.repository = repository

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        del context
        if self.repository is None:
            return ToolResult(
                success=False,
                tool_name=self.name,
                status_code="UNAVAILABLE",
                message="Los recordatorios persistentes requieren la base de datos local.",
                error_code=ErrorCode.TOOL_UNAVAILABLE,
            )

        action = validated_args["action"]
        if action == "create":
            text = (validated_args.get("text") or "").strip()
            when_text = (validated_args.get("when") or "").strip()
            if not text or not when_text:
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="INVALID_ARGS",
                    message="Falta el texto o el momento del recordatorio.",
                    error_code=ErrorCode.TOOL_ARGS_INVALID,
                )
            try:
                due_at = parse_reminder_when(when_text)
            except ValueError as exc:
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    status_code="INVALID_TIME",
                    message=str(exc),
                    error_code=ErrorCode.TOOL_ARGS_INVALID,
                )
            item = self.repository.create_reminder(content=text, due_at=due_at)
            msg = f"Recordatorio guardado: {text}, {when_text}."
            return ToolResult(
                success=True,
                tool_name=self.name,
                status_code="OK",
                message=msg,
                data={
                    "reminder_id": item.reminder_id,
                    "content": item.content,
                    "due_at": item.due_at,
                },
                requires_llm_summary=False,
            )

        if action == "list":
            limit = int(validated_args.get("limit", 10))
            reminders = self.repository.list_reminders(status="PENDING", limit=limit)
            data = [
                {"reminder_id": r.reminder_id, "content": r.content, "due_at": r.due_at}
                for r in reminders
            ]
            if not data:
                msg = "No tenés recordatorios pendientes."
            elif len(data) == 1:
                msg = f"Tenés 1 recordatorio pendiente: {data[0]['content']}."
            else:
                preview = "; ".join(f"{idx + 1}) {item['content']}" for idx, item in enumerate(data[:5]))
                msg = f"Tenés {len(data)} recordatorios pendientes: {preview}."
            return ToolResult(
                success=True,
                tool_name=self.name,
                message=msg,
                data={"count": len(data), "reminders": data},
                requires_llm_summary=False,
            )

        if action == "cancel":
            reminder_id = (validated_args.get("reminder_id") or "").strip() or None
            cancelled = self.repository.cancel_reminder(reminder_id)
            msg = "Recordatorio cancelado." if cancelled else "No encontré un recordatorio pendiente para cancelar."
            return ToolResult(
                success=cancelled,
                tool_name=self.name,
                status_code="OK" if cancelled else "NOT_FOUND",
                message=msg,
                data={"cancelled": cancelled},
                error_code=None if cancelled else ErrorCode.TOOL_NOT_FOUND,
                requires_llm_summary=False,
            )

        return ToolResult(
            success=False,
            tool_name=self.name,
            status_code="INVALID_ARGS",
            message=f"Acción de recordatorio desconocida: {action}",
            error_code=ErrorCode.TOOL_ARGS_INVALID,
        )
