"""Unit tests for the ADR-014 N2 bounded files tool."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ailen.core.config import (
    AILENConfig,
    dump_config_toml,
    load_config,
    save_config,
    validate_config,
)
from ailen.core.confirmation import ConfirmationService
from ailen.core.events import EventBus
from ailen.domain.enums import EventType, PrivacyLevel, SocialMode
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.memory.repository import MemoryRepository
from ailen.tools.builtin.files import MAX_LIST_ENTRIES, MAX_READ_BYTES, FilesTool
from ailen.tools.contracts import AutonomyLevel, ToolContext
from ailen.tools.executor import ToolExecutor
from ailen.tools.registry import ToolRegistry


def _tool(root: Path) -> FilesTool:
    return FilesTool([str(root)])


def _run(tool: FilesTool, action: str, path: str, content: str | None = None):
    args: dict[str, object] = {"action": action, "path": path}
    if content is not None:
        args["content"] = content
    # Direct tool tests exercise I/O after the executor's approval boundary.
    return tool.execute(args, ToolContext(confirmation_id="unit-test-consumed"))


def test_declares_expected_contract() -> None:
    tool = FilesTool(["/tmp"])
    assert tool.autonomy_level is AutonomyLevel.N2
    assert tool.requires_network is False
    assert tool.privacy_level is PrivacyLevel.PRIVATE
    assert tool.allowed_modes == {SocialMode.HOME, SocialMode.WORKSHOP, SocialMode.PRIVATE}
    assert tool.is_side_effecting({"action": "list"}) is False
    assert tool.is_side_effecting({"action": "read"}) is False
    assert tool.is_side_effecting({"action": "create"}) is True
    assert tool.is_side_effecting({"action": "append"}) is True
    assert tool.is_side_effecting({"action": "overwrite"}) is True
    assert tool.requires_confirmation({"action": "overwrite"}) is True
    assert tool.requires_confirmation({"action": "create"}) is False


def test_create_append_read_and_list_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    tool = _tool(root)

    created = _run(tool, "create", "nota.txt", "hola")
    assert created.success is True
    assert (root / "nota.txt").read_text(encoding="utf-8") == "hola"

    appended = _run(tool, "append", "nota.txt", " mundo")
    assert appended.success is True
    assert (root / "nota.txt").read_text(encoding="utf-8") == "hola mundo"

    read = _run(tool, "read", "nota.txt")
    assert read.success is True
    assert read.data["content"] == "hola mundo"

    listing = _run(tool, "list", ".")
    assert listing.success is True
    assert listing.data["count"] == 2
    assert {item["name"] for item in listing.data["entries"]} == {
        "nota.txt", Path(appended.data["backup_path"]).name,
    }


def test_traversal_with_dotdot_is_denied(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.txt").write_text("secreto", encoding="utf-8")

    result = _run(_tool(root), "read", "../outside.txt")

    assert result.success is False
    assert result.status_code == "PATH_DENIED"


def test_symlink_escaping_root_is_denied(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secreto", encoding="utf-8")
    (root / "escape.txt").symlink_to(outside)

    result = _run(_tool(root), "read", "escape.txt")

    assert result.success is False
    assert result.status_code == "PATH_DENIED"


def test_internal_symlink_is_allowed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "real.txt"
    target.write_text("interno", encoding="utf-8")
    (root / "alias.txt").symlink_to("real.txt")

    result = _run(_tool(root), "read", "alias.txt")

    assert result.success is True
    assert result.data["content"] == "interno"


def test_absolute_path_outside_root_is_denied(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secreto", encoding="utf-8")

    result = _run(_tool(root), "read", str(outside))

    assert result.success is False
    assert result.status_code == "PATH_DENIED"


def test_nul_byte_in_path_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    result = _run(_tool(root), "read", "archivo\x00.txt")

    assert result.success is False
    assert result.status_code == "INVALID_ARGS"


def test_fifo_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    fifo = root / "pipe"
    os.mkfifo(fifo)

    result = _run(_tool(root), "read", "pipe")

    assert result.success is False
    assert result.status_code == "UNSAFE_PATH"


def test_file_over_read_limit_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "big.txt").write_bytes(b"a" * (MAX_READ_BYTES + 1))

    result = _run(_tool(root), "read", "big.txt")

    assert result.success is False
    assert result.status_code == "PAYLOAD_TOO_LARGE"


def test_create_does_not_overwrite_existing_file(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "nota.txt").write_text("original", encoding="utf-8")

    result = _run(_tool(root), "create", "nota.txt", "nuevo")

    assert result.success is False
    assert result.status_code == "ALREADY_EXISTS"
    assert (root / "nota.txt").read_text(encoding="utf-8") == "original"


def test_overwrite_creates_sibling_backup(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "nota.txt").write_text("original", encoding="utf-8")

    result = _run(_tool(root), "overwrite", "nota.txt", "nuevo")

    assert result.success is True
    assert (root / "nota.txt").read_text(encoding="utf-8") == "nuevo"
    backups = list(root.glob("nota.txt.ailen-bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "original"
    assert result.data["backup_path"] == str(backups[0])


def test_without_roots_every_action_fails_closed() -> None:
    tool = FilesTool()
    assert tool.is_available is False

    for action in ("list", "read", "create", "append", "overwrite"):
        result = _run(tool, action, "nota.txt", "contenido")
        assert result.success is False
        assert result.status_code == "UNAVAILABLE"


def test_relative_root_is_not_authorized() -> None:
    tool = FilesTool(["relative/root"])
    assert tool.is_available is False


def test_listing_over_entry_limit_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    for index in range(MAX_LIST_ENTRIES + 1):
        (root / f"file-{index}.txt").touch()

    result = _run(_tool(root), "list", ".")

    assert result.success is False
    assert result.status_code == "TOO_MANY_ENTRIES"


def test_invalid_utf8_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "binario.dat").write_bytes(b"\xff\xfe\x00texto")

    result = _run(_tool(root), "read", "binario.dat")

    assert result.success is False
    assert result.status_code == "INVALID_ENCODING"


def test_agent_file_roots_toml_round_trip(tmp_path: Path) -> None:
    cfg = AILENConfig()
    docs = str(tmp_path / "docs")
    notes = str(tmp_path / "notas")
    cfg.agent.file_roots = [docs, notes]

    toml_text = dump_config_toml(cfg)
    assert f'file_roots = ["{docs}", "{notes}"]' in toml_text

    target = tmp_path / "ailen.toml"
    save_config(cfg, target)
    loaded = load_config(target)

    assert loaded.agent.file_roots == cfg.agent.file_roots


def test_agent_file_roots_must_be_absolute() -> None:
    cfg = AILENConfig()
    cfg.agent.file_roots = ["relative/path"]

    assert "agent.file_roots entries must be absolute paths" in validate_config(cfg)


@pytest.mark.parametrize("action", ["read", "append", "overwrite"])
def test_hardlinked_file_cannot_be_read_or_modified(tmp_path: Path, action: str) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside-original", encoding="utf-8")
    os.link(outside, root / "alias.txt")

    result = _run(_tool(root), action, "alias.txt", "changed")

    assert not result.success and result.status_code == "UNSAFE_PATH"
    assert outside.read_text() == "outside-original"
    assert not list(root.glob("*.ailen-bak-*"))


@pytest.mark.parametrize("action", ["read", "append", "overwrite"])
def test_final_symlink_swap_after_resolve_is_rejected(tmp_path: Path, action: str) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "safe.txt"
    target.write_text("safe", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside-original", encoding="utf-8")
    real_open = os.open

    def swap_then_open(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(path) == target:
            target.unlink()
            target.symlink_to(outside)
        return real_open(path, flags, *args, **kwargs)

    with patch("ailen.tools.builtin.files.os.open", side_effect=swap_then_open):
        result = _run(_tool(root), action, "safe.txt", "changed")

    assert not result.success
    assert outside.read_text() == "outside-original"


@pytest.mark.parametrize("action", ["read", "append", "overwrite"])
def test_opened_descriptor_is_used_when_path_changes_after_open(
    tmp_path: Path, action: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "safe.txt"
    moved = root / "moved.txt"
    outside = tmp_path / "outside.txt"
    target.write_text("before")
    outside.write_text("outside-original")
    real_open = os.open

    def open_then_swap(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
        descriptor = real_open(path, flags, *args, **kwargs)
        if Path(path) == target:
            assert flags & os.O_NOFOLLOW
            target.rename(moved)
            os.link(outside, target)
        return descriptor

    with patch("ailen.tools.builtin.files.os.open", side_effect=open_then_swap):
        result = _run(_tool(root), action, "safe.txt", "changed")

    assert result.success
    assert outside.read_text() == "outside-original"
    if action == "read":
        assert result.data["content"] == "before"
    else:
        assert moved.read_text() == ("beforechanged" if action == "append" else "changed")
        assert Path(result.data["backup_path"]).read_text() == "before"


def test_append_existing_backs_up_and_append_missing_creates(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    path = tmp_path / "note.txt"
    assert not tool.requires_confirmation({"action": "append", "path": "note.txt"})
    created = _run(tool, "append", "note.txt", "before")
    assert created.success and "backup_path" not in created.data
    assert tool.requires_confirmation({"action": "append", "path": "note.txt"})

    appended = _run(tool, "append", "note.txt", "-after")

    assert appended.success
    assert path.read_text() == "before-after"
    assert Path(appended.data["backup_path"]).read_text() == "before"


@pytest.mark.parametrize("action", ["append", "overwrite"])
def test_backup_collision_does_not_overwrite_file_or_follow_symlink(
    tmp_path: Path, action: str,
) -> None:
    tool = _tool(tmp_path)
    target = tmp_path / "note.txt"
    target.write_text("before")
    outside = tmp_path / "untouched.txt"
    outside.write_text("outside")
    backup = tmp_path / "note.txt.ailen-bak-fixed-000000000000"
    backup.symlink_to(outside)
    with (
        patch.object(tool, "_backup_timestamp", return_value="fixed"),
        patch("ailen.tools.builtin.files.secrets.token_hex", return_value="000000000000"),
    ):
        result = _run(tool, action, "note.txt", "changed")
    assert not result.success
    assert target.read_text() == "before"
    assert outside.read_text() == "outside"
    assert backup.is_symlink()


def test_backups_are_unique_even_when_timestamp_is_identical(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    (tmp_path / "note.txt").write_text("before")
    with patch.object(tool, "_backup_timestamp", return_value="fixed"):
        first = _run(tool, "overwrite", "note.txt", "middle")
        second = _run(tool, "overwrite", "note.txt", "after")
    assert first.success and second.success
    assert first.data["backup_path"] != second.data["backup_path"]
    assert Path(first.data["backup_path"]).read_text() == "before"
    assert Path(second.data["backup_path"]).read_text() == "middle"


def test_list_stops_consuming_at_entry_limit_before_sorting(tmp_path: Path) -> None:
    yielded = 0

    def many_entries():  # type: ignore[no-untyped-def]
        nonlocal yielded
        for index in range(MAX_LIST_ENTRIES + 1000):
            yielded += 1
            assert yielded <= MAX_LIST_ENTRIES + 1
            yield tmp_path / f"entry-{index}"

    with patch.object(Path, "iterdir", side_effect=many_entries):
        result = _run(_tool(tmp_path), "list", ".")
    assert result.status_code == "TOO_MANY_ENTRIES"
    assert yielded == MAX_LIST_ENTRIES + 1


def test_confirmation_summary_describes_relative_action_without_content(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    summary = tool.confirmation_summary({
        "action": "overwrite", "path": str(tmp_path / "notes.txt"),
        "content": "private-content-marker",
    })
    assert "Sobrescribir" in summary and "notes.txt" in summary
    assert str(tmp_path) not in summary and "private-content-marker" not in summary


def test_create_and_append_content_never_reaches_sqlite_audit(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    db = SQLiteManager(str(tmp_path / "audit.db"))
    MigrationRunner(db).run_migrations()
    service = ConfirmationService()
    executor = ToolExecutor(
        ToolRegistry([_tool(root)]), repository=MemoryRepository(db),
        confirmation_service=service,
    )
    ctx = ToolContext(mode=SocialMode.HOME, max_autonomy=AutonomyLevel.N2)
    created = executor.execute("files", {
        "action": "create", "path": "note.txt", "content": "private-create-content",
    }, ctx)
    assert created.success
    args = {"action": "append", "path": "note.txt", "content": "private-append-content"}
    pending = executor.execute("files", args, ctx)
    assert pending.status_code == "CONFIRMATION_REQUIRED"
    ctx.confirmation_id = pending.data["confirmation_id"]
    assert service.resolve(ctx.confirmation_id, True, "panel")
    assert executor.execute("files", args, ctx).success
    with db.connection() as connection:
        rows = [dict(row) for row in connection.execute(
            "SELECT arguments_redacted, result_summary FROM tool_events",
        ).fetchall()]
    assert len(rows) == 2
    assert "private-create-content" not in str(rows)
    assert "private-append-content" not in str(rows)
    assert all("redact" in row["arguments_redacted"].lower() for row in rows)


def test_file_appearing_after_append_policy_does_not_bypass_confirmation(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    events = EventBus()
    events.subscribe(EventType.TOOL_REQUESTED, lambda _: target.write_text("appeared"))
    executor = ToolExecutor(
        ToolRegistry([_tool(tmp_path)]), event_bus=events,
        confirmation_service=ConfirmationService(),
    )
    result = executor.execute(
        "files", {"action": "append", "path": "note.txt", "content": "unapproved"},
        ToolContext(
            mode=SocialMode.HOME, max_autonomy=AutonomyLevel.N2,
            confirmation_id="forged-id-must-not-be-forwarded",
        ),
    )
    assert result.status_code == "CONFIRMATION_REQUIRED"
    assert target.read_text() == "appeared"
    assert not list(tmp_path.glob("*.ailen-bak-*"))
