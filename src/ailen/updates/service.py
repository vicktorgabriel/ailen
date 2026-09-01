"""Bounded unprivileged planning and download lifecycle for updates."""

from __future__ import annotations

import secrets
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from ailen.updates.activation import ActivationResult, PreparedRelease, RollbackResult
from ailen.updates.contracts import (
    ArtifactSpec,
    OperationRecord,
    OperationStatus,
    ReleaseManifest,
    UpdateAdminSnapshot,
    UpdateChannel,
    UpdateCommandResult,
    UpdateErrorKind,
    UpdateFailure,
    UpdatePhase,
)
from ailen.updates.downloader import CancellationToken, DownloadProgress
from ailen.updates.journal import OperationJournal
from ailen.updates.manifest import validate_release_compatibility


class ReleaseSource(Protocol):
    def fetch(self, channel: UpdateChannel) -> ReleaseManifest:
        raise NotImplementedError


class ArtifactDownloader(Protocol):
    def download(
        self,
        spec: ArtifactSpec,
        operation_id: str,
        cancellation: CancellationToken,
        on_progress: Callable[[DownloadProgress], None] | None = None,
    ) -> Path:
        raise NotImplementedError


class ReleasePreparer(Protocol):
    def prepare(
        self,
        artifact_path: Path,
        manifest: ReleaseManifest,
        spec: ArtifactSpec,
    ) -> PreparedRelease:
        raise NotImplementedError


class ReleaseActivationBoundary(Protocol):
    def activate(
        self,
        prepared: PreparedRelease,
        operation_id: str,
        current_db_schema: int,
    ) -> ActivationResult:
        raise NotImplementedError

    def rollback(self, operation_id: str) -> RollbackResult:
        raise NotImplementedError


@dataclass(frozen=True)
class _Approval:
    operation_id: str
    manifest: ReleaseManifest
    fingerprint: tuple[object, ...]
    expires_at: float


class LocalUpdateService:
    """Update-specific implementation of the unprivileged provisioning boundary."""

    _APPROVAL_LIFETIME_SECONDS = 300.0

    def __init__(
        self,
        *,
        source: ReleaseSource,
        downloader: ArtifactDownloader,
        journal: OperationJournal,
        channel: UpdateChannel,
        platform: str,
        config_schema: int,
        current_db_schema: int,
        current_sequence: int,
        installed_version: str,
        mode: str,
        wall_clock: Callable[[], str] | None = None,
        monotonic: Callable[[], float] | None = None,
        operation_id_factory: Callable[[], str] | None = None,
        approval_token_factory: Callable[[], str] | None = None,
        executor_factory: Callable[[], ThreadPoolExecutor] | None = None,
        preparer: ReleasePreparer | None = None,
        activator: ReleaseActivationBoundary | None = None,
    ) -> None:
        self._source = source
        self._downloader = downloader
        self._journal = journal
        self._channel = channel
        self._platform = platform
        self._config_schema = config_schema
        self._current_db_schema = current_db_schema
        self._current_sequence = current_sequence
        self._installed_version = installed_version
        self._mode = mode
        self._wall_clock = wall_clock or (lambda: datetime.now(UTC).isoformat())
        self._monotonic = monotonic or time.monotonic
        self._operation_id_factory = operation_id_factory or (lambda: uuid.uuid4().hex)
        self._approval_token_factory = approval_token_factory or (
            lambda: secrets.token_urlsafe(32)
        )
        self._executor_factory = executor_factory or (
            lambda: ThreadPoolExecutor(max_workers=1, thread_name_prefix="ailen-update")
        )
        self._preparer = preparer
        self._activator = activator
        self._executor: ThreadPoolExecutor | None = None
        self._lock = threading.RLock()
        self._candidate: ReleaseManifest | None = None
        self._candidate_reasons: tuple[str, ...] = ()
        self._approvals: dict[str, _Approval] = {}
        self._cancellations: dict[str, CancellationToken] = {}
        self._live_downloaded: dict[str, int] = {}
        self._prepared: dict[str, PreparedRelease] = {}
        self._recoverable_downloads: dict[str, OperationRecord] = {}
        self._rollback_sequences: dict[str, int] = {}
        self._active_operation_id = ""
        self._latest_operation_id = ""
        self._rollback_operation_id = ""
        self._availability = "UNKNOWN"
        self._detail = "update check has not run"
        self._effective_version = installed_version
        self._rollback_available = False
        self._closed = False
        self._recover_interrupted_operations()

    @staticmethod
    def _fingerprint(manifest: ReleaseManifest) -> tuple[object, ...]:
        return (
            manifest.release_id,
            manifest.sequence,
            tuple(artifact.sha256 for artifact in manifest.artifacts),
            sum(artifact.size_bytes for artifact in manifest.artifacts),
        )

    @staticmethod
    def _status(record: OperationRecord) -> OperationStatus:
        return OperationStatus(
            operation_id=record.operation_id,
            phase=record.phase,
            release_id=record.release_id,
            downloaded_bytes=record.downloaded_bytes,
            total_bytes=record.total_bytes,
            error_kind=record.error_kind,
            error_message=record.error_message,
            started_at=record.started_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _result(
        ok: bool,
        code: str,
        message: str,
        *,
        operation_id: str = "",
        approval_token: str = "",
    ) -> UpdateCommandResult:
        return UpdateCommandResult(
            ok=ok,
            code=code,
            message=message,
            operation_id=operation_id,
            approval_token=approval_token,
        )

    @staticmethod
    def _public_failure_message(kind: UpdateErrorKind) -> str:
        return {
            UpdateErrorKind.CANCELLED: "artifact download cancelled",
            UpdateErrorKind.INTEGRITY: "artifact verification failed",
            UpdateErrorKind.INSUFFICIENT_DISK: "insufficient disk space",
            UpdateErrorKind.NETWORK: "update provider unavailable",
            UpdateErrorKind.SIGNATURE_INVALID: "release signature is invalid",
            UpdateErrorKind.SIGNATURE_UNAVAILABLE: "signature verifier unavailable",
            UpdateErrorKind.INCOMPATIBLE: "release is incompatible",
            UpdateErrorKind.RECOVERY_REQUIRED: "manual recovery required",
            UpdateErrorKind.UNAVAILABLE: "update service unavailable",
            UpdateErrorKind.ACTIVATION: "release activation failed",
            UpdateErrorKind.ROLLBACK_FAILED: "release rollback failed",
        }.get(kind, "update operation failed")

    def _recover_interrupted_operations(self) -> None:
        for record in self._journal.list_incomplete():
            self._latest_operation_id = record.operation_id
            if record.phase in {UpdatePhase.PLANNED, UpdatePhase.DOWNLOADING}:
                self._recoverable_downloads[record.operation_id] = record
                continue
            if record.phase in {
                UpdatePhase.VERIFIED,
                UpdatePhase.PREPARED,
                UpdatePhase.ACTIVATING,
                UpdatePhase.PROBATION,
                UpdatePhase.ROLLING_BACK,
            }:
                self._journal.transition(
                    record.operation_id,
                    expected=frozenset({record.phase}),
                    phase=UpdatePhase.FAILED,
                    error_kind=UpdateErrorKind.RECOVERY_REQUIRED,
                    error_message="manual recovery required",
                )

    def check(self) -> UpdateCommandResult:
        try:
            manifest = self._source.fetch(self._channel)
            reasons = tuple(
                validate_release_compatibility(
                    manifest,
                    platform=self._platform,
                    config_schema=self._config_schema,
                    current_db_schema=self._current_db_schema,
                    current_sequence=self._current_sequence,
                )
            )
        except UpdateFailure as exc:
            public_message = self._public_failure_message(exc.kind)
            with self._lock:
                self._candidate = None
                self._candidate_reasons = ()
                self._approvals.clear()
                self._availability = "UNAVAILABLE"
                self._detail = public_message
            return self._result(False, exc.kind.value.upper(), public_message)
        except Exception:  # noqa: BLE001 - provider boundary becomes typed/redacted
            with self._lock:
                self._candidate = None
                self._candidate_reasons = ()
                self._approvals.clear()
                self._availability = "UNAVAILABLE"
                self._detail = "update provider failed internally"
            return self._result(False, "INTERNAL", "update provider failed internally")

        with self._lock:
            self._candidate = manifest
            self._candidate_reasons = reasons
            if reasons:
                self._availability = "INCOMPATIBLE"
                self._detail = "release is incompatible with this node"
                return self._result(False, "INCOMPATIBLE", self._detail)
            self._availability = "AVAILABLE"
            self._detail = "verified update is available"
            return self._result(True, "UPDATE_AVAILABLE", self._detail)

    def plan(self, release_id: str) -> UpdateCommandResult:
        with self._lock:
            manifest = self._candidate
            if manifest is None:
                return self._result(False, "NOT_CHECKED", "no verified release is available")
            if release_id != manifest.release_id:
                return self._result(False, "RELEASE_NOT_AVAILABLE", "release is not available")
            if self._candidate_reasons:
                return self._result(False, "INCOMPATIBLE", "release is incompatible")

            artifact_hashes = tuple(artifact.sha256 for artifact in manifest.artifacts)
            total_bytes = sum(artifact.size_bytes for artifact in manifest.artifacts)
            for recovered in self._recoverable_downloads.values():
                if (
                    recovered.release_id == manifest.release_id
                    and recovered.version == manifest.version
                    and recovered.sequence == manifest.sequence
                    and recovered.artifact_hashes == artifact_hashes
                    and recovered.total_bytes == total_bytes
                ):
                    approval_token = self._approval_token_factory()
                    self._approvals[approval_token] = _Approval(
                        operation_id=recovered.operation_id,
                        manifest=manifest,
                        fingerprint=self._fingerprint(manifest),
                        expires_at=self._monotonic() + self._APPROVAL_LIFETIME_SECONDS,
                    )
                    self._latest_operation_id = recovered.operation_id
                    return self._result(
                        True,
                        "RESUME_APPROVAL_REQUIRED",
                        "interrupted download awaits renewed approval",
                        operation_id=recovered.operation_id,
                        approval_token=approval_token,
                    )

            operation_id = self._operation_id_factory()
            approval_token = self._approval_token_factory()
            now = self._wall_clock()
            record = OperationRecord(
                schema_version=1,
                operation_id=operation_id,
                phase=UpdatePhase.PLANNED,
                release_id=manifest.release_id,
                version=manifest.version,
                sequence=manifest.sequence,
                artifact_hashes=artifact_hashes,
                downloaded_bytes=0,
                total_bytes=total_bytes,
                error_kind=None,
                error_message="",
                started_at=now,
                updated_at=now,
            )
            self._journal.create(record)
            self._approvals[approval_token] = _Approval(
                operation_id=operation_id,
                manifest=manifest,
                fingerprint=self._fingerprint(manifest),
                expires_at=self._monotonic() + self._APPROVAL_LIFETIME_SECONDS,
            )
            self._latest_operation_id = operation_id
            return self._result(
                True,
                "APPROVAL_REQUIRED",
                "download plan awaits approval",
                operation_id=operation_id,
                approval_token=approval_token,
            )

    def _ensure_executor(self) -> ThreadPoolExecutor:
        if self._executor is None:
            self._executor = self._executor_factory()
        return self._executor

    def start_download(
        self,
        release_id: str,
        approval_token: str,
    ) -> UpdateCommandResult:
        with self._lock:
            if self._closed:
                return self._result(False, "CLOSED", "update service is closed")
            if self._active_operation_id:
                return self._result(False, "BUSY", "another update operation is active")
            approval = self._approvals.pop(approval_token, None)
            if approval is None:
                return self._result(False, "APPROVAL_INVALID", "approval is invalid")
            if self._monotonic() > approval.expires_at:
                return self._result(False, "APPROVAL_EXPIRED", "approval has expired")
            if (
                approval.manifest.release_id != release_id
                or approval.fingerprint != self._fingerprint(approval.manifest)
            ):
                return self._result(False, "APPROVAL_INVALID", "approval is invalid")
            operation_id = approval.operation_id
            record = self._journal.read(operation_id)
            if record.phase not in {UpdatePhase.PLANNED, UpdatePhase.DOWNLOADING}:
                return self._result(False, "INVALID_PHASE", "operation cannot be downloaded")

            cancellation = CancellationToken()
            if record.phase is UpdatePhase.PLANNED:
                self._journal.transition(
                    operation_id,
                    expected=frozenset({UpdatePhase.PLANNED}),
                    phase=UpdatePhase.DOWNLOADING,
                )
            self._recoverable_downloads.pop(operation_id, None)
            self._cancellations[operation_id] = cancellation
            self._live_downloaded[operation_id] = record.downloaded_bytes
            self._active_operation_id = operation_id
            executor = self._ensure_executor()
            try:
                executor.submit(
                    self._run_download,
                    approval.manifest,
                    operation_id,
                    cancellation,
                )
            except Exception:  # noqa: BLE001 - executor boundary becomes typed/redacted
                self._active_operation_id = ""
                self._cancellations.pop(operation_id, None)
                self._live_downloaded.pop(operation_id, None)
                self._journal.transition(
                    operation_id,
                    expected=frozenset({UpdatePhase.DOWNLOADING}),
                    phase=UpdatePhase.FAILED,
                    error_kind=UpdateErrorKind.INTERNAL,
                    error_message="update worker could not start",
                )
                return self._result(False, "INTERNAL", "update worker could not start")
            return self._result(
                True,
                "DOWNLOAD_STARTED",
                "artifact download started",
                operation_id=operation_id,
            )

    def _run_download(
        self,
        manifest: ReleaseManifest,
        operation_id: str,
        cancellation: CancellationToken,
    ) -> None:
        completed_bytes = 0
        downloaded_paths: dict[str, Path] = {}
        try:
            for index, artifact in enumerate(manifest.artifacts, start=1):

                def on_progress(
                    progress: DownloadProgress,
                    *,
                    base: int = completed_bytes,
                ) -> None:
                    with self._lock:
                        self._live_downloaded[operation_id] = base + progress.downloaded_bytes

                downloaded_path = self._downloader.download(
                    artifact,
                    f"{operation_id}-{index}",
                    cancellation,
                    on_progress,
                )
                downloaded_paths[artifact.artifact_id] = downloaded_path
                completed_bytes += artifact.size_bytes
                with self._lock:
                    self._live_downloaded[operation_id] = completed_bytes
                self._journal.transition(
                    operation_id,
                    expected=frozenset({UpdatePhase.DOWNLOADING}),
                    phase=UpdatePhase.DOWNLOADING,
                    downloaded_bytes=completed_bytes,
                )
            self._journal.transition(
                operation_id,
                expected=frozenset({UpdatePhase.DOWNLOADING}),
                phase=UpdatePhase.VERIFIED,
                downloaded_bytes=completed_bytes,
            )
            if self._preparer is not None:
                release_specs = tuple(
                    artifact
                    for artifact in manifest.artifacts
                    if artifact.kind.value == "release"
                )
                if len(release_specs) != 1:
                    raise UpdateFailure(
                        UpdateErrorKind.INTEGRITY,
                        "release manifest must contain exactly one core artifact",
                    )
                if cancellation.cancelled:
                    raise UpdateFailure(
                        UpdateErrorKind.CANCELLED,
                        "artifact download cancelled",
                    )
                release_spec = release_specs[0]
                prepared = self._preparer.prepare(
                    downloaded_paths[release_spec.artifact_id],
                    manifest,
                    release_spec,
                )
                if cancellation.cancelled:
                    raise UpdateFailure(
                        UpdateErrorKind.CANCELLED,
                        "artifact download cancelled",
                    )
                if (
                    prepared.release_id != manifest.release_id
                    or prepared.version != manifest.version
                    or prepared.sequence != manifest.sequence
                    or prepared.artifact_sha256 != release_spec.sha256
                ):
                    raise UpdateFailure(
                        UpdateErrorKind.INTEGRITY,
                        "prepared release metadata mismatch",
                    )
                with self._lock:
                    self._prepared[operation_id] = prepared
                self._journal.transition(
                    operation_id,
                    expected=frozenset({UpdatePhase.VERIFIED}),
                    phase=UpdatePhase.PREPARED,
                    downloaded_bytes=completed_bytes,
                )
        except UpdateFailure as exc:
            phase = (
                UpdatePhase.CANCELLED
                if exc.kind is UpdateErrorKind.CANCELLED
                else UpdatePhase.FAILED
            )
            public_message = self._public_failure_message(exc.kind)
            current = self._journal.read(operation_id)
            if current.phase in {UpdatePhase.DOWNLOADING, UpdatePhase.VERIFIED}:
                self._journal.transition(
                    operation_id,
                    expected=frozenset({current.phase}),
                    phase=phase,
                    downloaded_bytes=max(
                        current.downloaded_bytes,
                        self._live_downloaded.get(operation_id, completed_bytes),
                    ),
                    error_kind=exc.kind,
                    error_message=public_message,
                )
        except Exception:  # noqa: BLE001 - worker boundary becomes typed/redacted
            current = self._journal.read(operation_id)
            if current.phase in {UpdatePhase.DOWNLOADING, UpdatePhase.VERIFIED}:
                self._journal.transition(
                    operation_id,
                    expected=frozenset({current.phase}),
                    phase=UpdatePhase.FAILED,
                    downloaded_bytes=max(
                        current.downloaded_bytes,
                        self._live_downloaded.get(operation_id, completed_bytes),
                    ),
                    error_kind=UpdateErrorKind.INTERNAL,
                    error_message="update worker failed internally",
                )
        finally:
            with self._lock:
                self._cancellations.pop(operation_id, None)
                self._live_downloaded.pop(operation_id, None)
                if self._active_operation_id == operation_id:
                    self._active_operation_id = ""

    def status(self, operation_id: str) -> OperationStatus:
        record = self._journal.read(operation_id)
        with self._lock:
            live_downloaded = self._live_downloaded.get(operation_id)
        if live_downloaded is not None:
            record = replace(record, downloaded_bytes=live_downloaded)
        return self._status(record)

    def cancel(self, operation_id: str) -> UpdateCommandResult:
        with self._lock:
            cancellation = self._cancellations.get(operation_id)
            if cancellation is not None:
                cancellation.cancel()
                return self._result(
                    True,
                    "CANCEL_REQUESTED",
                    "operation cancellation requested",
                    operation_id=operation_id,
                )
            if self._active_operation_id == operation_id:
                return self._result(
                    False,
                    "BUSY",
                    "operation is actively executing",
                    operation_id=operation_id,
                )
            try:
                record = self._journal.read(operation_id)
            except UpdateFailure:
                return self._result(False, "NOT_FOUND", "update operation not found")
            if record.phase in {
                UpdatePhase.CHECKING,
                UpdatePhase.PLANNED,
                UpdatePhase.VERIFIED,
                UpdatePhase.PREPARED,
            }:
                self._journal.transition(
                    operation_id,
                    expected=frozenset({record.phase}),
                    phase=UpdatePhase.CANCELLED,
                    error_kind=UpdateErrorKind.CANCELLED,
                    error_message="operation cancelled",
                )
                return self._result(
                    True,
                    "CANCELLED",
                    "operation cancelled",
                    operation_id=operation_id,
                )
            return self._result(False, "INVALID_PHASE", "operation cannot be cancelled")

    def activate(self, operation_id: str) -> UpdateCommandResult:
        if self._activator is None:
            return self._result(False, "UNAVAILABLE", "release activation is unavailable")
        try:
            record = self._journal.read(operation_id)
        except UpdateFailure:
            return self._result(False, "NOT_FOUND", "update operation not found")
        if record.phase is not UpdatePhase.PREPARED:
            return self._result(False, "INVALID_PHASE", "operation is not prepared")
        with self._lock:
            prepared = self._prepared.get(operation_id)
            if prepared is None:
                return self._result(
                    False,
                    "RECOVERY_REQUIRED",
                    "prepared operation requires recovery",
                    operation_id=operation_id,
                )
            if self._active_operation_id:
                return self._result(False, "BUSY", "another update operation is active")
            self._active_operation_id = operation_id
        try:
            try:
                result = self._activator.activate(
                    prepared,
                    operation_id,
                    self._current_db_schema,
                )
            except Exception:  # noqa: BLE001 - activator boundary is projected safely
                return self._result(
                    False,
                    "INTERNAL",
                    "release activation failed internally",
                    operation_id=operation_id,
                )
            if result.ok:
                with self._lock:
                    self._rollback_sequences[operation_id] = self._current_sequence
                    self._effective_version = result.effective_version
                    self._current_sequence = prepared.sequence
                    self._rollback_operation_id = operation_id
                    self._rollback_available = True
                    self._availability = "UP_TO_DATE"
                    self._detail = "release activated in lab simulation"
                return self._result(
                    True,
                    "ACTIVATED",
                    "release activated",
                    operation_id=operation_id,
                )
            failure = result.failure or UpdateFailure(
                UpdateErrorKind.ACTIVATION,
                "release activation failed",
            )
            with self._lock:
                if result.effective_version:
                    self._effective_version = result.effective_version
                self._rollback_available = False
                self._detail = self._public_failure_message(failure.kind)
            return self._result(
                False,
                failure.kind.value.upper(),
                self._public_failure_message(failure.kind),
                operation_id=operation_id,
            )
        finally:
            with self._lock:
                if self._active_operation_id == operation_id:
                    self._active_operation_id = ""

    def rollback(self) -> UpdateCommandResult:
        if self._activator is None:
            return self._result(False, "UNAVAILABLE", "release rollback is unavailable")
        with self._lock:
            operation_id = self._rollback_operation_id
            if not operation_id:
                return self._result(False, "UNAVAILABLE", "no rollback release is available")
            if self._active_operation_id:
                return self._result(False, "BUSY", "another update operation is active")
            self._active_operation_id = operation_id
        try:
            try:
                record = self._journal.read(operation_id)
            except UpdateFailure:
                return self._result(
                    False,
                    "RECOVERY_REQUIRED",
                    "rollback metadata is unavailable",
                )
            if record.phase is UpdatePhase.ROLLED_BACK:
                return self._result(
                    True,
                    "ALREADY_ROLLED_BACK",
                    "release is already rolled back",
                    operation_id=operation_id,
                )
            if record.phase is not UpdatePhase.ACTIVE:
                return self._result(
                    False,
                    "INVALID_PHASE",
                    "active release cannot be rolled back",
                )
            try:
                result = self._activator.rollback(operation_id)
            except Exception:  # noqa: BLE001 - activator boundary is projected safely
                return self._result(
                    False,
                    "INTERNAL",
                    "release rollback failed internally",
                    operation_id=operation_id,
                )
            if result.ok:
                with self._lock:
                    self._effective_version = result.effective_version
                    self._current_sequence = self._rollback_sequences.get(
                        operation_id,
                        self._current_sequence,
                    )
                    self._rollback_available = False
                    self._availability = "ROLLED_BACK"
                    self._detail = "release rolled back in lab simulation"
                return self._result(
                    True,
                    "ROLLED_BACK",
                    "release rolled back",
                    operation_id=operation_id,
                )
            failure = result.failure or UpdateFailure(
                UpdateErrorKind.ROLLBACK_FAILED,
                "release rollback failed",
            )
            with self._lock:
                self._rollback_available = False
                self._detail = self._public_failure_message(failure.kind)
            return self._result(
                False,
                failure.kind.value.upper(),
                self._public_failure_message(failure.kind),
                operation_id=operation_id,
            )
        finally:
            with self._lock:
                if self._active_operation_id == operation_id:
                    self._active_operation_id = ""

    def snapshot(self) -> UpdateAdminSnapshot:
        with self._lock:
            candidate = self._candidate
            operation_id = self._latest_operation_id
            availability = self._availability
            detail = self._detail
            effective_version = self._effective_version
            rollback_available = self._rollback_available
        operation: OperationStatus | None = None
        if operation_id:
            try:
                operation = self.status(operation_id)
            except UpdateFailure:
                operation = None
        return UpdateAdminSnapshot(
            availability=availability,
            mode=self._mode,
            channel=self._channel,
            installed_version=self._installed_version,
            effective_version=effective_version,
            candidate_version=candidate.version if candidate else "",
            release_notes=candidate.release_notes if candidate else "",
            operation=operation,
            rollback_available=rollback_available,
            detail=detail,
            candidate_release_id=candidate.release_id if candidate else "",
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for cancellation in self._cancellations.values():
                cancellation.cancel()
            executor = self._executor
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)


class DisabledUpdateService:
    """No-I/O implementation that never fabricates updater availability."""

    def __init__(self, *, channel: UpdateChannel, reason: str) -> None:
        self._channel = channel
        self._reason = reason

    def _unavailable(self) -> UpdateCommandResult:
        return UpdateCommandResult(False, "UNAVAILABLE", self._reason)

    def snapshot(self) -> UpdateAdminSnapshot:
        return UpdateAdminSnapshot(
            availability="UNAVAILABLE",
            mode="DISABLED",
            channel=self._channel,
            installed_version="",
            effective_version="",
            candidate_version="",
            release_notes="",
            operation=None,
            rollback_available=False,
            detail=self._reason,
            candidate_release_id="",
        )

    def check(self) -> UpdateCommandResult:
        return self._unavailable()

    def plan(self, release_id: str) -> UpdateCommandResult:
        return self._unavailable()

    def start_download(
        self,
        release_id: str,
        approval_token: str,
    ) -> UpdateCommandResult:
        return self._unavailable()

    def cancel(self, operation_id: str) -> UpdateCommandResult:
        return self._unavailable()

    def activate(self, operation_id: str) -> UpdateCommandResult:
        return self._unavailable()

    def rollback(self) -> UpdateCommandResult:
        return self._unavailable()

    def status(self, operation_id: str) -> OperationStatus:
        raise UpdateFailure(UpdateErrorKind.UNAVAILABLE, self._reason)

    def close(self) -> None:
        return None
