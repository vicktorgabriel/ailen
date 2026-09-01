"""Bounded, resumable, and cancellable artifact download."""

from __future__ import annotations

import http.client
import json
import os
import re
import stat
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ailen.updates.artifact_store import ContentAddressedArtifactStore
from ailen.updates.contracts import ArtifactSpec, UpdateErrorKind, UpdateFailure
from ailen.updates.source import HttpsUrlPolicy, UrlPolicy, ValidatingRedirectHandler

_METADATA_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_id",
        "sha256",
        "size_bytes",
        "downloaded_bytes",
        "etag",
    }
)
_CONTENT_RANGE = re.compile(r"^bytes ([0-9]+)-([0-9]+)/([0-9]+)$")
_MAX_METADATA_BYTES = 8 * 1024
_READ_SIZE = 64 * 1024


@dataclass(frozen=True)
class DownloadProgress:
    downloaded_bytes: int
    total_bytes: int


@dataclass(frozen=True)
class _ResumeMetadata:
    downloaded_bytes: int
    etag: str


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class HttpsArtifactDownloader:
    """Download one manifest-approved artifact into its immutable CAS object."""

    def __init__(
        self,
        *,
        store: ContentAddressedArtifactStore,
        timeout_seconds: float = 10.0,
        url_policy: UrlPolicy | None = None,
        opener: Any | None = None,
    ) -> None:
        self._store = store
        self._timeout_seconds = timeout_seconds
        self._url_policy = url_policy or HttpsUrlPolicy()
        self._opener = opener or urllib.request.build_opener(
            ValidatingRedirectHandler(self._url_policy)
        )

    @staticmethod
    def _metadata_path(stage: Path) -> Path:
        return stage.with_name(f"{stage.name}.json")

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _discard_partial(self, stage: Path, metadata_path: Path) -> None:
        try:
            if stage.is_symlink() or metadata_path.is_symlink():
                raise UpdateFailure(UpdateErrorKind.INTEGRITY, "download staging is unsafe")
            stage.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            self._fsync_directory(stage.parent)
        except UpdateFailure:
            raise
        except OSError as exc:
            raise UpdateFailure(UpdateErrorKind.INTEGRITY, "download staging unavailable") from exc

    def _load_resume_metadata(
        self,
        stage: Path,
        metadata_path: Path,
        spec: ArtifactSpec,
    ) -> _ResumeMetadata | None:
        if not stage.exists() and not stage.is_symlink():
            if metadata_path.exists() or metadata_path.is_symlink():
                self._discard_partial(stage, metadata_path)
            return None
        if stage.is_symlink() or metadata_path.is_symlink() or not metadata_path.is_file():
            self._discard_partial(stage, metadata_path)
            return None
        try:
            metadata_stat = metadata_path.lstat()
            if not stat.S_ISREG(metadata_stat.st_mode) or metadata_stat.st_size > _MAX_METADATA_BYTES:
                self._discard_partial(stage, metadata_path)
                return None
            raw = metadata_path.read_bytes()
            document = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            self._discard_partial(stage, metadata_path)
            return None
        if not isinstance(document, dict) or set(document) != _METADATA_FIELDS:
            self._discard_partial(stage, metadata_path)
            return None
        downloaded = document.get("downloaded_bytes")
        size_bytes = document.get("size_bytes")
        schema_version = document.get("schema_version")
        etag = document.get("etag")
        valid = (
            type(schema_version) is int
            and schema_version == 1
            and document.get("artifact_id") == spec.artifact_id
            and document.get("sha256") == spec.sha256
            and type(size_bytes) is int
            and size_bytes == spec.size_bytes
            and type(downloaded) is int
            and 0 < downloaded < spec.size_bytes
            and downloaded == stage.stat().st_size
            and isinstance(etag, str)
            and 0 < len(etag.encode("utf-8")) <= 256
            and not any(ord(character) < 32 or ord(character) == 127 for character in etag)
        )
        if not valid:
            self._discard_partial(stage, metadata_path)
            return None
        assert type(downloaded) is int
        assert isinstance(etag, str)
        return _ResumeMetadata(downloaded_bytes=downloaded, etag=etag)

    def _write_resume_metadata(
        self,
        metadata_path: Path,
        spec: ArtifactSpec,
        *,
        downloaded_bytes: int,
        etag: str,
    ) -> None:
        document = {
            "schema_version": 1,
            "artifact_id": spec.artifact_id,
            "sha256": spec.sha256,
            "size_bytes": spec.size_bytes,
            "downloaded_bytes": downloaded_bytes,
            "etag": etag,
        }
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{metadata_path.name}.",
            dir=metadata_path.parent,
        )
        temporary = Path(raw_path)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, metadata_path)
            self._fsync_directory(metadata_path.parent)
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _notify(
        callback: Any | None,
        downloaded_bytes: int,
        total_bytes: int,
    ) -> None:
        if callback is None:
            return
        try:
            callback(DownloadProgress(downloaded_bytes, total_bytes))
        except Exception:  # noqa: BLE001 - observer failures cannot corrupt the download
            return

    @staticmethod
    def _response_status(response: Any) -> int:
        status = getattr(response, "status", None)
        return status if isinstance(status, int) else int(response.getcode())

    @staticmethod
    def _content_length(response: Any) -> int | None:
        raw = response.headers.get("Content-Length")
        if raw is None:
            return None
        if not raw.isdigit():
            raise UpdateFailure(UpdateErrorKind.INTEGRITY, "invalid artifact length")
        return int(raw)

    @staticmethod
    def _validate_partial_response(
        response: Any,
        spec: ArtifactSpec,
        resume: _ResumeMetadata,
    ) -> bool:
        etag = response.headers.get("ETag", "")
        content_range = response.headers.get("Content-Range", "")
        match = _CONTENT_RANGE.fullmatch(content_range)
        if etag != resume.etag or match is None:
            return False
        start, end, total = (int(value) for value in match.groups())
        expected_remaining = spec.size_bytes - resume.downloaded_bytes
        content_length = HttpsArtifactDownloader._content_length(response)
        return (
            start == resume.downloaded_bytes
            and end == spec.size_bytes - 1
            and total == spec.size_bytes
            and (content_length is None or content_length == expected_remaining)
        )

    def _consume(
        self,
        response: Any,
        *,
        stage: Path,
        metadata_path: Path,
        spec: ArtifactSpec,
        start: int,
        etag: str,
        cancellation: CancellationToken,
        on_progress: Any | None,
    ) -> None:
        mode = "ab" if start else "wb"
        downloaded = start
        try:
            with stage.open(mode) as handle:
                while downloaded < spec.size_bytes:
                    if cancellation.cancelled:
                        handle.flush()
                        os.fsync(handle.fileno())
                        if etag and downloaded:
                            self._write_resume_metadata(
                                metadata_path,
                                spec,
                                downloaded_bytes=downloaded,
                                etag=etag,
                            )
                        else:
                            self._discard_partial(stage, metadata_path)
                        raise UpdateFailure(UpdateErrorKind.CANCELLED, "artifact download cancelled")
                    remaining = spec.size_bytes - downloaded
                    chunk = response.read(min(_READ_SIZE, remaining + 1))
                    if not chunk:
                        raise UpdateFailure(UpdateErrorKind.INTEGRITY, "artifact body is incomplete")
                    downloaded += len(chunk)
                    if downloaded > spec.size_bytes:
                        raise UpdateFailure(UpdateErrorKind.INTEGRITY, "artifact body is too large")
                    handle.write(chunk)
                    self._notify(on_progress, downloaded, spec.size_bytes)
                extra = response.read(1)
                if extra:
                    raise UpdateFailure(UpdateErrorKind.INTEGRITY, "artifact body is too large")
                handle.flush()
                os.fsync(handle.fileno())
        except UpdateFailure:
            raise
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            if etag and downloaded:
                self._write_resume_metadata(
                    metadata_path,
                    spec,
                    downloaded_bytes=downloaded,
                    etag=etag,
                )
            raise UpdateFailure(UpdateErrorKind.NETWORK, "artifact download unavailable") from exc

    def download(
        self,
        spec: ArtifactSpec,
        operation_id: str,
        cancellation: CancellationToken,
        on_progress: Any | None = None,
    ) -> Path:
        self._url_policy.validate(spec.url)
        stage = self._store.stage_path(operation_id)
        metadata_path = self._metadata_path(stage)
        if cancellation.cancelled:
            raise UpdateFailure(UpdateErrorKind.CANCELLED, "artifact download cancelled")

        if stage.exists() and stage.stat().st_size == spec.size_bytes:
            try:
                target = self._store.commit(stage, spec)
            except UpdateFailure:
                self._discard_partial(stage, metadata_path)
            else:
                metadata_path.unlink(missing_ok=True)
                return target

        resume = self._load_resume_metadata(stage, metadata_path, spec)
        restarted = False
        while True:
            headers: dict[str, str] = {}
            if resume is not None:
                headers = {
                    "Range": f"bytes={resume.downloaded_bytes}-",
                    "If-Range": resume.etag,
                }
            request = urllib.request.Request(spec.url, headers=headers, method="GET")
            try:
                response = self._opener.open(request, timeout=self._timeout_seconds)
            except urllib.error.HTTPError as exc:
                if exc.code == 416 and resume is not None and not restarted:
                    exc.close()
                    self._discard_partial(stage, metadata_path)
                    resume = None
                    restarted = True
                    continue
                raise UpdateFailure(UpdateErrorKind.NETWORK, "artifact download unavailable") from exc
            except (OSError, TimeoutError, urllib.error.URLError, http.client.HTTPException) as exc:
                raise UpdateFailure(UpdateErrorKind.NETWORK, "artifact download unavailable") from exc

            try:
                with response:
                    self._url_policy.validate(response.geturl())
                    status = self._response_status(response)
                    if resume is not None and status == 206:
                        if not self._validate_partial_response(response, spec, resume):
                            if restarted:
                                raise UpdateFailure(
                                    UpdateErrorKind.INTEGRITY,
                                    "artifact resume response is invalid",
                                )
                            self._discard_partial(stage, metadata_path)
                            resume = None
                            restarted = True
                            continue
                        start = resume.downloaded_bytes
                        etag = resume.etag
                    elif status == 200:
                        expected_length = spec.size_bytes
                        content_length = self._content_length(response)
                        if content_length is not None and content_length != expected_length:
                            raise UpdateFailure(
                                UpdateErrorKind.INTEGRITY,
                                "invalid artifact length",
                            )
                        if resume is not None:
                            self._discard_partial(stage, metadata_path)
                        start = 0
                        etag = response.headers.get("ETag", "")
                    else:
                        raise UpdateFailure(
                            UpdateErrorKind.NETWORK,
                            "artifact server response is unsupported",
                        )
                    self._consume(
                        response,
                        stage=stage,
                        metadata_path=metadata_path,
                        spec=spec,
                        start=start,
                        etag=etag,
                        cancellation=cancellation,
                        on_progress=on_progress,
                    )
            except UpdateFailure as exc:
                if exc.kind is UpdateErrorKind.INTEGRITY:
                    self._discard_partial(stage, metadata_path)
                raise

            try:
                target = self._store.commit(stage, spec)
            except UpdateFailure as exc:
                if exc.kind is UpdateErrorKind.INTEGRITY:
                    self._discard_partial(stage, metadata_path)
                raise
            metadata_path.unlink(missing_ok=True)
            return target
