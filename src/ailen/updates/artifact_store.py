"""Immutable content-addressed storage for verified update artifacts."""

from __future__ import annotations

import errno
import hashlib
import hmac
import os
import re
import stat
from pathlib import Path

from ailen.updates.contracts import ArtifactSpec, UpdateErrorKind, UpdateFailure

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ContentAddressedArtifactStore:
    """Own staging and immutable objects beneath one injected private root."""

    def __init__(self, root: Path) -> None:
        self._configured_root = root
        self._root = root.resolve(strict=False)

    @staticmethod
    def _failure(message: str = "artifact store integrity check failed") -> UpdateFailure:
        return UpdateFailure(UpdateErrorKind.INTEGRITY, message)

    @staticmethod
    def _validate_identifier(value: str, *, label: str) -> None:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ContentAddressedArtifactStore._failure(f"invalid {label}")

    @staticmethod
    def _validate_digest(value: str) -> None:
        if _SHA256.fullmatch(value) is None:
            raise ContentAddressedArtifactStore._failure("invalid artifact digest")

    def _validate_root_policy(self) -> None:
        if not self._configured_root.is_absolute():
            raise self._failure("artifact store root must be absolute")
        if self._root in {Path("/"), Path.home().resolve(strict=False)}:
            raise self._failure("broad artifact store root refused")
        try:
            if self._configured_root.is_symlink():
                raise self._failure("artifact store root is unsafe")
        except OSError as exc:
            raise self._failure() from exc

    @staticmethod
    def _validate_directory(path: Path) -> None:
        try:
            directory_stat = path.lstat()
        except OSError as exc:
            raise ContentAddressedArtifactStore._failure() from exc
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise ContentAddressedArtifactStore._failure("artifact store directory is unsafe")
        if directory_stat.st_uid not in {0, os.geteuid()}:
            raise ContentAddressedArtifactStore._failure("artifact store owner is unsafe")
        if stat.S_IMODE(directory_stat.st_mode) & 0o022:
            raise ContentAddressedArtifactStore._failure("artifact store permissions are unsafe")

    def _ensure_directory(self, path: Path, *, mode: int = 0o700) -> None:
        if not path.is_relative_to(self._root):
            raise self._failure()
        try:
            path.mkdir(mode=mode, parents=False, exist_ok=True)
        except OSError as exc:
            kind = (
                UpdateErrorKind.INSUFFICIENT_DISK
                if exc.errno == errno.ENOSPC
                else UpdateErrorKind.INTEGRITY
            )
            raise UpdateFailure(kind, "artifact store unavailable") from exc
        self._validate_directory(path)

    def _ensure_root(self) -> None:
        self._validate_root_policy()
        if not self._root.exists():
            try:
                self._root.mkdir(mode=0o700, parents=True)
            except OSError as exc:
                raise self._failure("artifact store unavailable") from exc
        self._validate_directory(self._root)

    def _ensure_staging_dir(self) -> Path:
        self._ensure_root()
        staging = self._root / "staging"
        self._ensure_directory(staging)
        return staging

    def _ensure_object_dir(self, digest: str) -> Path:
        self._ensure_root()
        objects = self._root / "objects"
        self._ensure_directory(objects)
        digest_dir = objects / digest[:2]
        self._ensure_directory(digest_dir)
        return digest_dir

    def stage_path(self, operation_id: str) -> Path:
        self._validate_identifier(operation_id, label="operation_id")
        staging = self._ensure_staging_dir()
        path = staging / f"{operation_id}.part"
        if path.exists() or path.is_symlink():
            try:
                file_stat = path.lstat()
            except OSError as exc:
                raise self._failure() from exc
            if not stat.S_ISREG(file_stat.st_mode):
                raise self._failure("staged artifact is unsafe")
        return path

    def object_path(self, sha256: str) -> Path:
        self._validate_digest(sha256)
        return self._root / "objects" / sha256[:2] / sha256

    @staticmethod
    def _open_regular(path: Path) -> tuple[int, os.stat_result]:
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if no_follow == 0:
            raise ContentAddressedArtifactStore._failure("safe file open unavailable")
        flags = os.O_RDONLY | os.O_NONBLOCK | no_follow | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ContentAddressedArtifactStore._failure("artifact file is unsafe") from exc
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            os.close(descriptor)
            raise ContentAddressedArtifactStore._failure("artifact file is unsafe")
        return descriptor, file_stat

    @staticmethod
    def _digest_descriptor(descriptor: int) -> str:
        os.lseek(descriptor, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _verify_file(self, path: Path, spec: ArtifactSpec, *, fsync: bool) -> None:
        descriptor, file_stat = self._open_regular(path)
        try:
            if file_stat.st_size != spec.size_bytes:
                raise self._failure("artifact size verification failed")
            actual_digest = self._digest_descriptor(descriptor)
            if not hmac.compare_digest(actual_digest, spec.sha256):
                raise self._failure("artifact digest verification failed")
            if fsync:
                os.fsync(descriptor)
            current_stat = path.lstat()
            if (
                current_stat.st_ino != file_stat.st_ino
                or current_stat.st_dev != file_stat.st_dev
                or not stat.S_ISREG(current_stat.st_mode)
            ):
                raise self._failure("artifact changed during verification")
        except OSError as exc:
            raise self._failure() from exc
        finally:
            os.close(descriptor)

    def _validate_staged_path(self, staged_path: Path) -> Path:
        staging = self._ensure_staging_dir()
        try:
            parent = staged_path.parent.resolve(strict=True)
        except OSError as exc:
            raise self._failure("staged artifact is unsafe") from exc
        if parent != staging or not staged_path.name.endswith(".part"):
            raise self._failure("staged artifact is outside store")
        operation_id = staged_path.name.removesuffix(".part")
        self._validate_identifier(operation_id, label="operation_id")
        return staging

    def commit(self, staged_path: Path, spec: ArtifactSpec) -> Path:
        self._validate_digest(spec.sha256)
        self._validate_identifier(spec.artifact_id, label="artifact_id")
        staging = self._validate_staged_path(staged_path)
        self._verify_file(staged_path, spec, fsync=True)

        target_parent = self._ensure_object_dir(spec.sha256)
        target = target_parent / spec.sha256
        if target.exists() or target.is_symlink():
            self._verify_file(target, spec, fsync=False)
            try:
                staged_path.unlink()
                self._fsync_directory(staging)
            except OSError as exc:
                raise self._failure() from exc
            return target

        try:
            os.replace(staged_path, target)
            target.chmod(0o444)
            target_descriptor, _ = self._open_regular(target)
            try:
                os.fsync(target_descriptor)
            finally:
                os.close(target_descriptor)
            self._fsync_directory(target_parent)
            self._fsync_directory(staging)
        except OSError as exc:
            kind = (
                UpdateErrorKind.INSUFFICIENT_DISK
                if exc.errno == errno.ENOSPC
                else UpdateErrorKind.INTEGRITY
            )
            raise UpdateFailure(kind, "artifact commit failed") from exc
        return target

    def remove(self, sha256: str, protected: frozenset[str]) -> bool:
        self._validate_digest(sha256)
        if sha256 in protected:
            return False
        self._validate_root_policy()
        if not self._root.exists():
            return False
        self._validate_directory(self._root)
        target = self.object_path(sha256)
        if not target.exists() and not target.is_symlink():
            return False
        descriptor, _ = self._open_regular(target)
        os.close(descriptor)
        try:
            target.unlink()
            self._fsync_directory(target.parent)
        except OSError as exc:
            raise self._failure() from exc
        return True
