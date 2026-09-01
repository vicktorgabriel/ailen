"""Atomic, redacted persistence for update operation state."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import threading
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ailen.updates.contracts import (
    OperationRecord,
    UpdateErrorKind,
    UpdateFailure,
    UpdatePhase,
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE = re.compile(
    r"(?:[a-z][a-z0-9+.-]*://|(?:^|\s)/[A-Za-z0-9_.-]|authorization\s*:\s*bearer|password\s*=)",
    re.IGNORECASE,
)
_MAX_RECORD_BYTES = 64 * 1024
_FIELDS = frozenset(
    {
        "schema_version",
        "operation_id",
        "phase",
        "release_id",
        "version",
        "sequence",
        "artifact_hashes",
        "downloaded_bytes",
        "total_bytes",
        "error_kind",
        "error_message",
        "started_at",
        "updated_at",
    }
)
_TERMINAL_PHASES = frozenset(
    {
        UpdatePhase.ACTIVE,
        UpdatePhase.ROLLED_BACK,
        UpdatePhase.CANCELLED,
        UpdatePhase.FAILED,
    }
)
_ALLOWED_TRANSITIONS: dict[UpdatePhase, frozenset[UpdatePhase]] = {
    UpdatePhase.IDLE: frozenset({UpdatePhase.CHECKING, UpdatePhase.FAILED}),
    UpdatePhase.CHECKING: frozenset(
        {UpdatePhase.PLANNED, UpdatePhase.CANCELLED, UpdatePhase.FAILED}
    ),
    UpdatePhase.PLANNED: frozenset(
        {UpdatePhase.DOWNLOADING, UpdatePhase.CANCELLED, UpdatePhase.FAILED}
    ),
    UpdatePhase.DOWNLOADING: frozenset(
        {
            UpdatePhase.DOWNLOADING,
            UpdatePhase.VERIFIED,
            UpdatePhase.CANCELLED,
            UpdatePhase.FAILED,
        }
    ),
    UpdatePhase.VERIFIED: frozenset(
        {UpdatePhase.PREPARED, UpdatePhase.CANCELLED, UpdatePhase.FAILED}
    ),
    UpdatePhase.PREPARED: frozenset(
        {UpdatePhase.ACTIVATING, UpdatePhase.CANCELLED, UpdatePhase.FAILED}
    ),
    UpdatePhase.ACTIVATING: frozenset(
        {UpdatePhase.PROBATION, UpdatePhase.ROLLING_BACK, UpdatePhase.FAILED}
    ),
    UpdatePhase.PROBATION: frozenset(
        {UpdatePhase.ACTIVE, UpdatePhase.ROLLING_BACK, UpdatePhase.FAILED}
    ),
    UpdatePhase.ACTIVE: frozenset({UpdatePhase.ROLLING_BACK}),
    UpdatePhase.ROLLING_BACK: frozenset(
        {UpdatePhase.ROLLED_BACK, UpdatePhase.FAILED}
    ),
    UpdatePhase.ROLLED_BACK: frozenset(),
    UpdatePhase.CANCELLED: frozenset(),
    UpdatePhase.FAILED: frozenset(),
}


class _DuplicateKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


class OperationJournal:
    """Store one immutable-shape JSON record per operation."""

    def __init__(self, root: Path, *, clock: Callable[[], str] | None = None) -> None:
        self._configured_root = root
        self._root = root.resolve(strict=False)
        self._clock = clock or (lambda: datetime.now(UTC).isoformat())
        self._lock = threading.RLock()

    @staticmethod
    def _failure(message: str = "update journal integrity check failed") -> UpdateFailure:
        return UpdateFailure(UpdateErrorKind.INTEGRITY, message)

    @staticmethod
    def _validate_identifier(value: str, *, field: str) -> None:
        if _IDENTIFIER.fullmatch(value) is None:
            raise OperationJournal._failure(f"invalid {field}")

    def _validate_root_policy(self) -> None:
        if not self._configured_root.is_absolute():
            raise self._failure("update journal root must be absolute")
        if self._root in {Path("/"), Path.home().resolve(strict=False)}:
            raise self._failure("broad update journal root refused")
        if self._configured_root.is_symlink():
            raise self._failure("update journal root is unsafe")

    def _validate_root(self) -> None:
        try:
            root_stat = self._root.lstat()
        except OSError as exc:
            raise self._failure("update journal unavailable") from exc
        if not stat.S_ISDIR(root_stat.st_mode):
            raise self._failure("update journal root is unsafe")
        if root_stat.st_uid not in {0, os.geteuid()} or stat.S_IMODE(root_stat.st_mode) & 0o022:
            raise self._failure("update journal root permissions are unsafe")

    def _ensure_root(self) -> None:
        self._validate_root_policy()
        if not self._root.exists():
            try:
                self._root.mkdir(mode=0o700, parents=True)
            except OSError as exc:
                raise self._failure("update journal unavailable") from exc
        self._validate_root()

    def _record_path(self, operation_id: str) -> Path:
        self._validate_identifier(operation_id, field="operation_id")
        return self._root / f"{operation_id}.json"

    @staticmethod
    def _validate_timestamp(value: str, *, field: str) -> None:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise OperationJournal._failure(f"invalid {field}") from exc
        if parsed.tzinfo is None:
            raise OperationJournal._failure(f"invalid {field}")

    @classmethod
    def _validate_record(cls, record: OperationRecord) -> None:
        if type(record.schema_version) is not int or record.schema_version != 1:
            raise cls._failure("invalid journal schema_version")
        cls._validate_identifier(record.operation_id, field="operation_id")
        cls._validate_identifier(record.release_id, field="release_id")
        cls._validate_identifier(record.version, field="version")
        if type(record.sequence) is not int or record.sequence <= 0:
            raise cls._failure("invalid release sequence")
        if len(set(record.artifact_hashes)) != len(record.artifact_hashes) or any(
            _SHA256.fullmatch(digest) is None for digest in record.artifact_hashes
        ):
            raise cls._failure("invalid artifact hashes")
        if (
            type(record.downloaded_bytes) is not int
            or type(record.total_bytes) is not int
            or record.downloaded_bytes < 0
            or record.total_bytes < 0
            or record.downloaded_bytes > record.total_bytes
        ):
            raise cls._failure("invalid journal byte counters")
        if len(record.error_message.encode("utf-8")) > 512 or _SENSITIVE.search(
            record.error_message
        ):
            raise cls._failure("unsafe journal error content")
        if any(ord(character) < 32 and character not in "\n\t" for character in record.error_message):
            raise cls._failure("unsafe journal error content")
        cls._validate_timestamp(record.started_at, field="started_at")
        cls._validate_timestamp(record.updated_at, field="updated_at")

    @staticmethod
    def _serialize(record: OperationRecord) -> bytes:
        document = asdict(record)
        document["phase"] = record.phase.value
        document["error_kind"] = record.error_kind.value if record.error_kind else None
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(payload) > _MAX_RECORD_BYTES:
            raise OperationJournal._failure("update journal record is too large")
        return payload

    @classmethod
    def _parse(cls, raw: bytes) -> OperationRecord:
        if len(raw) > _MAX_RECORD_BYTES:
            raise cls._failure("update journal record is too large")
        try:
            document = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey) as exc:
            raise cls._failure("update journal record is corrupt") from exc
        if not isinstance(document, dict) or set(document) != _FIELDS:
            raise cls._failure("update journal record has invalid fields")
        hashes = document["artifact_hashes"]
        if not isinstance(hashes, list) or not all(isinstance(item, str) for item in hashes):
            raise cls._failure("update journal record has invalid hashes")
        try:
            record = OperationRecord(
                schema_version=document["schema_version"],
                operation_id=document["operation_id"],
                phase=UpdatePhase(document["phase"]),
                release_id=document["release_id"],
                version=document["version"],
                sequence=document["sequence"],
                artifact_hashes=tuple(hashes),
                downloaded_bytes=document["downloaded_bytes"],
                total_bytes=document["total_bytes"],
                error_kind=(
                    UpdateErrorKind(document["error_kind"])
                    if document["error_kind"] is not None
                    else None
                ),
                error_message=document["error_message"],
                started_at=document["started_at"],
                updated_at=document["updated_at"],
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise cls._failure("update journal record is corrupt") from exc
        if not all(
            isinstance(value, str)
            for value in (
                record.operation_id,
                record.release_id,
                record.version,
                record.error_message,
                record.started_at,
                record.updated_at,
            )
        ):
            raise cls._failure("update journal record is corrupt")
        cls._validate_record(record)
        return record

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _write(self, record: OperationRecord, *, replace_existing: bool) -> None:
        self._validate_record(record)
        payload = self._serialize(record)
        self._ensure_root()
        target = self._record_path(record.operation_id)
        if not replace_existing and (target.exists() or target.is_symlink()):
            raise self._failure("update operation already exists")
        if target.is_symlink():
            raise self._failure("update journal record is unsafe")
        descriptor, raw_path = tempfile.mkstemp(prefix=f".{record.operation_id}.", dir=self._root)
        temporary = Path(raw_path)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            self._fsync_directory(self._root)
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            temporary.unlink(missing_ok=True)
            raise

    def _read_unlocked(self, operation_id: str) -> OperationRecord:
        path = self._record_path(operation_id)
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if no_follow == 0:
            raise self._failure("safe journal read unavailable")
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | no_follow)
        except OSError as exc:
            raise self._failure("update operation not found") from exc
        try:
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > _MAX_RECORD_BYTES:
                raise self._failure("update journal record is unsafe")
            raw = os.read(descriptor, _MAX_RECORD_BYTES + 1)
        finally:
            os.close(descriptor)
        return self._parse(raw)

    def create(self, record: OperationRecord) -> None:
        with self._lock:
            self._write(record, replace_existing=False)

    def read(self, operation_id: str) -> OperationRecord:
        with self._lock:
            self._validate_root_policy()
            if not self._root.exists():
                raise self._failure("update operation not found")
            self._validate_root()
            return self._read_unlocked(operation_id)

    def transition(
        self,
        operation_id: str,
        *,
        expected: frozenset[UpdatePhase],
        phase: UpdatePhase,
        downloaded_bytes: int | None = None,
        error_kind: UpdateErrorKind | None = None,
        error_message: str = "",
    ) -> OperationRecord:
        with self._lock:
            current = self.read(operation_id)
            if current.phase not in expected:
                raise self._failure("stale update operation phase")
            if phase not in _ALLOWED_TRANSITIONS[current.phase]:
                raise self._failure("invalid update operation transition")
            next_downloaded = (
                current.downloaded_bytes if downloaded_bytes is None else downloaded_bytes
            )
            if next_downloaded < current.downloaded_bytes:
                raise self._failure("update progress cannot decrease")
            updated = replace(
                current,
                phase=phase,
                downloaded_bytes=next_downloaded,
                error_kind=error_kind,
                error_message=error_message,
                updated_at=self._clock(),
            )
            self._write(updated, replace_existing=True)
            return updated

    def list_incomplete(self) -> tuple[OperationRecord, ...]:
        with self._lock:
            self._validate_root_policy()
            if not self._root.exists():
                return ()
            self._validate_root()
            records = tuple(
                self._read_unlocked(path.stem)
                for path in sorted(self._root.glob("*.json"))
            )
            return tuple(record for record in records if record.phase not in _TERMINAL_PHASES)
