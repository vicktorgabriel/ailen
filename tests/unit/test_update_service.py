"""Tests for the bounded unprivileged update planning/download service."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from ailen.updates.activation import ActivationResult, PreparedRelease, RollbackResult
from ailen.updates.contracts import (
    ArtifactKind,
    ArtifactSpec,
    OperationRecord,
    ReleaseManifest,
    UpdateChannel,
    UpdateErrorKind,
    UpdateFailure,
    UpdatePhase,
)
from ailen.updates.downloader import CancellationToken, DownloadProgress
from ailen.updates.journal import OperationJournal
from ailen.updates.service import DisabledUpdateService, LocalUpdateService


def _artifact(index: int = 1, *, size: int = 1024) -> ArtifactSpec:
    return ArtifactSpec(
        artifact_id=f"ailen-core-linux-amd64-{index}",
        kind=ArtifactKind.RELEASE,
        url=f"https://updates.example.invalid/core-{index}.tar.gz",
        sha256=f"{index:x}" * 64,
        size_bytes=size,
        expanded_size_bytes=size * 4,
        platform="linux-amd64",
        media_type="application/gzip",
    )


def _manifest(*artifacts: ArtifactSpec) -> ReleaseManifest:
    selected = artifacts or (_artifact(),)
    return ReleaseManifest(
        schema_version=1,
        release_id="ailen-0.4.1-beta.1",
        version="0.4.1-beta.1",
        sequence=401001,
        channel=UpdateChannel.BETA,
        platforms=("linux-amd64",),
        config_schema_min=1,
        config_schema_max=1,
        migration_from_db_schema_min=4,
        migration_from_db_schema_max=4,
        db_schema_after=4,
        rollback_db_schema_min=4,
        rollback_db_schema_max=4,
        artifacts=tuple(selected),
        release_notes="Synthetic service fixture.",
    )


class _Source:
    def __init__(
        self,
        manifest: ReleaseManifest | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.manifest = manifest or _manifest()
        self.error = error
        self.calls: list[UpdateChannel] = []

    def fetch(self, channel: UpdateChannel) -> ReleaseManifest:
        self.calls.append(channel)
        if self.error is not None:
            raise self.error
        return self.manifest


class _Downloader:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[tuple[str, str]] = []

    def download(
        self,
        spec: ArtifactSpec,
        operation_id: str,
        cancellation: CancellationToken,
        on_progress: Callable[[DownloadProgress], None] | None = None,
    ) -> Path:
        self.calls.append((spec.artifact_id, operation_id))
        if cancellation.cancelled:
            raise UpdateFailure(UpdateErrorKind.CANCELLED, "artifact download cancelled")
        if on_progress is not None:
            on_progress(DownloadProgress(spec.size_bytes // 2, spec.size_bytes))
            on_progress(DownloadProgress(spec.size_bytes, spec.size_bytes))
        return self.root / spec.sha256


class _BlockingDownloader(_Downloader):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.started = threading.Event()
        self.release = threading.Event()

    def download(
        self,
        spec: ArtifactSpec,
        operation_id: str,
        cancellation: CancellationToken,
        on_progress: Callable[[DownloadProgress], None] | None = None,
    ) -> Path:
        self.calls.append((spec.artifact_id, operation_id))
        if on_progress is not None:
            on_progress(DownloadProgress(spec.size_bytes // 2, spec.size_bytes))
        self.started.set()
        while not self.release.wait(0.005):
            if cancellation.cancelled:
                raise UpdateFailure(UpdateErrorKind.CANCELLED, "artifact download cancelled")
        if cancellation.cancelled:
            raise UpdateFailure(UpdateErrorKind.CANCELLED, "artifact download cancelled")
        if on_progress is not None:
            on_progress(DownloadProgress(spec.size_bytes, spec.size_bytes))
        return self.root / spec.sha256


class _Preparer:
    def __init__(self, root: Path, *, error: UpdateFailure | None = None) -> None:
        self.root = root
        self.error = error
        self.calls: list[tuple[Path, str, str]] = []

    def prepare(
        self,
        artifact_path: Path,
        manifest: ReleaseManifest,
        spec: ArtifactSpec,
    ) -> PreparedRelease:
        self.calls.append((artifact_path, manifest.release_id, spec.artifact_id))
        if self.error is not None:
            raise self.error
        return PreparedRelease(
            release_id=manifest.release_id,
            version=manifest.version,
            sequence=manifest.sequence,
            artifact_sha256=spec.sha256,
            release_dir=self.root / "releases" / manifest.version,
            previous_target=self.root / "releases" / "0.4.0",
            db_schema_after=manifest.db_schema_after,
            rollback_db_schema_min=manifest.rollback_db_schema_min,
            rollback_db_schema_max=manifest.rollback_db_schema_max,
        )


class _Activator:
    def __init__(self, journal: OperationJournal) -> None:
        self.journal = journal
        self.activate_calls: list[tuple[PreparedRelease, str, int]] = []
        self.rollback_calls: list[str] = []
        self.activate_failure: UpdateFailure | None = None
        self.rollback_failure: UpdateFailure | None = None

    def activate(
        self,
        prepared: PreparedRelease,
        operation_id: str,
        current_db_schema: int,
    ) -> ActivationResult:
        self.activate_calls.append((prepared, operation_id, current_db_schema))
        if self.activate_failure is not None:
            self.journal.transition(
                operation_id,
                expected=frozenset({UpdatePhase.PREPARED}),
                phase=UpdatePhase.FAILED,
                error_kind=self.activate_failure.kind,
                error_message="release activation failed",
            )
            return ActivationResult(
                False,
                "0.4.0.dev0",
                UpdatePhase.FAILED,
                self.activate_failure,
            )
        self.journal.transition(
            operation_id,
            expected=frozenset({UpdatePhase.PREPARED}),
            phase=UpdatePhase.ACTIVATING,
        )
        self.journal.transition(
            operation_id,
            expected=frozenset({UpdatePhase.ACTIVATING}),
            phase=UpdatePhase.PROBATION,
        )
        self.journal.transition(
            operation_id,
            expected=frozenset({UpdatePhase.PROBATION}),
            phase=UpdatePhase.ACTIVE,
        )
        return ActivationResult(True, prepared.version, UpdatePhase.ACTIVE)

    def rollback(self, operation_id: str) -> RollbackResult:
        self.rollback_calls.append(operation_id)
        if self.rollback_failure is not None:
            self.journal.transition(
                operation_id,
                expected=frozenset({UpdatePhase.ACTIVE}),
                phase=UpdatePhase.ROLLING_BACK,
            )
            self.journal.transition(
                operation_id,
                expected=frozenset({UpdatePhase.ROLLING_BACK}),
                phase=UpdatePhase.FAILED,
                error_kind=self.rollback_failure.kind,
                error_message="release rollback failed",
            )
            return RollbackResult(False, "", UpdatePhase.FAILED, self.rollback_failure)
        self.journal.transition(
            operation_id,
            expected=frozenset({UpdatePhase.ACTIVE}),
            phase=UpdatePhase.ROLLING_BACK,
        )
        self.journal.transition(
            operation_id,
            expected=frozenset({UpdatePhase.ROLLING_BACK}),
            phase=UpdatePhase.ROLLED_BACK,
        )
        return RollbackResult(True, "0.4.0.dev0", UpdatePhase.ROLLED_BACK)


class _BlockingPreparer(_Preparer):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.started = threading.Event()
        self.release = threading.Event()

    def prepare(
        self,
        artifact_path: Path,
        manifest: ReleaseManifest,
        spec: ArtifactSpec,
    ) -> PreparedRelease:
        self.started.set()
        assert self.release.wait(2.0)
        return super().prepare(artifact_path, manifest, spec)


class _BlockingActivator(_Activator):
    def __init__(self, journal: OperationJournal) -> None:
        super().__init__(journal)
        self.started = threading.Event()
        self.release = threading.Event()

    def activate(
        self,
        prepared: PreparedRelease,
        operation_id: str,
        current_db_schema: int,
    ) -> ActivationResult:
        self.started.set()
        assert self.release.wait(2.0)
        return super().activate(prepared, operation_id, current_db_schema)


class _BlockingReadJournal(OperationJournal):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.block_operation_id = ""
        self.started = threading.Event()
        self.release = threading.Event()

    def read(self, operation_id: str) -> OperationRecord:
        if operation_id == self.block_operation_id:
            self.started.set()
            assert self.release.wait(2.0)
        return super().read(operation_id)


class _FakeTime:
    def __init__(self) -> None:
        self.monotonic_value = 1000.0
        self.wall_value = "2026-08-31T12:00:00+00:00"

    def monotonic(self) -> float:
        return self.monotonic_value

    def wall(self) -> str:
        return self.wall_value


def _service(
    tmp_path: Path,
    *,
    source: _Source | None = None,
    downloader: _Downloader | None = None,
    journal: OperationJournal | None = None,
    fake_time: _FakeTime | None = None,
    executor_factory: Callable[[], ThreadPoolExecutor] | None = None,
    preparer: _Preparer | None = None,
    activator: _Activator | None = None,
) -> tuple[LocalUpdateService, _Source, _Downloader, OperationJournal, _FakeTime]:
    clock = fake_time or _FakeTime()
    actual_source = source or _Source()
    actual_downloader = downloader or _Downloader(tmp_path)
    actual_journal = journal or OperationJournal(tmp_path / "journal", clock=clock.wall)
    operation_ids = iter(f"operation-{index}" for index in range(1, 20))
    approval_tokens = iter(f"approval-{index}" for index in range(1, 20))
    service = LocalUpdateService(
        source=actual_source,
        downloader=actual_downloader,
        journal=actual_journal,
        channel=UpdateChannel.BETA,
        platform="linux-amd64",
        config_schema=1,
        current_db_schema=4,
        current_sequence=401000,
        installed_version="0.4.0.dev0",
        mode="LAB_SIMULATION",
        wall_clock=clock.wall,
        monotonic=clock.monotonic,
        operation_id_factory=lambda: next(operation_ids),
        approval_token_factory=lambda: next(approval_tokens),
        executor_factory=executor_factory,
        preparer=preparer,
        activator=activator,
    )
    return service, actual_source, actual_downloader, actual_journal, clock


def _wait_for_phase(
    service: LocalUpdateService,
    operation_id: str,
    phases: frozenset[UpdatePhase],
) -> UpdatePhase:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        phase = service.status(operation_id).phase
        if phase in phases:
            return phase
        time.sleep(0.005)
    raise AssertionError(f"operation did not reach {sorted(item.value for item in phases)}")


def _checked_plan(service: LocalUpdateService) -> tuple[str, str]:
    checked = service.check()
    assert checked.ok is True
    planned = service.plan("ailen-0.4.1-beta.1")
    assert planned.ok is True
    return planned.operation_id, planned.approval_token


def test_check_exposes_only_verified_candidate_metadata(tmp_path: Path) -> None:
    service, source, _, _, _ = _service(tmp_path)

    result = service.check()
    snapshot = service.snapshot()

    assert result.ok is True
    assert result.code == "UPDATE_AVAILABLE"
    assert source.calls == [UpdateChannel.BETA]
    assert snapshot.candidate_version == "0.4.1-beta.1"
    assert snapshot.release_notes == "Synthetic service fixture."
    assert snapshot.availability == "AVAILABLE"
    service.close()


def test_incompatible_release_cannot_be_planned(tmp_path: Path) -> None:
    service, _, _, _, _ = _service(
        tmp_path,
        source=_Source(replace(_manifest(), platforms=("linux-arm64",))),
    )

    checked = service.check()
    planned = service.plan("ailen-0.4.1-beta.1")

    assert checked.ok is False
    assert checked.code == "INCOMPATIBLE"
    assert planned.ok is False
    assert planned.code == "INCOMPATIBLE"
    service.close()


def test_plan_persists_exact_hashes_and_bytes_but_not_approval_token(tmp_path: Path) -> None:
    manifest = _manifest(_artifact(1, size=1024), _artifact(2, size=2048))
    service, _, _, journal, _ = _service(tmp_path, source=_Source(manifest))
    assert service.check().ok is True

    planned = service.plan(manifest.release_id)
    status = service.status(planned.operation_id)
    persisted = journal.read(planned.operation_id)
    journal_text = (tmp_path / "journal" / f"{planned.operation_id}.json").read_text(
        encoding="utf-8"
    )

    assert planned.ok is True
    assert planned.approval_token
    assert status.phase is UpdatePhase.PLANNED
    assert persisted.artifact_hashes == ("1" * 64, "2" * 64)
    assert persisted.total_bytes == 3072
    assert planned.approval_token not in journal_text
    service.close()


def test_approval_token_is_bound_expires_and_is_one_use(tmp_path: Path) -> None:
    fake_time = _FakeTime()
    service, _, downloader, _, _ = _service(tmp_path, fake_time=fake_time)
    operation_id, token = _checked_plan(service)

    wrong = service.start_download("ailen-0.4.1-beta.1", "wrong-token")
    assert wrong.ok is False
    assert downloader.calls == []

    fake_time.monotonic_value += 301.0
    expired = service.start_download("ailen-0.4.1-beta.1", token)
    assert expired.ok is False
    assert expired.code == "APPROVAL_EXPIRED"

    operation_id, token = _checked_plan(service)
    started = service.start_download("ailen-0.4.1-beta.1", token)
    assert started.ok is True
    assert _wait_for_phase(service, operation_id, frozenset({UpdatePhase.VERIFIED})) \
        is UpdatePhase.VERIFIED
    reused = service.start_download("ailen-0.4.1-beta.1", token)
    assert reused.ok is False
    assert reused.code == "APPROVAL_INVALID"
    service.close()


def test_executor_is_lazy_and_only_one_download_runs(tmp_path: Path) -> None:
    created = 0

    def executor_factory() -> ThreadPoolExecutor:
        nonlocal created
        created += 1
        return ThreadPoolExecutor(max_workers=1, thread_name_prefix="ailen-update-test")

    blocking = _BlockingDownloader(tmp_path)
    service, _, _, _, _ = _service(
        tmp_path,
        downloader=blocking,
        executor_factory=executor_factory,
    )
    assert created == 0
    first_operation, first_token = _checked_plan(service)
    assert created == 0
    assert service.start_download("ailen-0.4.1-beta.1", first_token).ok is True
    assert blocking.started.wait(1.0)
    assert created == 1

    second_operation, second_token = _checked_plan(service)
    busy = service.start_download("ailen-0.4.1-beta.1", second_token)
    assert busy.ok is False
    assert busy.code == "BUSY"
    assert service.status(second_operation).phase is UpdatePhase.PLANNED

    blocking.release.set()
    assert _wait_for_phase(service, first_operation, frozenset({UpdatePhase.VERIFIED})) \
        is UpdatePhase.VERIFIED
    service.close()


def test_live_progress_is_visible_without_persisting_every_callback(tmp_path: Path) -> None:
    blocking = _BlockingDownloader(tmp_path)
    service, _, _, journal, _ = _service(tmp_path, downloader=blocking)
    operation_id, token = _checked_plan(service)
    assert service.start_download("ailen-0.4.1-beta.1", token).ok is True
    assert blocking.started.wait(1.0)

    live = service.status(operation_id)
    persisted = journal.read(operation_id)

    assert live.downloaded_bytes == 512
    assert persisted.downloaded_bytes == 0
    blocking.release.set()
    assert _wait_for_phase(service, operation_id, frozenset({UpdatePhase.VERIFIED})) \
        is UpdatePhase.VERIFIED
    assert journal.read(operation_id).downloaded_bytes == 1024
    service.close()


def test_cancel_targets_only_matching_operation_and_worker_finishes_cancelled(
    tmp_path: Path,
) -> None:
    blocking = _BlockingDownloader(tmp_path)
    service, _, _, _, _ = _service(tmp_path, downloader=blocking)
    operation_id, token = _checked_plan(service)
    assert service.start_download("ailen-0.4.1-beta.1", token).ok is True
    assert blocking.started.wait(1.0)

    unknown = service.cancel("operation-999")
    assert unknown.ok is False
    assert service.status(operation_id).phase is UpdatePhase.DOWNLOADING

    cancelled = service.cancel(operation_id)
    assert cancelled.ok is True
    assert _wait_for_phase(service, operation_id, frozenset({UpdatePhase.CANCELLED})) \
        is UpdatePhase.CANCELLED
    service.close()


def test_recovery_preserves_download_and_marks_interrupted_activation(tmp_path: Path) -> None:
    fake_time = _FakeTime()
    journal = OperationJournal(tmp_path / "journal", clock=fake_time.wall)
    downloading = OperationRecord(
        schema_version=1,
        operation_id="operation-1",
        phase=UpdatePhase.DOWNLOADING,
        release_id="ailen-0.4.1-beta.1",
        version="0.4.1-beta.1",
        sequence=401001,
        artifact_hashes=("1" * 64,),
        downloaded_bytes=512,
        total_bytes=1024,
        error_kind=None,
        error_message="",
        started_at=fake_time.wall(),
        updated_at=fake_time.wall(),
    )
    journal.create(downloading)
    journal.create(
        replace(
            downloading,
            operation_id="operation-2",
            phase=UpdatePhase.ACTIVATING,
        )
    )

    service, _, downloader, _, _ = _service(
        tmp_path,
        journal=journal,
        fake_time=fake_time,
    )

    assert service.status("operation-1").phase is UpdatePhase.DOWNLOADING
    recovered = service.status("operation-2")
    assert recovered.phase is UpdatePhase.FAILED
    assert recovered.error_kind is UpdateErrorKind.RECOVERY_REQUIRED
    assert downloader.calls == []

    assert service.check().ok is True
    resumed_plan = service.plan("ailen-0.4.1-beta.1")
    assert resumed_plan.ok is True
    assert resumed_plan.code == "RESUME_APPROVAL_REQUIRED"
    assert resumed_plan.operation_id == "operation-1"
    assert service.start_download(
        "ailen-0.4.1-beta.1",
        resumed_plan.approval_token,
    ).ok is True
    assert _wait_for_phase(service, "operation-1", frozenset({UpdatePhase.VERIFIED})) \
        is UpdatePhase.VERIFIED
    assert downloader.calls == [("ailen-core-linux-amd64-1", "operation-1-1")]
    service.close()


def test_verified_release_is_prepared_before_activation_when_boundary_exists(
    tmp_path: Path,
) -> None:
    preparer = _Preparer(tmp_path)
    service, _, _, journal, _ = _service(tmp_path, preparer=preparer)
    operation_id, token = _checked_plan(service)

    assert service.start_download("ailen-0.4.1-beta.1", token).ok is True
    assert _wait_for_phase(service, operation_id, frozenset({UpdatePhase.PREPARED})) \
        is UpdatePhase.PREPARED

    assert preparer.calls == [
        (
            tmp_path / ("1" * 64),
            "ailen-0.4.1-beta.1",
            "ailen-core-linux-amd64-1",
        )
    ]
    assert journal.read(operation_id).phase is UpdatePhase.PREPARED
    service.close()


def test_prepare_failure_is_typed_redacted_and_never_activates(tmp_path: Path) -> None:
    preparer = _Preparer(
        tmp_path,
        error=UpdateFailure(UpdateErrorKind.INTEGRITY, "secret /private/release.tar.gz"),
    )
    service, _, _, journal, _ = _service(tmp_path, preparer=preparer)
    operation_id, token = _checked_plan(service)

    assert service.start_download("ailen-0.4.1-beta.1", token).ok is True
    assert _wait_for_phase(service, operation_id, frozenset({UpdatePhase.FAILED})) \
        is UpdatePhase.FAILED

    record = journal.read(operation_id)
    assert record.error_kind is UpdateErrorKind.INTEGRITY
    assert record.error_message == "artifact verification failed"
    assert "/private" not in record.error_message
    service.close()


def test_cancellation_during_preparation_finishes_cancelled_not_prepared(
    tmp_path: Path,
) -> None:
    preparer = _BlockingPreparer(tmp_path)
    service, _, _, journal, _ = _service(tmp_path, preparer=preparer)
    operation_id, token = _checked_plan(service)
    assert service.start_download("ailen-0.4.1-beta.1", token).ok is True
    assert preparer.started.wait(1.0)

    cancelled = service.cancel(operation_id)
    preparer.release.set()

    assert cancelled.ok is True
    assert _wait_for_phase(service, operation_id, frozenset({UpdatePhase.CANCELLED})) \
        is UpdatePhase.CANCELLED
    assert journal.read(operation_id).phase is UpdatePhase.CANCELLED
    service.close()


def test_service_activates_only_matching_prepared_operation_and_projects_state(
    tmp_path: Path,
) -> None:
    journal = OperationJournal(tmp_path / "journal")
    preparer = _Preparer(tmp_path)
    activator = _Activator(journal)
    service, _, _, _, _ = _service(
        tmp_path,
        journal=journal,
        preparer=preparer,
        activator=activator,
    )
    missing = service.activate("operation-999")
    operation_id, token = _checked_plan(service)
    not_prepared = service.activate(operation_id)
    assert service.start_download("ailen-0.4.1-beta.1", token).ok is True
    assert _wait_for_phase(service, operation_id, frozenset({UpdatePhase.PREPARED})) \
        is UpdatePhase.PREPARED

    activated = service.activate(operation_id)
    snapshot = service.snapshot()

    assert missing.code == "NOT_FOUND"
    assert not_prepared.code == "INVALID_PHASE"
    assert activated.ok is True
    assert activated.code == "ACTIVATED"
    assert len(activator.activate_calls) == 1
    assert activator.activate_calls[0][1:] == (operation_id, 4)
    assert journal.read(operation_id).phase is UpdatePhase.ACTIVE
    assert snapshot.effective_version == "0.4.1-beta.1"
    assert snapshot.rollback_available is True
    service.close()


def test_activation_failure_is_redacted_and_preserves_activator_phase(
    tmp_path: Path,
) -> None:
    journal = OperationJournal(tmp_path / "journal")
    preparer = _Preparer(tmp_path)
    activator = _Activator(journal)
    activator.activate_failure = UpdateFailure(
        UpdateErrorKind.ACTIVATION,
        "failure at /private/release",
    )
    service, _, _, _, _ = _service(
        tmp_path,
        journal=journal,
        preparer=preparer,
        activator=activator,
    )
    operation_id, token = _checked_plan(service)
    assert service.start_download("ailen-0.4.1-beta.1", token).ok is True
    assert _wait_for_phase(service, operation_id, frozenset({UpdatePhase.PREPARED})) \
        is UpdatePhase.PREPARED

    result = service.activate(operation_id)

    assert result.ok is False
    assert result.code == "ACTIVATION"
    assert result.message == "release activation failed"
    assert "/private" not in result.message
    assert journal.read(operation_id).phase is UpdatePhase.FAILED
    service.close()


def test_cancel_cannot_change_journal_while_activation_is_running(tmp_path: Path) -> None:
    journal = OperationJournal(tmp_path / "journal")
    preparer = _Preparer(tmp_path)
    activator = _BlockingActivator(journal)
    service, _, _, _, _ = _service(
        tmp_path,
        journal=journal,
        preparer=preparer,
        activator=activator,
    )
    operation_id, token = _checked_plan(service)
    assert service.start_download("ailen-0.4.1-beta.1", token).ok is True
    assert _wait_for_phase(service, operation_id, frozenset({UpdatePhase.PREPARED})) \
        is UpdatePhase.PREPARED
    results: list[object] = []
    worker = threading.Thread(target=lambda: results.append(service.activate(operation_id)))
    worker.start()
    assert activator.started.wait(1.0)
    try:
        cancelled = service.cancel(operation_id)
        assert cancelled.ok is False
        assert cancelled.code == "BUSY"
        assert journal.read(operation_id).phase is UpdatePhase.PREPARED
    finally:
        activator.release.set()
        worker.join(2.0)
    assert not worker.is_alive()
    assert journal.read(operation_id).phase is UpdatePhase.ACTIVE
    service.close()


def test_service_manual_rollback_delegates_once_and_updates_effective_version(
    tmp_path: Path,
) -> None:
    journal = OperationJournal(tmp_path / "journal")
    preparer = _Preparer(tmp_path)
    activator = _Activator(journal)
    service, _, _, _, _ = _service(
        tmp_path,
        journal=journal,
        preparer=preparer,
        activator=activator,
    )
    operation_id, token = _checked_plan(service)
    assert service.start_download("ailen-0.4.1-beta.1", token).ok is True
    assert _wait_for_phase(service, operation_id, frozenset({UpdatePhase.PREPARED})) \
        is UpdatePhase.PREPARED
    assert service.activate(operation_id).ok is True

    rolled_back = service.rollback()
    repeated = service.rollback()
    snapshot = service.snapshot()

    assert rolled_back.ok is True
    assert rolled_back.code == "ROLLED_BACK"
    assert repeated.ok is True
    assert repeated.code == "ALREADY_ROLLED_BACK"
    assert activator.rollback_calls == [operation_id]
    assert snapshot.effective_version == "0.4.0.dev0"
    assert snapshot.rollback_available is False
    assert service.check().ok is True
    service.close()


def test_rollback_reserves_worker_before_reading_journal(tmp_path: Path) -> None:
    journal = _BlockingReadJournal(tmp_path / "journal")
    preparer = _Preparer(tmp_path)
    activator = _Activator(journal)
    service, source, _, _, _ = _service(
        tmp_path,
        journal=journal,
        preparer=preparer,
        activator=activator,
    )
    operation_id, token = _checked_plan(service)
    assert service.start_download("ailen-0.4.1-beta.1", token).ok is True
    assert _wait_for_phase(service, operation_id, frozenset({UpdatePhase.PREPARED})) \
        is UpdatePhase.PREPARED
    assert service.activate(operation_id).ok is True
    assert service.check().ok is False  # same sequence is not a new update yet
    newer = replace(_manifest(), sequence=401002, release_id="ailen-0.4.2", version="0.4.2")
    source.manifest = newer
    assert service.check().ok is True
    second = service.plan(newer.release_id)
    assert second.ok is True

    journal.block_operation_id = operation_id
    results: list[object] = []
    worker = threading.Thread(target=lambda: results.append(service.rollback()))
    worker.start()
    assert journal.started.wait(1.0)
    try:
        competing = service.start_download(newer.release_id, second.approval_token)
        assert competing.ok is False
        assert competing.code == "BUSY"
    finally:
        journal.release.set()
        worker.join(2.0)
    assert not worker.is_alive()
    assert activator.rollback_calls == [operation_id]
    service.close()


def test_activation_boundaries_are_unavailable_when_not_configured(tmp_path: Path) -> None:
    service, _, _, _, _ = _service(tmp_path)
    operation_id, token = _checked_plan(service)
    assert service.start_download("ailen-0.4.1-beta.1", token).ok is True
    assert _wait_for_phase(service, operation_id, frozenset({UpdatePhase.VERIFIED})) \
        is UpdatePhase.VERIFIED

    assert service.activate(operation_id).code == "UNAVAILABLE"
    assert service.rollback().code == "UNAVAILABLE"
    service.close()


def test_disabled_service_is_honest_and_performs_no_io(tmp_path: Path) -> None:
    root = tmp_path / "must-not-exist"
    service = DisabledUpdateService(
        channel=UpdateChannel.BETA,
        reason="update source is not configured",
    )

    snapshot = service.snapshot()

    assert snapshot.availability == "UNAVAILABLE"
    assert snapshot.installed_version == ""
    assert service.check().code == "UNAVAILABLE"
    assert service.plan("release").code == "UNAVAILABLE"
    assert service.start_download("release", "token").code == "UNAVAILABLE"
    assert service.cancel("operation").code == "UNAVAILABLE"
    assert service.activate("operation").code == "UNAVAILABLE"
    assert service.rollback().code == "UNAVAILABLE"
    with pytest.raises(UpdateFailure) as caught:
        service.status("operation")
    assert caught.value.kind is UpdateErrorKind.UNAVAILABLE
    assert not root.exists()
    service.close()


def test_unexpected_source_error_is_redacted_as_internal_failure(tmp_path: Path) -> None:
    source = _Source(error=RuntimeError("secret at /private/path?token=value"))
    service, _, _, _, _ = _service(tmp_path, source=source)

    result = service.check()
    snapshot = service.snapshot()

    serialized = json.dumps({"message": result.message, "detail": snapshot.detail})
    assert result.ok is False
    assert result.code == "INTERNAL"
    assert "/private/path" not in serialized
    assert "token=value" not in serialized
    service.close()
