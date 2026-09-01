"""Detached Ed25519 verification through a narrow OpenSSL boundary."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from ailen.updates.contracts import (
    ReleaseManifest,
    UpdateErrorKind,
    UpdateFailure,
)
from ailen.updates.manifest import MAX_MANIFEST_BYTES, parse_release_manifest

ED25519_SIGNATURE_BYTES = 64
MAX_PUBLIC_KEY_BYTES = 16 * 1024

Runner = Callable[..., subprocess.CompletedProcess[bytes]]


class UpdateSignatureError(UpdateFailure):
    """A signature is invalid or its verifier is unavailable."""

    def __init__(self, kind: UpdateErrorKind, message: str | None = None) -> None:
        if kind not in {
            UpdateErrorKind.SIGNATURE_INVALID,
            UpdateErrorKind.SIGNATURE_UNAVAILABLE,
        }:
            raise ValueError("invalid signature error kind")
        public_message = message or (
            "signature verifier unavailable"
            if kind is UpdateErrorKind.SIGNATURE_UNAVAILABLE
            else "manifest signature is invalid"
        )
        super().__init__(kind, public_message)


class SignatureVerifier(Protocol):
    def verify(
        self,
        manifest_path: Path,
        signature_path: Path,
        public_key_path: Path,
    ) -> bytes:
        raise NotImplementedError


class OpenSslEd25519Verifier:
    """Verify exact manifest bytes without exposing OpenSSL output."""

    def __init__(
        self,
        *,
        binary: str | None = None,
        timeout_seconds: float = 3.0,
        strict_key_permissions: bool = True,
        runner: Runner | None = None,
    ) -> None:
        self._binary = shutil.which(binary or "openssl")
        self._timeout_seconds = timeout_seconds
        self._strict_key_permissions = strict_key_permissions
        self._runner = runner or subprocess.run

    @staticmethod
    def _open_regular_file(path: Path) -> tuple[int, os.stat_result]:
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        close_on_exec = getattr(os, "O_CLOEXEC", 0)
        if no_follow == 0 or not Path("/proc/self/fd").is_dir():
            raise UpdateSignatureError(UpdateErrorKind.SIGNATURE_UNAVAILABLE)
        flags = os.O_RDONLY | os.O_NONBLOCK | no_follow | close_on_exec
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise UpdateSignatureError(
                UpdateErrorKind.SIGNATURE_INVALID,
                "signature inputs must be regular files",
            ) from exc
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            os.close(descriptor)
            raise UpdateSignatureError(
                UpdateErrorKind.SIGNATURE_INVALID,
                "signature inputs must be regular files",
            )
        return descriptor, file_stat

    def _validate_stats(
        self,
        manifest_stat: os.stat_result,
        signature_stat: os.stat_result,
        key_stat: os.stat_result,
    ) -> None:
        if manifest_stat.st_size > MAX_MANIFEST_BYTES:
            raise UpdateSignatureError(
                UpdateErrorKind.SIGNATURE_INVALID,
                "manifest exceeds signature verification size limit",
            )
        if signature_stat.st_size != ED25519_SIGNATURE_BYTES:
            raise UpdateSignatureError(
                UpdateErrorKind.SIGNATURE_INVALID,
                "signature has invalid size",
            )
        if key_stat.st_size <= 0 or key_stat.st_size > MAX_PUBLIC_KEY_BYTES:
            raise UpdateSignatureError(UpdateErrorKind.SIGNATURE_INVALID)
        if self._strict_key_permissions:
            owner_allowed = key_stat.st_uid in {0, os.geteuid()}
            writable_by_others = bool(stat.S_IMODE(key_stat.st_mode) & 0o022)
            if not owner_allowed or writable_by_others:
                raise UpdateSignatureError(
                    UpdateErrorKind.SIGNATURE_INVALID,
                    "public key permissions are unsafe",
                )

    @staticmethod
    def _read_descriptor(descriptor: int, *, maximum: int) -> bytes:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise UpdateSignatureError(UpdateErrorKind.SIGNATURE_INVALID)
        return b"".join(chunks)

    def verify(
        self,
        manifest_path: Path,
        signature_path: Path,
        public_key_path: Path,
    ) -> bytes:
        if self._binary is None:
            raise UpdateSignatureError(UpdateErrorKind.SIGNATURE_UNAVAILABLE)

        descriptors: list[int] = []
        try:
            manifest_fd, manifest_stat = self._open_regular_file(manifest_path)
            descriptors.append(manifest_fd)
            signature_fd, signature_stat = self._open_regular_file(signature_path)
            descriptors.append(signature_fd)
            key_fd, key_stat = self._open_regular_file(public_key_path)
            descriptors.append(key_fd)
            self._validate_stats(manifest_stat, signature_stat, key_stat)

            manifest_before = self._read_descriptor(
                manifest_fd,
                maximum=MAX_MANIFEST_BYTES,
            )
            signature_before = self._read_descriptor(
                signature_fd,
                maximum=ED25519_SIGNATURE_BYTES,
            )
            key_before = self._read_descriptor(key_fd, maximum=MAX_PUBLIC_KEY_BYTES)

            command = [
                self._binary,
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                f"/proc/self/fd/{key_fd}",
                "-rawin",
                "-in",
                f"/proc/self/fd/{manifest_fd}",
                "-sigfile",
                f"/proc/self/fd/{signature_fd}",
            ]
            result = self._runner(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=self._timeout_seconds,
                check=False,
                pass_fds=(manifest_fd, signature_fd, key_fd),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UpdateSignatureError(UpdateErrorKind.SIGNATURE_UNAVAILABLE) from exc
        else:
            if result.returncode != 0:
                raise UpdateSignatureError(UpdateErrorKind.SIGNATURE_INVALID)
            manifest_after = self._read_descriptor(
                manifest_fd,
                maximum=MAX_MANIFEST_BYTES,
            )
            signature_after = self._read_descriptor(
                signature_fd,
                maximum=ED25519_SIGNATURE_BYTES,
            )
            key_after = self._read_descriptor(key_fd, maximum=MAX_PUBLIC_KEY_BYTES)
            if (
                manifest_before != manifest_after
                or signature_before != signature_after
                or key_before != key_after
            ):
                raise UpdateSignatureError(UpdateErrorKind.SIGNATURE_INVALID)
            return manifest_after
        finally:
            for descriptor in descriptors:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


class VerifiedManifestLoader:
    """Parse a manifest only after its detached signature succeeds."""

    def __init__(self, verifier: SignatureVerifier) -> None:
        self._verifier = verifier

    def load(
        self,
        manifest_path: Path,
        signature_path: Path,
        public_key_path: Path,
    ) -> ReleaseManifest:
        verified_bytes = self._verifier.verify(
            manifest_path,
            signature_path,
            public_key_path,
        )
        return parse_release_manifest(verified_bytes)
