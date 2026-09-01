"""Bounded HTTPS loading of signed release manifests."""

from __future__ import annotations

import http.client
import os
import stat
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from ailen.updates.contracts import (
    ReleaseManifest,
    UpdateChannel,
    UpdateErrorKind,
    UpdateFailure,
)
from ailen.updates.manifest import MAX_MANIFEST_BYTES
from ailen.updates.signatures import ED25519_SIGNATURE_BYTES, VerifiedManifestLoader


class ByteFetcher(Protocol):
    def fetch(self, url: str, *, max_bytes: int) -> bytes:
        raise NotImplementedError


class UrlPolicy(Protocol):
    def validate(self, url: str) -> None:
        raise NotImplementedError


class HttpsUrlPolicy:
    """Canonical network URL policy for release and artifact retrieval."""

    def validate(self, url: str) -> None:
        if not isinstance(url, str) or url != url.strip():
            raise UpdateFailure(UpdateErrorKind.NETWORK, "update source URL is not allowed")
        try:
            parsed = urlsplit(url)
            _ = parsed.port
        except ValueError as exc:
            raise UpdateFailure(
                UpdateErrorKind.NETWORK, "update source URL is not allowed"
            ) from exc
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise UpdateFailure(UpdateErrorKind.NETWORK, "update source URL is not allowed")


class ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Apply the URL policy to every redirect before urllib follows it."""

    def __init__(self, policy: UrlPolicy) -> None:
        super().__init__()
        self._policy = policy

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        self._policy.validate(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpsByteFetcher:
    """Read a bounded response without exposing URL or body in errors."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        policy: HttpsUrlPolicy | None = None,
        opener: Any | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._policy = policy or HttpsUrlPolicy()
        self._opener = opener or urllib.request.build_opener(
            ValidatingRedirectHandler(self._policy)
        )

    def fetch(self, url: str, *, max_bytes: int) -> bytes:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._policy.validate(url)
        request = urllib.request.Request(url, method="GET")
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                self._policy.validate(response.geturl())
                body = response.read(max_bytes + 1)
        except UpdateFailure:
            raise
        except (
            OSError,
            TimeoutError,
            urllib.error.URLError,
            http.client.HTTPException,
        ) as exc:
            raise UpdateFailure(UpdateErrorKind.NETWORK, "update source unavailable") from exc
        if not isinstance(body, bytes):
            raise UpdateFailure(UpdateErrorKind.INTEGRITY, "update source response is invalid")
        if len(body) > max_bytes:
            raise UpdateFailure(UpdateErrorKind.INTEGRITY, "update source response is too large")
        return body


class HttpsReleaseSource:
    """Fetch, stage, verify, parse, and channel-check a release manifest."""

    def __init__(
        self,
        *,
        manifest_url: str,
        signature_url: str,
        public_key_path: Path,
        staging_dir: Path,
        loader: VerifiedManifestLoader,
        fetcher: ByteFetcher,
    ) -> None:
        self._manifest_url = manifest_url
        self._signature_url = signature_url
        self._public_key_path = public_key_path
        self._staging_dir = staging_dir
        self._loader = loader
        self._fetcher = fetcher

    def _ensure_private_staging_dir(self) -> None:
        try:
            if not self._staging_dir.exists():
                self._staging_dir.mkdir(mode=0o700, parents=True)
            directory_stat = self._staging_dir.lstat()
        except OSError as exc:
            raise UpdateFailure(UpdateErrorKind.INTEGRITY, "update staging unavailable") from exc
        if self._staging_dir.is_symlink() or not stat.S_ISDIR(directory_stat.st_mode):
            raise UpdateFailure(UpdateErrorKind.INTEGRITY, "update staging is unsafe")
        if directory_stat.st_uid not in {0, os.geteuid()}:
            raise UpdateFailure(UpdateErrorKind.INTEGRITY, "update staging owner is unsafe")
        if stat.S_IMODE(directory_stat.st_mode) & 0o077:
            raise UpdateFailure(UpdateErrorKind.INTEGRITY, "update staging permissions are unsafe")

    def _write_staged(self, *, prefix: str, payload: bytes) -> Path:
        descriptor, raw_path = tempfile.mkstemp(prefix=prefix, dir=self._staging_dir)
        path = Path(raw_path)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            path.unlink(missing_ok=True)
            raise
        return path

    def fetch(self, channel: UpdateChannel) -> ReleaseManifest:
        manifest_bytes = self._fetcher.fetch(
            self._manifest_url,
            max_bytes=MAX_MANIFEST_BYTES,
        )
        signature_bytes = self._fetcher.fetch(
            self._signature_url,
            max_bytes=ED25519_SIGNATURE_BYTES,
        )
        if not isinstance(manifest_bytes, bytes) or len(manifest_bytes) > MAX_MANIFEST_BYTES:
            raise UpdateFailure(UpdateErrorKind.INTEGRITY, "release manifest has invalid size")
        if (
            not isinstance(signature_bytes, bytes)
            or len(signature_bytes) != ED25519_SIGNATURE_BYTES
        ):
            raise UpdateFailure(UpdateErrorKind.INTEGRITY, "release signature has invalid size")

        self._ensure_private_staging_dir()
        manifest_path: Path | None = None
        signature_path: Path | None = None
        try:
            manifest_path = self._write_staged(prefix="manifest-", payload=manifest_bytes)
            signature_path = self._write_staged(prefix="signature-", payload=signature_bytes)
            manifest = self._loader.load(
                manifest_path,
                signature_path,
                self._public_key_path,
            )
            if manifest.channel is not channel:
                raise UpdateFailure(
                    UpdateErrorKind.INCOMPATIBLE,
                    "release channel does not match request",
                )
            return manifest
        finally:
            if manifest_path is not None:
                manifest_path.unlink(missing_ok=True)
            if signature_path is not None:
                signature_path.unlink(missing_ok=True)
