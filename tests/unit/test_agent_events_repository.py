"""Repository read of tool audit rows used by the agent admin panel."""
from pathlib import Path

from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.memory.repository import MemoryRepository


def _repo(tmp_path: Path) -> MemoryRepository:
    manager = SQLiteManager(tmp_path / "events.db")
    MigrationRunner(manager).run_migrations()
    return MemoryRepository(manager)


def test_recent_tool_events_newest_first_and_bounded(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert repo.recent_tool_events() == []
    for index in range(5):
        repo.log_tool_event(
            tool_name=f"t{index}", arguments_redacted="{}", result_summary="ok",
            success=True, latency_ms=1.0,
        )
    events = repo.recent_tool_events(3)
    assert [e.tool_name for e in events] == ["t4", "t3", "t2"]
    assert len(repo.recent_tool_events(10_000)) == 5
    assert len(repo.recent_tool_events(0)) == 1
