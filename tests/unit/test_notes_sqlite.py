"""Unit tests for SQLite notes persistence and NotesTool."""

from pathlib import Path

from ailen.domain.enums import ErrorCode
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.memory.repository import MemoryRepository
from ailen.tools.builtin.notes import NotesTool
from ailen.tools.contracts import ToolContext


def test_notes_sqlite_migration_and_crud(tmp_path: Path) -> None:
    db_file = tmp_path / "test_notes.db"
    mgr = SQLiteManager(str(db_file))
    runner = MigrationRunner(mgr)
    applied = runner.run_migrations()
    assert applied >= 3  # Initial + Admin credentials + Notes migrations

    repo = MemoryRepository(mgr)

    # 1. Create note with SQL injection attempt in text
    payload = "Comprar capacitor 22uF'; DROP TABLE notes; --"
    note = repo.create_note(content=payload)
    assert note.note_id.startswith("note-")
    assert note.content == payload

    # 2. List notes
    notes = repo.list_notes(limit=10)
    assert len(notes) == 1
    assert notes[0].content == payload

    # 3. Create second note
    repo.create_note(content="Medir tensión en pin 5")
    all_notes = repo.list_notes(limit=10)
    assert len(all_notes) == 2

    # 4. Search notes
    results = repo.search_notes(query="capacitor")
    assert len(results) == 1
    assert results[0].content == payload

    results_empty = repo.search_notes(query="inexistente")
    assert len(results_empty) == 0


def test_notes_tool_integration(tmp_path: Path) -> None:
    db_file = tmp_path / "test_notes_tool.db"
    mgr = SQLiteManager(str(db_file))
    MigrationRunner(mgr).run_migrations()
    repo = MemoryRepository(mgr)
    tool = NotesTool(repository=repo)

    # Create note
    res_create = tool.execute({"action": "create", "text": "Revisar oscilador de 16MHz"}, ToolContext())
    assert res_create.success is True
    assert "Revisar oscilador" in res_create.message

    # List notes
    res_list = tool.execute({"action": "list"}, ToolContext())
    assert res_list.success is True
    assert res_list.data["count"] == 1

    # Search notes
    res_search = tool.execute({"action": "search", "query": "oscilador"}, ToolContext())
    assert res_search.success is True
    assert res_search.data["count"] == 1


def test_notes_tool_without_repository_fails_closed() -> None:
    tool = NotesTool()

    result = tool.execute(
        {"action": "create", "text": "esto no debe quedar sólo en RAM"},
        ToolContext(),
    )

    assert tool.is_available is False
    assert result.success is False
    assert result.status_code == "UNAVAILABLE"
    assert result.error_code == ErrorCode.TOOL_UNAVAILABLE


def test_notes_search_matches_noncontiguous_meaningful_tokens(tmp_path: Path) -> None:
    mgr = SQLiteManager(str(tmp_path / "token_notes.db"))
    MigrationRunner(mgr).run_migrations()
    repo = MemoryRepository(mgr)
    repo.create_note(content="comprar estaño mañana")

    assert [n.content for n in repo.search_notes("comprar mañana")] == ["comprar estaño mañana"]
    assert [n.content for n in repo.search_notes("qué tengo que comprar mañana")] == ["comprar estaño mañana"]
    assert repo.search_notes("%") == []
