"""Persistent reminders: temporal parsing, SQLite CRUD, tools, and scheduling."""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from ailen.core.events import EventBus
from ailen.domain.enums import EventType, SocialMode
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.memory.repository import MemoryRepository
from ailen.tools.builtin.reminders import ReminderService, RemindersTool
from ailen.tools.contracts import ToolContext
from ailen.tools.reminder_time import extract_reminder_request, parse_reminder_when


def _repository(tmp_path: Path) -> MemoryRepository:
    manager = SQLiteManager(tmp_path / "reminders.db")
    MigrationRunner(manager).run_migrations()
    return MemoryRepository(manager)


def test_extract_reminder_requires_explicit_temporal_anchor() -> None:
    request = extract_reminder_request("Recordame comprar estaño mañana a las 10:30")
    assert request is not None
    assert request.content == "comprar estaño"
    assert request.when_text == "mañana a las 10:30"

    request = extract_reminder_request("Recuérdame que apague el horno en 20 minutos")
    assert request is not None
    assert request.content == "apague el horno"
    assert request.when_text == "en 20 minutos"

    assert extract_reminder_request("recordá que tengo que comprar leche") is None
    assert extract_reminder_request("mañana a las 10 comprar leche") is None


def test_parse_reminder_when_relative_and_local_clock() -> None:
    buenos_aires = timezone(timedelta(hours=-3))
    now = datetime(2026, 8, 24, 22, 0, tzinfo=buenos_aires)

    assert parse_reminder_when("en 20 minutos", now=now) == "2026-08-25T01:20:00+00:00"
    assert parse_reminder_when("mañana a las 10", now=now) == "2026-08-25T13:00:00+00:00"
    assert parse_reminder_when("25/08/2026 a las 18:30", now=now) == "2026-08-25T21:30:00+00:00"

    with pytest.raises(ValueError):
        parse_reminder_when("mañana", now=now)
    with pytest.raises(ValueError):
        parse_reminder_when("hoy a las 20", now=now)
    with pytest.raises(ValueError):
        parse_reminder_when("25/08/2026 a las 99:00", now=now)


def test_reminder_repository_crud_and_due_filter(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    first = repo.create_reminder("apagar horno", "2026-08-24T23:00:00+00:00")
    second = repo.create_reminder("comprar estaño", "2026-08-25T12:00:00+00:00")

    pending = repo.list_reminders(status="PENDING")
    assert [item.reminder_id for item in pending] == [first.reminder_id, second.reminder_id]

    due = repo.list_due_reminders("2026-08-25T00:00:00+00:00")
    assert [item.reminder_id for item in due] == [first.reminder_id]

    assert repo.mark_reminder_notified(first.reminder_id, "2026-08-25T00:00:01+00:00") is True
    notified = repo.list_reminders(status="NOTIFIED")
    assert notified[0].notified_at == "2026-08-25T00:00:01+00:00"

    assert repo.cancel_reminder(second.reminder_id) is True
    assert repo.list_reminders(status="PENDING") == []
    assert repo.cancel_reminder(second.reminder_id) is False


def test_reminders_tool_create_list_cancel(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    tool = RemindersTool(repository=repo)
    context = ToolContext(mode=SocialMode.WORKSHOP)

    created = tool.execute(
        {"action": "create", "text": "revisar el horno", "when": "en 20 minutos"},
        context,
    )
    assert created.success is True
    reminder_id = created.data["reminder_id"]
    due = datetime.fromisoformat(created.data["due_at"])
    assert due.tzinfo is not None
    assert due.astimezone(UTC) > datetime.now(UTC)

    listed = tool.execute({"action": "list", "limit": 10}, context)
    assert listed.success is True
    assert listed.data["count"] == 1

    cancelled = tool.execute({"action": "cancel", "reminder_id": reminder_id}, context)
    assert cancelled.success is True
    assert repo.list_reminders(status="PENDING") == []


def test_reminders_tool_fails_closed_without_repository() -> None:
    result = RemindersTool(repository=None).execute(
        {"action": "create", "text": "algo", "when": "en 5 minutos"},
        ToolContext(),
    )
    assert result.success is False
    assert result.status_code == "UNAVAILABLE"


def test_reminder_service_publishes_due_event_and_marks_notified(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    item = repo.create_reminder("probar recordatorio", "2026-08-24T23:00:00+00:00")
    bus = EventBus()
    seen: list[dict[str, object]] = []
    bus.subscribe(EventType.REMINDER_DUE, lambda event: seen.append(event.payload))
    service = ReminderService(repository=repo, event_bus=bus)

    published = service.poll_once("2026-08-25T00:00:00+00:00")

    assert [r.reminder_id for r in published] == [item.reminder_id]
    assert seen == [
        {
            "reminder_id": item.reminder_id,
            "content": "probar recordatorio",
            "due_at": "2026-08-24T23:00:00+00:00",
        }
    ]
    assert repo.list_due_reminders("2026-08-25T01:00:00+00:00") == []
    assert repo.list_reminders(status="NOTIFIED")[0].reminder_id == item.reminder_id
