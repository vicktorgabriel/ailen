"""Tests for the atomic, content-minimized update operation journal."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from ailen.updates.contracts import (
    OperationRecord,
    UpdateErrorKind,
    UpdateFailure,
    UpdatePhase,
)
from ailen.updates.journal import OperationJournal


def _record(
    operation_id: str = "operation-1",
    phase: UpdatePhase = UpdatePhase.PLANNED,
) -> OperationRecord:
    return OperationRecord(
        schema_version=1,
        operation_id=operation_id,
        phase=phase,
        release_id="ailen-0.4.1-beta.1",
        version="0.4.1-beta.1",
        sequence=401001,
        artifact_hashes=("a" * 64,),
        downloaded_bytes=0,
        total_bytes=1024,
        error_kind=None,
        error_message="",
        started_at="2026-08-31T12:00:00+00:00",
        updated_at="2026-08-31T12:00:00+00:00",
    )


def test_construction_is_side_effect_free(tmp_path: Path) -> None:
    root = tmp_path / "journal"

    OperationJournal(root)

    assert not root.exists()


def test_create_and_read_round_trip_with_private_atomic_file(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    journal = OperationJournal(root)
    record = _record()

    journal.create(record)
    loaded = journal.read(record.operation_id)

    assert loaded == record
    record_path = root / "operation-1.json"
    assert stat.S_IMODE(record_path.stat().st_mode) == 0o600
    assert not list(root.glob("*.tmp"))


def test_duplicate_operation_id_is_rejected_without_overwrite(tmp_path: Path) -> None:
    journal = OperationJournal(tmp_path / "journal")
    original = _record()
    journal.create(original)

    with pytest.raises(UpdateFailure):
        journal.create(replace(original, version="0.4.2"))

    assert journal.read(original.operation_id) == original


@pytest.mark.parametrize("operation_id", ["", ".", "..", "../escape", "/absolute"])
def test_invalid_operation_ids_never_escape_journal_root(
    tmp_path: Path,
    operation_id: str,
) -> None:
    journal = OperationJournal(tmp_path / "journal")

    with pytest.raises(UpdateFailure):
        journal.create(_record(operation_id=operation_id))

    assert not (tmp_path / "escape.json").exists()


def test_all_normal_transitions_are_persisted(tmp_path: Path) -> None:
    journal = OperationJournal(tmp_path / "journal")
    journal.create(_record(phase=UpdatePhase.IDLE))

    expected = UpdatePhase.IDLE
    for phase in (
        UpdatePhase.CHECKING,
        UpdatePhase.PLANNED,
        UpdatePhase.DOWNLOADING,
        UpdatePhase.VERIFIED,
        UpdatePhase.PREPARED,
        UpdatePhase.ACTIVATING,
        UpdatePhase.PROBATION,
        UpdatePhase.ACTIVE,
        UpdatePhase.ROLLING_BACK,
        UpdatePhase.ROLLED_BACK,
    ):
        updated = journal.transition(
            "operation-1",
            expected=frozenset({expected}),
            phase=phase,
            downloaded_bytes=1024 if phase is not UpdatePhase.CHECKING else 0,
        )
        assert updated.phase is phase
        expected = phase

    assert journal.read("operation-1").phase is UpdatePhase.ROLLED_BACK


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (UpdatePhase.PLANNED, UpdatePhase.ACTIVE),
        (UpdatePhase.ACTIVE, UpdatePhase.CANCELLED),
        (UpdatePhase.FAILED, UpdatePhase.PLANNED),
        (UpdatePhase.ROLLED_BACK, UpdatePhase.ACTIVE),
    ],
)
def test_transition_skips_and_terminal_reentry_are_rejected(
    tmp_path: Path,
    start: UpdatePhase,
    target: UpdatePhase,
) -> None:
    journal = OperationJournal(tmp_path / "journal")
    journal.create(_record(phase=start))

    with pytest.raises(UpdateFailure):
        journal.transition(
            "operation-1",
            expected=frozenset({start}),
            phase=target,
        )

    assert journal.read("operation-1").phase is start


def test_expected_phase_prevents_stale_concurrent_transition(tmp_path: Path) -> None:
    journal = OperationJournal(tmp_path / "journal")
    journal.create(_record())

    with pytest.raises(UpdateFailure):
        journal.transition(
            "operation-1",
            expected=frozenset({UpdatePhase.DOWNLOADING}),
            phase=UpdatePhase.VERIFIED,
        )

    assert journal.read("operation-1").phase is UpdatePhase.PLANNED


def test_transition_updates_progress_and_redacted_failure(tmp_path: Path) -> None:
    journal = OperationJournal(tmp_path / "journal")
    journal.create(_record(phase=UpdatePhase.DOWNLOADING))

    downloading = journal.transition(
        "operation-1",
        expected=frozenset({UpdatePhase.DOWNLOADING}),
        phase=UpdatePhase.DOWNLOADING,
        downloaded_bytes=512,
    )
    failed = journal.transition(
        "operation-1",
        expected=frozenset({UpdatePhase.DOWNLOADING}),
        phase=UpdatePhase.FAILED,
        error_kind=UpdateErrorKind.NETWORK,
        error_message="artifact provider unavailable",
    )

    assert downloading.downloaded_bytes == 512
    assert failed.error_kind is UpdateErrorKind.NETWORK
    assert failed.error_message == "artifact provider unavailable"


def test_unknown_operation_is_rejected_without_creating_directory(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    journal = OperationJournal(root)

    with pytest.raises(UpdateFailure):
        journal.read("unknown-operation")

    assert not root.exists()


def test_list_incomplete_excludes_terminal_operations(tmp_path: Path) -> None:
    journal = OperationJournal(tmp_path / "journal")
    for index, phase in enumerate(
        (
            UpdatePhase.DOWNLOADING,
            UpdatePhase.PREPARED,
            UpdatePhase.ACTIVE,
            UpdatePhase.CANCELLED,
            UpdatePhase.FAILED,
        ),
        start=1,
    ):
        journal.create(_record(operation_id=f"operation-{index}", phase=phase))

    incomplete = journal.list_incomplete()

    assert [(record.operation_id, record.phase) for record in incomplete] == [
        ("operation-1", UpdatePhase.DOWNLOADING),
        ("operation-2", UpdatePhase.PREPARED),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        json.dumps({"schema_version": 1, "unexpected": True}).encode("utf-8"),
        b"x" * (64 * 1024 + 1),
    ],
)
def test_corrupt_or_oversized_journal_fails_closed(tmp_path: Path, payload: bytes) -> None:
    root = tmp_path / "journal"
    root.mkdir()
    (root / "operation-1.json").write_bytes(payload)
    journal = OperationJournal(root)

    with pytest.raises(UpdateFailure):
        journal.read("operation-1")


def test_boolean_schema_version_is_not_accepted_as_integer(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    payload = json.loads(OperationJournal._serialize(_record()).decode("utf-8"))
    payload["schema_version"] = True
    (root / "operation-1.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(UpdateFailure):
        OperationJournal(root).read("operation-1")


def test_symlinked_journal_record_is_never_followed(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("private outside content", encoding="utf-8")
    os.symlink(outside, root / "operation-1.json")
    journal = OperationJournal(root)

    with pytest.raises(UpdateFailure):
        journal.read("operation-1")

    assert outside.read_text(encoding="utf-8") == "private outside content"


@pytest.mark.parametrize(
    "unsafe_message",
    [
        "https://private.example.invalid/path",
        "/var/lib/ailen/private.db",
        "Authorization: Bearer synthetic-token",
        "password=synthetic",
    ],
)
def test_journal_rejects_sensitive_error_content(
    tmp_path: Path,
    unsafe_message: str,
) -> None:
    journal = OperationJournal(tmp_path / "journal")

    with pytest.raises(UpdateFailure):
        journal.create(
            replace(
                _record(phase=UpdatePhase.FAILED),
                error_kind=UpdateErrorKind.INTERNAL,
                error_message=unsafe_message,
            )
        )


def test_new_instance_recovers_persisted_incomplete_operation(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    OperationJournal(root).create(_record(phase=UpdatePhase.DOWNLOADING))

    recovered = OperationJournal(root).list_incomplete()

    assert recovered == (_record(phase=UpdatePhase.DOWNLOADING),)
