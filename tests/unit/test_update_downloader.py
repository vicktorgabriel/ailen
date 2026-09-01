"""Integration-style unit tests for bounded resumable artifact downloads."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from ailen.updates.artifact_store import ContentAddressedArtifactStore
from ailen.updates.contracts import ArtifactKind, ArtifactSpec, UpdateErrorKind, UpdateFailure
from ailen.updates.downloader import (
    CancellationToken,
    DownloadProgress,
    HttpsArtifactDownloader,
)


class _ScenarioServer(ThreadingHTTPServer):
    data: bytes
    etag: str
    requests_seen: list[tuple[str, str, str]]


class _Handler(BaseHTTPRequestHandler):
    server: _ScenarioServer

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _send_body(
        self,
        *,
        status: int,
        body: bytes,
        etag: str,
        content_range: str = "",
        declared_length: int | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body) if declared_length is None else declared_length))
        self.send_header("ETag", etag)
        if content_range:
            self.send_header("Content-Range", content_range)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        range_header = self.headers.get("Range", "")
        if_range = self.headers.get("If-Range", "")
        path = self.path.split("?", 1)[0]
        self.server.requests_seen.append((path, range_header, if_range))

        if path == "/redirect-away":
            self.send_response(302)
            self.send_header("Location", "http://example.invalid/private")
            self.end_headers()
            return
        if path == "/error":
            self.send_response(503)
            self.send_header("Content-Length", "12")
            self.end_headers()
            self.wfile.write(b"private-body")
            return
        if path == "/oversized":
            self._send_body(
                status=200,
                body=self.server.data + b"x",
                etag=self.server.etag,
            )
            return
        if path == "/wrong-length":
            self._send_body(
                status=200,
                body=self.server.data,
                etag=self.server.etag,
                declared_length=len(self.server.data) - 1,
            )
            return

        if range_header:
            start = int(range_header.removeprefix("bytes=").removesuffix("-"))
            if path == "/range-416":
                self.send_response(416)
                self.end_headers()
                return
            if path == "/ignore-range":
                self._send_body(status=200, body=self.server.data, etag=self.server.etag)
                return
            response_etag = "changed-etag" if path == "/changed-etag" else self.server.etag
            body = self.server.data[start:]
            self._send_body(
                status=206,
                body=body,
                etag=response_etag,
                content_range=f"bytes {start}-{len(self.server.data) - 1}/{len(self.server.data)}",
            )
            return

        self._send_body(status=200, body=self.server.data, etag=self.server.etag)


@contextmanager
def _server(data: bytes) -> Iterator[tuple[_ScenarioServer, str]]:
    server = _ScenarioServer(("127.0.0.1", 0), _Handler)
    server.data = data
    server.etag = '"synthetic-etag"'
    server.requests_seen = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield server, f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


class _LoopbackPolicy:
    def validate(self, url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.fragment:
            raise UpdateFailure(UpdateErrorKind.NETWORK, "test URL rejected")


def _spec(data: bytes, url: str, *, digest_data: bytes | None = None) -> ArtifactSpec:
    return ArtifactSpec(
        artifact_id="ailen-core-linux-amd64",
        kind=ArtifactKind.RELEASE,
        url=url,
        sha256=hashlib.sha256(data if digest_data is None else digest_data).hexdigest(),
        size_bytes=len(data),
        expanded_size_bytes=len(data) * 4,
        platform="linux-amd64",
        media_type="application/gzip",
    )


def _downloader(tmp_path: Path) -> tuple[ContentAddressedArtifactStore, HttpsArtifactDownloader]:
    store = ContentAddressedArtifactStore(tmp_path / "store")
    return store, HttpsArtifactDownloader(store=store, url_policy=_LoopbackPolicy())


def _write_resume_metadata(stage: Path, spec: ArtifactSpec, downloaded: int, etag: str) -> Path:
    metadata = stage.with_name(f"{stage.name}.json")
    metadata.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifact_id": spec.artifact_id,
                "sha256": spec.sha256,
                "size_bytes": spec.size_bytes,
                "downloaded_bytes": downloaded,
                "etag": etag,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return metadata


def test_fresh_download_commits_only_after_exact_integrity(tmp_path: Path) -> None:
    data = b"a" * (128 * 1024)
    with _server(data) as (_, base_url):
        store, downloader = _downloader(tmp_path)
        spec = _spec(data, f"{base_url}/full")
        progress: list[DownloadProgress] = []

        target = downloader.download(
            spec,
            "operation-1",
            CancellationToken(),
            progress.append,
        )

    assert target == store.object_path(spec.sha256)
    assert target.read_bytes() == data
    assert progress
    assert progress[-1] == DownloadProgress(len(data), len(data))
    assert [item.downloaded_bytes for item in progress] == sorted(
        item.downloaded_bytes for item in progress
    )


def test_valid_partial_resumes_with_range_and_if_range(tmp_path: Path) -> None:
    data = b"0123456789" * 20_000
    with _server(data) as (server, base_url):
        store, downloader = _downloader(tmp_path)
        spec = _spec(data, f"{base_url}/range")
        downloaded = 70_000
        stage = store.stage_path("operation-1")
        stage.write_bytes(data[:downloaded])
        metadata = _write_resume_metadata(stage, spec, downloaded, server.etag)

        target = downloader.download(spec, "operation-1", CancellationToken())

    assert target.read_bytes() == data
    assert server.requests_seen == [("/range", f"bytes={downloaded}-", server.etag)]
    assert not metadata.exists()


def test_server_ignoring_range_restarts_without_appending(tmp_path: Path) -> None:
    data = b"range ignored" * 10_000
    with _server(data) as (server, base_url):
        store, downloader = _downloader(tmp_path)
        spec = _spec(data, f"{base_url}/ignore-range")
        downloaded = 4096
        stage = store.stage_path("operation-1")
        stage.write_bytes(data[:downloaded])
        _write_resume_metadata(stage, spec, downloaded, server.etag)

        target = downloader.download(spec, "operation-1", CancellationToken())

    assert target.read_bytes() == data
    assert server.requests_seen == [
        ("/ignore-range", f"bytes={downloaded}-", server.etag)
    ]


@pytest.mark.parametrize("path", ["/changed-etag", "/range-416"])
def test_ambiguous_resume_retries_once_from_zero(tmp_path: Path, path: str) -> None:
    data = b"resume safely" * 12_000
    with _server(data) as (server, base_url):
        store, downloader = _downloader(tmp_path)
        spec = _spec(data, f"{base_url}{path}")
        downloaded = 5000
        stage = store.stage_path("operation-1")
        stage.write_bytes(data[:downloaded])
        _write_resume_metadata(stage, spec, downloaded, server.etag)

        target = downloader.download(spec, "operation-1", CancellationToken())

    assert target.read_bytes() == data
    assert server.requests_seen == [
        (path, f"bytes={downloaded}-", server.etag),
        (path, "", ""),
    ]


@pytest.mark.parametrize("path", ["/wrong-length", "/oversized"])
def test_invalid_length_never_creates_cas_object(tmp_path: Path, path: str) -> None:
    data = b"bounded body" * 10_000
    with _server(data) as (_, base_url):
        store, downloader = _downloader(tmp_path)
        spec = _spec(data, f"{base_url}{path}")

        with pytest.raises(UpdateFailure):
            downloader.download(spec, "operation-1", CancellationToken())

    assert not store.object_path(spec.sha256).exists()


def test_cancellation_preserves_bounded_resume_then_completes(tmp_path: Path) -> None:
    data = b"c" * (256 * 1024)
    with _server(data) as (server, base_url):
        store, downloader = _downloader(tmp_path)
        spec = _spec(data, f"{base_url}/range")
        token = CancellationToken()

        def cancel_after_first_chunk(progress: DownloadProgress) -> None:
            if progress.downloaded_bytes:
                token.cancel()

        with pytest.raises(UpdateFailure) as caught:
            downloader.download(spec, "operation-1", token, cancel_after_first_chunk)

        assert caught.value.kind is UpdateErrorKind.CANCELLED
        stage = store.stage_path("operation-1")
        metadata = stage.with_name(f"{stage.name}.json")
        partial_size = stage.stat().st_size
        assert 0 < partial_size < len(data)
        metadata_text = metadata.read_text(encoding="utf-8")
        assert base_url not in metadata_text
        assert "url" not in metadata_text

        target = downloader.download(spec, "operation-1", CancellationToken())

    assert target.read_bytes() == data
    assert any(item[1] == f"bytes={partial_size}-" for item in server.requests_seen)


def test_hash_failure_and_redirect_rejection_never_create_object(tmp_path: Path) -> None:
    data = b"downloaded bytes"
    with _server(data) as (_, base_url):
        store, downloader = _downloader(tmp_path)
        bad_hash_spec = _spec(data, f"{base_url}/full", digest_data=b"different bytes!")
        with pytest.raises(UpdateFailure) as digest_error:
            downloader.download(bad_hash_spec, "operation-1", CancellationToken())
        assert digest_error.value.kind is UpdateErrorKind.INTEGRITY
        assert not store.object_path(bad_hash_spec.sha256).exists()

        redirect_spec = _spec(data, f"{base_url}/redirect-away")
        with pytest.raises(UpdateFailure) as redirect_error:
            downloader.download(redirect_spec, "operation-2", CancellationToken())
        assert redirect_error.value.kind is UpdateErrorKind.NETWORK
        assert not store.object_path(redirect_spec.sha256).exists()


def test_progress_callback_failure_does_not_corrupt_download(tmp_path: Path) -> None:
    data = b"callback safe" * 10_000
    with _server(data) as (_, base_url):
        _, downloader = _downloader(tmp_path)
        spec = _spec(data, f"{base_url}/full")

        def broken_callback(progress: DownloadProgress) -> None:
            raise RuntimeError("synthetic callback failure")

        target = downloader.download(
            spec,
            "operation-1",
            CancellationToken(),
            broken_callback,
        )

    assert target.read_bytes() == data


def test_network_error_does_not_expose_url_or_response_body(tmp_path: Path) -> None:
    data = b"unused"
    with _server(data) as (_, base_url):
        _, downloader = _downloader(tmp_path)
        private_url = f"{base_url}/error?token=synthetic-private"
        spec = _spec(data, private_url)

        with pytest.raises(UpdateFailure) as caught:
            downloader.download(spec, "operation-1", CancellationToken())

    assert caught.value.kind is UpdateErrorKind.NETWORK
    assert "synthetic-private" not in str(caught.value)
    assert "private-body" not in str(caught.value)


def test_malformed_resume_metadata_restarts_from_zero(tmp_path: Path) -> None:
    data = b"restart safely" * 10_000
    with _server(data) as (server, base_url):
        store, downloader = _downloader(tmp_path)
        spec = _spec(data, f"{base_url}/range")
        stage = store.stage_path("operation-1")
        stage.write_bytes(data[:1000])
        stage.with_name(f"{stage.name}.json").write_text(
            json.dumps({"schema_version": 1, "url": "private"}),
            encoding="utf-8",
        )

        target = downloader.download(spec, "operation-1", CancellationToken())

    assert target.read_bytes() == data
    assert server.requests_seen == [("/range", "", "")]


def test_cancellation_token_is_thread_safe() -> None:
    token = CancellationToken()

    assert token.cancelled is False
    token.cancel()
    assert token.cancelled is True
