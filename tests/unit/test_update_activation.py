"""Safe extraction and simulated activation tests for signed releases."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import tarfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from ailen.updates.activation import (
    AppliancePaths,
    HealthGateResult,
    ReleaseActivator,
    SafeReleaseExtractor,
)
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
from ailen.updates.journal import OperationJournal


def _write_archive(
    path: Path,
    members: list[tuple[tarfile.TarInfo, bytes]],
) -> None:
    with tarfile.open(path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        for member, content in members:
            archive.addfile(member, io.BytesIO(content) if member.isreg() else None)


def _file(name: str, content: bytes = b"synthetic release\n") -> tuple[tarfile.TarInfo, bytes]:
    member = tarfile.TarInfo(name)
    member.size = len(content)
    member.mode = 0o6777
    member.uid = 1234
    member.gid = 5678
    return member, content


def _directory(name: str) -> tuple[tarfile.TarInfo, bytes]:
    member = tarfile.TarInfo(name)
    member.type = tarfile.DIRTYPE
    member.mode = 0o7777
    return member, b""


def _spec(path: Path, *, expanded_size: int = 4096) -> ArtifactSpec:
    raw = path.read_bytes()
    return ArtifactSpec(
        artifact_id="ailen-core-linux-amd64-0.4.1",
        kind=ArtifactKind.RELEASE,
        url="https://updates.example.invalid/ailen-core.tar.gz",
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        expanded_size_bytes=expanded_size,
        platform="linux-amd64",
        media_type="application/gzip",
    )


def _manifest(
    spec: ArtifactSpec,
    *,
    version: str = "0.4.1-beta.1",
    db_schema_after: int = 4,
    rollback_min: int = 4,
    rollback_max: int = 4,
) -> ReleaseManifest:
    return ReleaseManifest(
        schema_version=1,
        release_id=f"ailen-{version}",
        version=version,
        sequence=401001,
        channel=UpdateChannel.BETA,
        platforms=("linux-amd64",),
        config_schema_min=1,
        config_schema_max=1,
        migration_from_db_schema_min=4,
        migration_from_db_schema_max=4,
        db_schema_after=db_schema_after,
        rollback_db_schema_min=rollback_min,
        rollback_db_schema_max=rollback_max,
        artifacts=(spec,),
        release_notes="Synthetic activation fixture.",
    )


def _paths(tmp_path: Path) -> AppliancePaths:
    return AppliancePaths(
        install_root=tmp_path / "opt" / "ailen",
        state_root=tmp_path / "var" / "lib" / "ailen",
    )


def _prepare(
    tmp_path: Path,
    *,
    members: list[tuple[tarfile.TarInfo, bytes]] | None = None,
    expanded_size: int = 4096,
    manifest_transform: Callable[[ReleaseManifest], ReleaseManifest] | None = None,
):
    archive = tmp_path / "release.tar.gz"
    _write_archive(
        archive,
        members
        or [
            _directory("bin"),
            _file("bin/ailen", b"#!/bin/sh\nexit 0\n"),
            _file("VERSION", b"0.4.1-beta.1\n"),
        ],
    )
    spec = _spec(archive, expanded_size=expanded_size)
    manifest = _manifest(spec)
    if manifest_transform is not None:
        manifest = manifest_transform(manifest)
    paths = _paths(tmp_path)
    prepared = SafeReleaseExtractor().prepare(archive, manifest, spec, paths)
    return prepared, manifest, paths


@pytest.mark.parametrize(
    "unsafe_name",
    ["/absolute", "../escape", "safe/../../escape", "./../escape", "safe\\escape"],
)
def test_extractor_rejects_unsafe_member_paths(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    archive = tmp_path / "unsafe.tar.gz"
    _write_archive(archive, [_file(unsafe_name)])
    spec = _spec(archive)

    with pytest.raises(UpdateFailure) as caught:
        SafeReleaseExtractor().prepare(archive, _manifest(spec), spec, _paths(tmp_path))

    assert caught.value.kind is UpdateErrorKind.INTEGRITY
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize(
    "member_type",
    [
        tarfile.SYMTYPE,
        tarfile.LNKTYPE,
        tarfile.CHRTYPE,
        tarfile.BLKTYPE,
        tarfile.FIFOTYPE,
    ],
)
def test_extractor_rejects_links_devices_and_fifos(
    tmp_path: Path,
    member_type: bytes,
) -> None:
    archive = tmp_path / "unsafe-type.tar.gz"
    member = tarfile.TarInfo("payload")
    member.type = member_type
    member.linkname = "outside"
    _write_archive(archive, [(member, b"")])
    spec = _spec(archive)

    with pytest.raises(UpdateFailure):
        SafeReleaseExtractor().prepare(archive, _manifest(spec), spec, _paths(tmp_path))


def test_extractor_rejects_sparse_metadata(tmp_path: Path) -> None:
    archive = tmp_path / "sparse.tar.gz"
    member, content = _file("payload", b"x")
    member.pax_headers = {"GNU.sparse.map": "0,1"}
    _write_archive(archive, [(member, content)])
    spec = _spec(archive)

    with pytest.raises(UpdateFailure):
        SafeReleaseExtractor().prepare(archive, _manifest(spec), spec, _paths(tmp_path))


def test_extractor_rejects_duplicate_normalized_paths(tmp_path: Path) -> None:
    archive = tmp_path / "duplicates.tar.gz"
    _write_archive(archive, [_file("bin/ailen", b"one"), _file("bin/ailen", b"two")])
    spec = _spec(archive)

    with pytest.raises(UpdateFailure):
        SafeReleaseExtractor().prepare(archive, _manifest(spec), spec, _paths(tmp_path))


def test_extractor_rejects_too_many_members(tmp_path: Path) -> None:
    archive = tmp_path / "too-many.tar.gz"
    _write_archive(
        archive,
        [_file(f"files/{index}", b"") for index in range(10_001)],
    )
    spec = _spec(archive, expanded_size=1)

    with pytest.raises(UpdateFailure):
        SafeReleaseExtractor().prepare(archive, _manifest(spec), spec, _paths(tmp_path))


def test_extractor_rejects_expanded_size_over_manifest_limit(tmp_path: Path) -> None:
    archive = tmp_path / "oversized.tar.gz"
    _write_archive(archive, [_file("payload", b"12345")])
    spec = _spec(archive, expanded_size=4)

    with pytest.raises(UpdateFailure):
        SafeReleaseExtractor().prepare(archive, _manifest(spec), spec, _paths(tmp_path))


def test_extractor_rechecks_artifact_hash_and_manifest_membership(tmp_path: Path) -> None:
    archive = tmp_path / "release.tar.gz"
    _write_archive(archive, [_file("payload")])
    spec = _spec(archive)
    wrong_spec = replace(spec, artifact_id="other-release")

    with pytest.raises(UpdateFailure):
        SafeReleaseExtractor().prepare(archive, _manifest(spec), wrong_spec, _paths(tmp_path))

    archive.write_bytes(archive.read_bytes() + b"tampered")
    with pytest.raises(UpdateFailure):
        SafeReleaseExtractor().prepare(archive, _manifest(spec), spec, _paths(tmp_path))


def test_extractor_commits_atomically_with_conservative_modes(tmp_path: Path) -> None:
    prepared, manifest, paths = _prepare(tmp_path)

    assert prepared.release_id == manifest.release_id
    assert prepared.release_dir == paths.releases_dir / manifest.version
    assert prepared.release_dir.is_dir()
    assert not (paths.releases_dir / f"{manifest.version}.staging").exists()
    assert (prepared.release_dir / "bin" / "ailen").read_bytes().startswith(b"#!/bin/sh")
    assert stat.S_IMODE((prepared.release_dir / "bin").stat().st_mode) == 0o755
    assert stat.S_IMODE((prepared.release_dir / "bin" / "ailen").stat().st_mode) == 0o755
    assert (prepared.release_dir / ".ailen-release.json").is_file()


def test_extractor_is_idempotent_only_for_matching_prepared_release(tmp_path: Path) -> None:
    prepared, manifest, paths = _prepare(tmp_path)
    archive = tmp_path / "release.tar.gz"
    second = SafeReleaseExtractor().prepare(archive, manifest, manifest.artifacts[0], paths)

    assert second == prepared
    marker = prepared.release_dir / ".ailen-release.json"
    marker.chmod(0o600)
    marker.write_text("{}", encoding="utf-8")
    with pytest.raises(UpdateFailure):
        SafeReleaseExtractor().prepare(archive, manifest, manifest.artifacts[0], paths)


def test_appliance_paths_reject_broad_overlapping_and_symlink_roots(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        AppliancePaths(Path("/"), tmp_path / "state").validate()
    with pytest.raises(ValueError):
        AppliancePaths(tmp_path / "same", tmp_path / "same" / "state").validate()

    target = tmp_path / "real"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        AppliancePaths(alias, tmp_path / "state").validate()


class _Preflight:
    def __init__(self, result: HealthGateResult) -> None:
        self.result = result
        self.calls: list[Path] = []

    def check(self, release_dir: Path) -> HealthGateResult:
        self.calls.append(release_dir)
        return self.result


class _Controller:
    def __init__(self, *, fail_starts: int = 0) -> None:
        self.fail_starts = fail_starts
        self.calls: list[tuple[str, Path | None]] = []

    def stop(self) -> None:
        self.calls.append(("stop", None))

    def start(self, release_dir: Path) -> None:
        self.calls.append(("start", release_dir))
        if self.fail_starts:
            self.fail_starts -= 1
            raise RuntimeError("synthetic start failure at /private/path")


class _Health:
    def __init__(self, *results: HealthGateResult) -> None:
        self.results = list(results)
        self.calls: list[float] = []

    def wait_healthy(self, timeout_seconds: float) -> HealthGateResult:
        self.calls.append(timeout_seconds)
        return self.results.pop(0)


def _operation(
    manifest: ReleaseManifest,
    *,
    phase: UpdatePhase = UpdatePhase.PREPARED,
) -> OperationRecord:
    return OperationRecord(
        schema_version=1,
        operation_id="operation-1",
        phase=phase,
        release_id=manifest.release_id,
        version=manifest.version,
        sequence=manifest.sequence,
        artifact_hashes=tuple(item.sha256 for item in manifest.artifacts),
        downloaded_bytes=sum(item.size_bytes for item in manifest.artifacts),
        total_bytes=sum(item.size_bytes for item in manifest.artifacts),
        error_kind=None,
        error_message="",
        started_at="2026-08-31T12:00:00+00:00",
        updated_at="2026-08-31T12:00:00+00:00",
    )


def _activation_fixture(
    tmp_path: Path,
    *,
    preflight: HealthGateResult | None = None,
    health: tuple[HealthGateResult, ...] | None = None,
    manifest_transform: Callable[[ReleaseManifest], ReleaseManifest] | None = None,
    fail_starts: int = 0,
):
    paths = _paths(tmp_path)
    previous = paths.releases_dir / "0.4.0"
    previous.mkdir(mode=0o755, parents=True)
    paths.install_root.mkdir(mode=0o755, parents=True, exist_ok=True)
    paths.install_root.chmod(0o755)
    paths.releases_dir.chmod(0o755)
    previous.chmod(0o755)
    paths.current_link.symlink_to(Path("releases") / previous.name)
    unrelated = paths.install_root / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")
    prepared, manifest, _ = _prepare(
        tmp_path,
        manifest_transform=manifest_transform,
    )
    journal = OperationJournal(tmp_path / "journal")
    journal.create(_operation(manifest))
    actual_preflight = _Preflight(
        preflight or HealthGateResult(True, "PREFLIGHT_OK", "synthetic")
    )
    controller = _Controller(fail_starts=fail_starts)
    actual_health = _Health(
        *(health or (HealthGateResult(True, "HEALTHY", "synthetic"),))
    )
    activator = ReleaseActivator(
        paths=paths,
        journal=journal,
        preflight=actual_preflight,
        controller=controller,
        health=actual_health,
        probation_timeout_seconds=2.0,
    )
    return (
        activator,
        prepared,
        manifest,
        paths,
        journal,
        actual_preflight,
        controller,
        actual_health,
        unrelated,
    )


def _link_target(link: Path) -> Path:
    raw = Path(os.readlink(link))
    return (link.parent / raw).resolve(strict=True)


def _current_target(paths: AppliancePaths) -> Path:
    return _link_target(paths.current_link)


def test_activation_switches_atomically_after_preflight_and_healthy_probation(
    tmp_path: Path,
) -> None:
    (
        activator,
        prepared,
        _,
        paths,
        journal,
        preflight,
        controller,
        health,
        unrelated,
    ) = _activation_fixture(tmp_path)

    result = activator.activate(prepared, "operation-1", current_db_schema=4)

    assert result.ok is True
    assert result.phase is UpdatePhase.ACTIVE
    assert _current_target(paths) == prepared.release_dir
    assert _link_target(paths.rollback_link) == paths.releases_dir / "0.4.0"
    assert preflight.calls == [prepared.release_dir]
    assert controller.calls == [("stop", None), ("start", prepared.release_dir)]
    assert health.calls == [2.0]
    assert journal.read("operation-1").phase is UpdatePhase.ACTIVE
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_preflight_failure_never_stops_or_switches_service(tmp_path: Path) -> None:
    fixture = _activation_fixture(
        tmp_path,
        preflight=HealthGateResult(False, "PREFLIGHT_FAILED", "private detail"),
    )
    activator, prepared, _, paths, journal, _, controller, health, _ = fixture
    previous = _current_target(paths)

    result = activator.activate(prepared, "operation-1", current_db_schema=4)

    assert result.ok is False
    assert result.failure is not None
    assert result.failure.kind is UpdateErrorKind.ACTIVATION
    assert _current_target(paths) == previous
    assert controller.calls == []
    assert health.calls == []
    assert journal.read("operation-1").phase is UpdatePhase.FAILED


def test_unhealthy_candidate_restores_and_restarts_previous_release(tmp_path: Path) -> None:
    fixture = _activation_fixture(
        tmp_path,
        health=(HealthGateResult(False, "HEALTH_FAILED", "synthetic"),),
    )
    activator, prepared, _, paths, journal, _, controller, _, _ = fixture
    previous = _current_target(paths)

    result = activator.activate(prepared, "operation-1", current_db_schema=4)

    assert result.ok is False
    assert result.phase is UpdatePhase.ROLLED_BACK
    assert result.failure is not None
    assert result.failure.kind is UpdateErrorKind.ACTIVATION
    assert _current_target(paths) == previous
    assert controller.calls == [
        ("stop", None),
        ("start", prepared.release_dir),
        ("stop", None),
        ("start", previous),
    ]
    assert journal.read("operation-1").phase is UpdatePhase.ROLLED_BACK


def test_invalid_health_gate_data_still_restores_previous_release(tmp_path: Path) -> None:
    fixture = _activation_fixture(
        tmp_path,
        health=(HealthGateResult(True, "invalid reason", "synthetic"),),
    )
    activator, prepared, _, paths, journal, _, controller, _, _ = fixture
    previous = _current_target(paths)

    result = activator.activate(prepared, "operation-1", current_db_schema=4)

    assert result.ok is False
    assert result.phase is UpdatePhase.ROLLED_BACK
    assert result.failure is not None
    assert result.failure.kind is UpdateErrorKind.ACTIVATION
    assert _current_target(paths) == previous
    assert controller.calls[-2:] == [("stop", None), ("start", previous)]
    assert journal.read("operation-1").phase is UpdatePhase.ROLLED_BACK


@pytest.mark.parametrize("current_schema", [3, 5])
def test_incompatible_database_schema_blocks_before_service_stop(
    tmp_path: Path,
    current_schema: int,
) -> None:
    fixture = _activation_fixture(tmp_path)
    activator, prepared, _, paths, journal, _, controller, _, _ = fixture
    previous = _current_target(paths)

    result = activator.activate(prepared, "operation-1", current_db_schema=current_schema)

    assert result.ok is False
    assert result.failure is not None
    assert result.failure.kind is UpdateErrorKind.INCOMPATIBLE
    assert controller.calls == []
    assert _current_target(paths) == previous
    assert journal.read("operation-1").phase is UpdatePhase.FAILED


def test_manual_rollback_and_repeated_calls_are_idempotent(tmp_path: Path) -> None:
    fixture = _activation_fixture(
        tmp_path,
        health=(
            HealthGateResult(True, "HEALTHY", "synthetic"),
            HealthGateResult(True, "HEALTHY", "synthetic"),
        ),
    )
    activator, prepared, _, paths, journal, _, controller, _, _ = fixture
    previous = paths.releases_dir / "0.4.0"
    activated = activator.activate(prepared, "operation-1", current_db_schema=4)
    repeated_activation = activator.activate(
        prepared,
        "operation-1",
        current_db_schema=4,
    )

    rolled_back = activator.rollback("operation-1")
    calls_after_rollback = list(controller.calls)
    repeated_rollback = activator.rollback("operation-1")

    assert activated.ok is True
    assert repeated_activation.ok is True
    assert rolled_back.ok is True
    assert repeated_rollback.ok is True
    assert controller.calls == calls_after_rollback
    assert _current_target(paths) == previous
    assert journal.read("operation-1").phase is UpdatePhase.ROLLED_BACK


def test_failed_restoration_is_typed_and_preserves_release_directories(tmp_path: Path) -> None:
    fixture = _activation_fixture(tmp_path, fail_starts=2)
    activator, prepared, _, _, journal, _, controller, _, _ = fixture

    result = activator.activate(prepared, "operation-1", current_db_schema=4)

    assert result.ok is False
    assert result.failure is not None
    assert result.failure.kind is UpdateErrorKind.ROLLBACK_FAILED
    assert prepared.release_dir.is_dir()
    assert journal.read("operation-1").phase is UpdatePhase.FAILED
    assert "/private/path" not in journal.read("operation-1").error_message
    assert controller.calls
