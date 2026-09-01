"""Safe release extraction and injected, simulated atomic activation.

This module never invokes systemd and never chooses appliance paths.  The
caller supplies a narrow filesystem boundary plus deterministic preflight,
service and health adapters.  Real privileged activation remains a later
``ailen-updaterd`` vertical.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import stat
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from ailen.updates.contracts import (
    ArtifactKind,
    ArtifactSpec,
    ReleaseManifest,
    UpdateErrorKind,
    UpdateFailure,
    UpdatePhase,
)
from ailen.updates.journal import OperationJournal

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MARKER_NAME = ".ailen-release.json"
_MARKER_FIELDS = frozenset({"schema_version", "release_id", "version", "artifact_sha256"})
_MAX_MARKER_BYTES = 2048
_MAX_MEMBERS = 10_000
_CHUNK_BYTES = 64 * 1024
_SUPPORTED_MEDIA_TYPES = frozenset(
    {"application/gzip", "application/x-gzip", "application/x-tar"}
)


@dataclass(frozen=True)
class AppliancePaths:
    """Injected release/state roots; no production path is implicit."""

    install_root: Path
    state_root: Path

    @property
    def releases_dir(self) -> Path:
        return self.install_root / "releases"

    @property
    def current_link(self) -> Path:
        return self.install_root / "current"

    @property
    def rollback_link(self) -> Path:
        return self.install_root / "rollback"

    @property
    def data_dir(self) -> Path:
        return self.state_root

    def validate(self) -> None:
        if not self.install_root.is_absolute() or not self.state_root.is_absolute():
            raise ValueError("update roots must be absolute")
        install = self.install_root.resolve(strict=False)
        state = self.state_root.resolve(strict=False)
        home = Path.home().resolve(strict=False)
        if install in {Path("/"), home} or state in {Path("/"), home}:
            raise ValueError("broad update root refused")
        if install == state or install.is_relative_to(state) or state.is_relative_to(install):
            raise ValueError("install and state roots must be disjoint")
        for configured, resolved in (
            (self.install_root, install),
            (self.state_root, state),
        ):
            if configured.is_symlink() or configured.absolute() != resolved:
                raise ValueError("symlinked update root refused")


@dataclass(frozen=True)
class PreparedRelease:
    release_id: str
    version: str
    sequence: int
    artifact_sha256: str
    release_dir: Path
    previous_target: Path | None
    db_schema_after: int
    rollback_db_schema_min: int
    rollback_db_schema_max: int


@dataclass(frozen=True)
class HealthGateResult:
    healthy: bool
    reason_code: str
    detail: str


@dataclass(frozen=True)
class ActivationResult:
    ok: bool
    effective_version: str
    phase: UpdatePhase
    failure: UpdateFailure | None = None


@dataclass(frozen=True)
class RollbackResult:
    ok: bool
    effective_version: str
    phase: UpdatePhase
    failure: UpdateFailure | None = None


class PreflightGate(Protocol):
    def check(self, release_dir: Path) -> HealthGateResult:
        raise NotImplementedError


class ServiceController(Protocol):
    def stop(self) -> None:
        raise NotImplementedError

    def start(self, release_dir: Path) -> None:
        raise NotImplementedError


class HealthGate(Protocol):
    def wait_healthy(self, timeout_seconds: float) -> HealthGateResult:
        raise NotImplementedError


def _integrity(message: str) -> UpdateFailure:
    return UpdateFailure(UpdateErrorKind.INTEGRITY, message)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_owned_directory(path: Path) -> None:
    try:
        value = path.lstat()
    except OSError as exc:
        raise _integrity("release directory unavailable") from exc
    if not stat.S_ISDIR(value.st_mode) or value.st_uid not in {0, os.geteuid()}:
        raise _integrity("release directory is unsafe")
    if stat.S_IMODE(value.st_mode) & 0o022:
        raise _integrity("release directory permissions are unsafe")


def _bounded_fd_digest(descriptor: int, expected_size: int) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while total <= expected_size:
        chunk = os.read(descriptor, min(_CHUNK_BYTES, expected_size + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        digest.update(chunk)
    if total != expected_size or os.read(descriptor, 1):
        raise _integrity("release artifact size verification failed")
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest()


def _read_release_link(paths: AppliancePaths, link: Path, *, missing_ok: bool) -> Path | None:
    if not link.exists() and not link.is_symlink():
        if missing_ok:
            return None
        raise _integrity("release link is unavailable")
    try:
        link_stat = link.lstat()
        if not stat.S_ISLNK(link_stat.st_mode):
            raise _integrity("release link is unsafe")
        raw_target = Path(os.readlink(link))
        target = (
            raw_target
            if raw_target.is_absolute()
            else link.parent / raw_target
        ).resolve(strict=True)
        releases = paths.releases_dir.resolve(strict=True)
        target_stat = target.lstat()
    except (OSError, RuntimeError) as exc:
        raise _integrity("release link is unsafe") from exc
    if target.parent != releases or not stat.S_ISDIR(target_stat.st_mode):
        raise _integrity("release link target is unsafe")
    return target


class SafeReleaseExtractor:
    """Compile a verified tar artifact into one immutable release directory."""

    @staticmethod
    def _validate_spec(manifest: ReleaseManifest, spec: ArtifactSpec) -> None:
        if spec not in manifest.artifacts or spec.kind is not ArtifactKind.RELEASE:
            raise _integrity("release artifact is not declared by manifest")
        if spec.media_type not in _SUPPORTED_MEDIA_TYPES:
            raise _integrity("release artifact media type is unsupported")
        if _IDENTIFIER.fullmatch(manifest.release_id) is None or _IDENTIFIER.fullmatch(
            manifest.version
        ) is None:
            raise _integrity("release identity is invalid")
        if type(spec.expanded_size_bytes) is not int or spec.expanded_size_bytes <= 0:
            raise _integrity("release expanded size is invalid")

    @staticmethod
    def _open_verified_artifact(artifact_path: Path, spec: ArtifactSpec) -> tuple[int, os.stat_result]:
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if no_follow == 0:
            raise _integrity("safe release artifact open unavailable")
        try:
            descriptor = os.open(
                artifact_path,
                os.O_RDONLY | os.O_NONBLOCK | no_follow | getattr(os, "O_CLOEXEC", 0),
            )
            initial = os.fstat(descriptor)
        except OSError as exc:
            raise _integrity("release artifact is unavailable") from exc
        try:
            if not stat.S_ISREG(initial.st_mode) or initial.st_size != spec.size_bytes:
                raise _integrity("release artifact is unsafe")
            actual = _bounded_fd_digest(descriptor, spec.size_bytes)
            if not hmac.compare_digest(actual, spec.sha256):
                raise _integrity("release artifact digest verification failed")
            return descriptor, initial
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _member_parts(member: tarfile.TarInfo) -> tuple[str, ...]:
        name = member.name
        if (
            not name
            or "\\" in name
            or "\x00" in name
            or any(ord(character) < 32 for character in name)
        ):
            raise _integrity("release archive member path is unsafe")
        pure = PurePosixPath(name)
        if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
            raise _integrity("release archive member path is unsafe")
        return pure.parts

    @staticmethod
    def _is_sparse(member: tarfile.TarInfo) -> bool:
        return member.sparse is not None or any(
            key.startswith(("GNU.sparse", "SCHILY.realsize"))
            for key in member.pax_headers
        )

    @classmethod
    def _scan_members(
        cls,
        archive: tarfile.TarFile,
        spec: ArtifactSpec,
    ) -> list[tuple[tarfile.TarInfo, tuple[str, ...]]]:
        selected: list[tuple[tarfile.TarInfo, tuple[str, ...]]] = []
        kinds: dict[tuple[str, ...], str] = {}
        expanded = 0
        while True:
            try:
                member = archive.next()
            except (tarfile.TarError, OSError) as exc:
                raise _integrity("release archive is corrupt") from exc
            if member is None:
                break
            if len(selected) >= _MAX_MEMBERS:
                raise _integrity("release archive has too many members")
            parts = cls._member_parts(member)
            if parts in kinds:
                raise _integrity("release archive has duplicate members")
            if cls._is_sparse(member) or not (member.isdir() or member.isreg()):
                raise _integrity("release archive member type is unsafe")
            if type(member.size) is not int or member.size < 0:
                raise _integrity("release archive member size is invalid")
            kind = "directory" if member.isdir() else "file"
            if member.isdir() and member.size != 0:
                raise _integrity("release archive directory is malformed")
            if member.isreg():
                expanded += member.size
                if expanded > spec.expanded_size_bytes:
                    raise _integrity("release archive exceeds expanded size")
            kinds[parts] = kind
            selected.append((member, parts))

        for parts, kind in kinds.items():
            for depth in range(1, len(parts)):
                if kinds.get(parts[:depth]) == "file":
                    raise _integrity("release archive path collision")
            if kind == "file" and any(
                other[: len(parts)] == parts and len(other) > len(parts) for other in kinds
            ):
                raise _integrity("release archive path collision")
        return selected

    @staticmethod
    def _safe_child(root: Path, parts: tuple[str, ...]) -> Path:
        child = root.joinpath(*parts)
        resolved_root = root.resolve(strict=True)
        resolved_child = child.resolve(strict=False)
        if not resolved_child.is_relative_to(resolved_root):
            raise _integrity("release archive path escaped staging")
        return child

    @classmethod
    def _create_directories(
        cls,
        staging: Path,
        members: list[tuple[tarfile.TarInfo, tuple[str, ...]]],
    ) -> None:
        directories: set[tuple[str, ...]] = set()
        for member, parts in members:
            if member.isdir():
                directories.add(parts)
            for depth in range(1, len(parts)):
                directories.add(parts[:depth])
        for parts in sorted(directories, key=lambda item: (len(item), item)):
            directory = cls._safe_child(staging, parts)
            try:
                directory.mkdir(mode=0o755, exist_ok=True)
                value = directory.lstat()
                if not stat.S_ISDIR(value.st_mode):
                    raise _integrity("release archive directory is unsafe")
                directory.chmod(0o755)
            except OSError as exc:
                raise _integrity("release archive directory could not be created") from exc

    @classmethod
    def _extract_files(
        cls,
        archive: tarfile.TarFile,
        staging: Path,
        members: list[tuple[tarfile.TarInfo, tuple[str, ...]]],
    ) -> None:
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if no_follow == 0:
            raise _integrity("safe release extraction unavailable")
        for member, parts in members:
            if not member.isreg():
                continue
            destination = cls._safe_child(staging, parts)
            source = archive.extractfile(member)
            if source is None:
                raise _integrity("release archive file is unreadable")
            mode = 0o755 if member.mode & 0o111 else 0o644
            try:
                descriptor = os.open(
                    destination,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | no_follow
                    | getattr(os, "O_CLOEXEC", 0),
                    mode,
                )
            except OSError as exc:
                source.close()
                raise _integrity("release archive file could not be created") from exc
            written = 0
            try:
                os.fchmod(descriptor, mode)
                while written < member.size:
                    chunk = source.read(min(_CHUNK_BYTES, member.size - written))
                    if not chunk:
                        raise _integrity("release archive file is truncated")
                    offset = 0
                    while offset < len(chunk):
                        offset += os.write(descriptor, chunk[offset:])
                    written += len(chunk)
                if source.read(1):
                    raise _integrity("release archive file exceeds declared size")
                os.fsync(descriptor)
            except OSError as exc:
                raise _integrity("release archive file extraction failed") from exc
            finally:
                source.close()
                os.close(descriptor)

    @staticmethod
    def _marker_payload(manifest: ReleaseManifest, spec: ArtifactSpec) -> bytes:
        return json.dumps(
            {
                "artifact_sha256": spec.sha256,
                "release_id": manifest.release_id,
                "schema_version": 1,
                "version": manifest.version,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @classmethod
    def _write_marker(
        cls,
        staging: Path,
        manifest: ReleaseManifest,
        spec: ArtifactSpec,
    ) -> None:
        path = staging / _MARKER_NAME
        payload = cls._marker_payload(manifest, spec)
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o444,
        )
        try:
            os.fchmod(descriptor, 0o444)
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @classmethod
    def _marker_matches(
        cls,
        release_dir: Path,
        manifest: ReleaseManifest,
        spec: ArtifactSpec,
    ) -> bool:
        marker = release_dir / _MARKER_NAME
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if no_follow == 0:
            return False
        try:
            descriptor = os.open(marker, os.O_RDONLY | os.O_NONBLOCK | no_follow)
            marker_stat = os.fstat(descriptor)
            if not stat.S_ISREG(marker_stat.st_mode) or marker_stat.st_size > _MAX_MARKER_BYTES:
                return False
            raw = os.read(descriptor, _MAX_MARKER_BYTES + 1)
        except OSError:
            return False
        finally:
            if "descriptor" in locals():
                os.close(descriptor)
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        return (
            isinstance(document, dict)
            and set(document) == _MARKER_FIELDS
            and type(document["schema_version"]) is int
            and document["schema_version"] == 1
            and document["release_id"] == manifest.release_id
            and document["version"] == manifest.version
            and document["artifact_sha256"] == spec.sha256
        )

    @staticmethod
    def _ensure_install_dirs(paths: AppliancePaths) -> None:
        paths.validate()
        try:
            paths.install_root.mkdir(mode=0o755, parents=True, exist_ok=True)
            paths.releases_dir.mkdir(mode=0o755, exist_ok=True)
        except OSError as exc:
            raise _integrity("release installation root is unavailable") from exc
        _validate_owned_directory(paths.install_root)
        _validate_owned_directory(paths.releases_dir)

    def prepare(
        self,
        artifact_path: Path,
        manifest: ReleaseManifest,
        spec: ArtifactSpec,
        paths: AppliancePaths,
    ) -> PreparedRelease:
        self._validate_spec(manifest, spec)
        paths.validate()
        descriptor, initial = self._open_verified_artifact(artifact_path, spec)
        staging: Path | None = None
        try:
            self._ensure_install_dirs(paths)
            previous = _read_release_link(paths, paths.current_link, missing_ok=True)
            release_dir = paths.releases_dir / manifest.version
            if release_dir.exists() or release_dir.is_symlink():
                try:
                    release_stat = release_dir.lstat()
                except OSError as exc:
                    raise _integrity("prepared release is unsafe") from exc
                if not stat.S_ISDIR(release_stat.st_mode) or not self._marker_matches(
                    release_dir, manifest, spec
                ):
                    raise _integrity("prepared release conflicts with existing content")
                return PreparedRelease(
                    manifest.release_id,
                    manifest.version,
                    manifest.sequence,
                    spec.sha256,
                    release_dir,
                    previous,
                    manifest.db_schema_after,
                    manifest.rollback_db_schema_min,
                    manifest.rollback_db_schema_max,
                )

            staging = paths.releases_dir / f"{manifest.version}.staging"
            if staging.exists() or staging.is_symlink():
                raise _integrity("release staging directory already exists")
            staging.mkdir(mode=0o700)
            _validate_owned_directory(staging)

            os.lseek(descriptor, 0, os.SEEK_SET)
            with os.fdopen(os.dup(descriptor), "rb") as handle:
                try:
                    with tarfile.open(fileobj=handle, mode="r:*") as archive:
                        members = self._scan_members(archive, spec)
                        self._create_directories(staging, members)
                        self._extract_files(archive, staging, members)
                except (tarfile.TarError, EOFError, OSError) as exc:
                    raise _integrity("release archive is corrupt") from exc

            final_digest = _bounded_fd_digest(descriptor, spec.size_bytes)
            final_stat = os.fstat(descriptor)
            if (
                not hmac.compare_digest(final_digest, spec.sha256)
                or final_stat.st_ino != initial.st_ino
                or final_stat.st_dev != initial.st_dev
                or final_stat.st_size != initial.st_size
                or final_stat.st_mtime_ns != initial.st_mtime_ns
            ):
                raise _integrity("release artifact changed during extraction")
            self._write_marker(staging, manifest, spec)
            staging.chmod(0o755)
            _fsync_directory(staging)
            os.rename(staging, release_dir)
            staging = None
            _fsync_directory(paths.releases_dir)
            return PreparedRelease(
                manifest.release_id,
                manifest.version,
                manifest.sequence,
                spec.sha256,
                release_dir,
                previous,
                manifest.db_schema_after,
                manifest.rollback_db_schema_min,
                manifest.rollback_db_schema_max,
            )
        except ValueError as exc:
            raise _integrity("release path policy rejected configuration") from exc
        except OSError as exc:
            raise _integrity("release preparation failed") from exc
        finally:
            os.close(descriptor)
            if staging is not None and staging.exists() and not staging.is_symlink():
                shutil.rmtree(staging)


class ReleaseActivator:
    """Atomic activation against injected Lab-only service and health gates."""

    def __init__(
        self,
        *,
        paths: AppliancePaths,
        journal: OperationJournal,
        preflight: PreflightGate,
        controller: ServiceController,
        health: HealthGate,
        probation_timeout_seconds: float,
    ) -> None:
        paths.validate()
        if probation_timeout_seconds <= 0 or probation_timeout_seconds > 300:
            raise ValueError("invalid probation timeout")
        self._paths = paths
        self._journal = journal
        self._preflight = preflight
        self._controller = controller
        self._health = health
        self._probation_timeout_seconds = probation_timeout_seconds

    @staticmethod
    def _failure(kind: UpdateErrorKind, message: str) -> UpdateFailure:
        return UpdateFailure(kind, message)

    @staticmethod
    def _validate_gate(result: HealthGateResult) -> None:
        if type(result.healthy) is not bool or _REASON_CODE.fullmatch(result.reason_code) is None:
            raise UpdateFailure(UpdateErrorKind.ACTIVATION, "activation gate returned invalid data")

    def _validate_prepared(self, prepared: PreparedRelease, operation_id: str) -> None:
        record = self._journal.read(operation_id)
        if record.release_id != prepared.release_id or record.version != prepared.version:
            raise self._failure(UpdateErrorKind.INCOMPATIBLE, "prepared release does not match operation")
        release_dir = prepared.release_dir.resolve(strict=True)
        releases = self._paths.releases_dir.resolve(strict=True)
        if release_dir.parent != releases or release_dir.name != prepared.version:
            raise self._failure(UpdateErrorKind.INTEGRITY, "prepared release path is unsafe")
        release_stat = release_dir.lstat()
        if not stat.S_ISDIR(release_stat.st_mode):
            raise self._failure(UpdateErrorKind.INTEGRITY, "prepared release path is unsafe")

    def _atomic_link(self, link: Path, target: Path, operation_id: str) -> None:
        releases = self._paths.releases_dir.resolve(strict=True)
        resolved_target = target.resolve(strict=True)
        if resolved_target.parent != releases or not resolved_target.is_dir():
            raise self._failure(UpdateErrorKind.INTEGRITY, "activation target is unsafe")
        if link.exists() and not link.is_symlink():
            raise self._failure(UpdateErrorKind.INTEGRITY, "activation link is unsafe")
        temporary = link.parent / f".{link.name}.{operation_id}.tmp"
        if temporary.exists() or temporary.is_symlink():
            raise self._failure(UpdateErrorKind.RECOVERY_REQUIRED, "stale activation link requires recovery")
        relative_target = resolved_target.relative_to(link.parent.resolve(strict=True))
        try:
            temporary.symlink_to(relative_target, target_is_directory=True)
            os.replace(temporary, link)
            _fsync_directory(link.parent)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise self._failure(UpdateErrorKind.ACTIVATION, "atomic release switch failed") from exc

    def _set_rollback_link(self, target: Path | None, operation_id: str) -> None:
        link = self._paths.rollback_link
        if target is None:
            if link.exists() and not link.is_symlink():
                raise self._failure(UpdateErrorKind.INTEGRITY, "rollback link is unsafe")
            if link.is_symlink():
                link.unlink()
                _fsync_directory(link.parent)
            return
        self._atomic_link(link, target, operation_id)

    def _transition_failure(
        self,
        operation_id: str,
        expected: frozenset[UpdatePhase],
        failure: UpdateFailure,
    ) -> None:
        self._journal.transition(
            operation_id,
            expected=expected,
            phase=UpdatePhase.FAILED,
            error_kind=failure.kind,
            error_message=failure.public_message,
        )

    def _restore_previous(
        self,
        prepared: PreparedRelease,
        operation_id: str,
        original_failure: UpdateFailure,
        phase: UpdatePhase,
    ) -> ActivationResult:
        previous = prepared.previous_target
        try:
            self._journal.transition(
                operation_id,
                expected=frozenset({phase}),
                phase=UpdatePhase.ROLLING_BACK,
            )
            self._controller.stop()
            if previous is None:
                raise self._failure(
                    UpdateErrorKind.ROLLBACK_FAILED,
                    "no previous release is available",
                )
            self._atomic_link(self._paths.current_link, previous, operation_id)
            self._controller.start(previous)
            self._journal.transition(
                operation_id,
                expected=frozenset({UpdatePhase.ROLLING_BACK}),
                phase=UpdatePhase.ROLLED_BACK,
                error_kind=original_failure.kind,
                error_message=original_failure.public_message,
            )
            return ActivationResult(
                False,
                previous.name,
                UpdatePhase.ROLLED_BACK,
                original_failure,
            )
        except Exception as exc:  # noqa: BLE001 - activation boundary is projected safely
            failure = self._failure(UpdateErrorKind.ROLLBACK_FAILED, "release rollback failed")
            try:
                current = self._journal.read(operation_id)
                if current.phase is UpdatePhase.ROLLING_BACK:
                    self._transition_failure(
                        operation_id,
                        frozenset({UpdatePhase.ROLLING_BACK}),
                        failure,
                    )
            except UpdateFailure:
                pass
            _ = exc
            return ActivationResult(False, "", UpdatePhase.FAILED, failure)

    def activate(
        self,
        prepared: PreparedRelease,
        operation_id: str,
        current_db_schema: int,
    ) -> ActivationResult:
        try:
            self._validate_prepared(prepared, operation_id)
            record = self._journal.read(operation_id)
            if record.phase is UpdatePhase.ACTIVE:
                current = _read_release_link(
                    self._paths,
                    self._paths.current_link,
                    missing_ok=False,
                )
                if current == prepared.release_dir.resolve(strict=True):
                    return ActivationResult(True, prepared.version, UpdatePhase.ACTIVE)
                raise self._failure(UpdateErrorKind.RECOVERY_REQUIRED, "active release link is inconsistent")
            if record.phase is not UpdatePhase.PREPARED:
                raise self._failure(UpdateErrorKind.INCOMPATIBLE, "operation is not prepared")
            if (
                type(current_db_schema) is not int
                or current_db_schema != prepared.db_schema_after
                or not (
                    prepared.rollback_db_schema_min
                    <= current_db_schema
                    <= prepared.rollback_db_schema_max
                )
            ):
                failure = self._failure(
                    UpdateErrorKind.INCOMPATIBLE,
                    "database schema is not rollback compatible",
                )
                self._transition_failure(
                    operation_id,
                    frozenset({UpdatePhase.PREPARED}),
                    failure,
                )
                return ActivationResult(False, "", UpdatePhase.FAILED, failure)

            current = _read_release_link(
                self._paths,
                self._paths.current_link,
                missing_ok=True,
            )
            if current != prepared.previous_target:
                failure = self._failure(
                    UpdateErrorKind.RECOVERY_REQUIRED,
                    "current release changed after preparation",
                )
                self._transition_failure(
                    operation_id,
                    frozenset({UpdatePhase.PREPARED}),
                    failure,
                )
                return ActivationResult(False, "", UpdatePhase.FAILED, failure)

            preflight = self._preflight.check(prepared.release_dir)
            self._validate_gate(preflight)
            if not preflight.healthy:
                failure = self._failure(UpdateErrorKind.ACTIVATION, "candidate preflight failed")
                self._transition_failure(
                    operation_id,
                    frozenset({UpdatePhase.PREPARED}),
                    failure,
                )
                return ActivationResult(False, current.name if current else "", UpdatePhase.FAILED, failure)

            self._journal.transition(
                operation_id,
                expected=frozenset({UpdatePhase.PREPARED}),
                phase=UpdatePhase.ACTIVATING,
            )
            self._controller.stop()
            self._set_rollback_link(current, operation_id)
            self._atomic_link(self._paths.current_link, prepared.release_dir, operation_id)
            try:
                self._controller.start(prepared.release_dir)
            except Exception:  # noqa: BLE001 - restoration below returns a typed result
                failure = self._failure(UpdateErrorKind.ACTIVATION, "candidate service failed to start")
                return self._restore_previous(
                    prepared,
                    operation_id,
                    failure,
                    UpdatePhase.ACTIVATING,
                )
            self._journal.transition(
                operation_id,
                expected=frozenset({UpdatePhase.ACTIVATING}),
                phase=UpdatePhase.PROBATION,
            )
            health = self._health.wait_healthy(self._probation_timeout_seconds)
            self._validate_gate(health)
            if not health.healthy:
                failure = self._failure(UpdateErrorKind.ACTIVATION, "candidate health gate failed")
                return self._restore_previous(
                    prepared,
                    operation_id,
                    failure,
                    UpdatePhase.PROBATION,
                )
            self._journal.transition(
                operation_id,
                expected=frozenset({UpdatePhase.PROBATION}),
                phase=UpdatePhase.ACTIVE,
            )
            return ActivationResult(True, prepared.version, UpdatePhase.ACTIVE)
        except UpdateFailure as caught:
            try:
                record = self._journal.read(operation_id)
                if record.phase in {UpdatePhase.ACTIVATING, UpdatePhase.PROBATION}:
                    return self._restore_previous(
                        prepared,
                        operation_id,
                        caught,
                        record.phase,
                    )
                if record.phase is UpdatePhase.PREPARED:
                    self._transition_failure(
                        operation_id,
                        frozenset({UpdatePhase.PREPARED}),
                        caught,
                    )
            except UpdateFailure:
                pass
            return ActivationResult(False, "", UpdatePhase.FAILED, caught)
        except Exception:  # noqa: BLE001 - unexpected boundary failures are redacted
            failure = self._failure(UpdateErrorKind.ACTIVATION, "release activation failed")
            try:
                record = self._journal.read(operation_id)
                if record.phase in {UpdatePhase.ACTIVATING, UpdatePhase.PROBATION}:
                    return self._restore_previous(
                        prepared,
                        operation_id,
                        failure,
                        record.phase,
                    )
                if record.phase is UpdatePhase.PREPARED:
                    self._transition_failure(
                        operation_id,
                        frozenset({UpdatePhase.PREPARED}),
                        failure,
                    )
            except UpdateFailure:
                pass
            return ActivationResult(False, "", UpdatePhase.FAILED, failure)

    def rollback(self, operation_id: str) -> RollbackResult:
        try:
            record = self._journal.read(operation_id)
            if record.phase is UpdatePhase.ROLLED_BACK:
                current = _read_release_link(
                    self._paths,
                    self._paths.current_link,
                    missing_ok=False,
                )
                assert current is not None
                return RollbackResult(True, current.name, UpdatePhase.ROLLED_BACK)
            if record.phase is not UpdatePhase.ACTIVE:
                failure = self._failure(UpdateErrorKind.INCOMPATIBLE, "active release cannot be rolled back")
                return RollbackResult(False, "", record.phase, failure)
            current = _read_release_link(
                self._paths,
                self._paths.current_link,
                missing_ok=False,
            )
            previous = _read_release_link(
                self._paths,
                self._paths.rollback_link,
                missing_ok=False,
            )
            assert current is not None and previous is not None
            self._journal.transition(
                operation_id,
                expected=frozenset({UpdatePhase.ACTIVE}),
                phase=UpdatePhase.ROLLING_BACK,
            )
            self._controller.stop()
            self._atomic_link(self._paths.current_link, previous, operation_id)
            self._controller.start(previous)
            health = self._health.wait_healthy(self._probation_timeout_seconds)
            self._validate_gate(health)
            if not health.healthy:
                raise self._failure(UpdateErrorKind.ROLLBACK_FAILED, "rollback health gate failed")
            self._journal.transition(
                operation_id,
                expected=frozenset({UpdatePhase.ROLLING_BACK}),
                phase=UpdatePhase.ROLLED_BACK,
            )
            return RollbackResult(True, previous.name, UpdatePhase.ROLLED_BACK)
        except Exception as exc:  # noqa: BLE001 - rollback boundary is redacted
            failure = (
                exc
                if isinstance(exc, UpdateFailure) and exc.kind is UpdateErrorKind.ROLLBACK_FAILED
                else self._failure(UpdateErrorKind.ROLLBACK_FAILED, "release rollback failed")
            )
            try:
                record = self._journal.read(operation_id)
                if record.phase is UpdatePhase.ROLLING_BACK:
                    self._transition_failure(
                        operation_id,
                        frozenset({UpdatePhase.ROLLING_BACK}),
                        failure,
                    )
            except UpdateFailure:
                pass
            return RollbackResult(False, "", UpdatePhase.FAILED, failure)
