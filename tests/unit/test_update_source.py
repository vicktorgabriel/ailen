"""Tests for bounded HTTPS retrieval before manifest parsing."""

from __future__ import annotations

import http.client
import json
import os
import stat
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Self
from urllib.request import Request

import pytest

from ailen.updates.contracts import (
    ReleaseManifest,
    UpdateChannel,
    UpdateErrorKind,
    UpdateFailure,
)
from ailen.updates.signatures import (
    UpdateSignatureError,
    VerifiedManifestLoader,
)
from ailen.updates.source import (
    HttpsByteFetcher,
    HttpsReleaseSource,
    HttpsUrlPolicy,
    ValidatingRedirectHandler,
)


def _manifest_bytes(channel: str = "beta") -> bytes:
    document = {
        "schema_version": 1,
        "release_id": "ailen-0.4.1-beta.1",
        "version": "0.4.1-beta.1",
        "sequence": 401001,
        "channel": channel,
        "platforms": ["linux-amd64"],
        "config_schema_min": 1,
        "config_schema_max": 1,
        "migration_from_db_schema_min": 4,
        "migration_from_db_schema_max": 4,
        "db_schema_after": 4,
        "rollback_db_schema_min": 4,
        "rollback_db_schema_max": 4,
        "release_notes": "Synthetic source fixture.",
        "artifacts": [
            {
                "artifact_id": "ailen-core-linux-amd64-0.4.1-beta.1",
                "kind": "release",
                "url": "https://updates.example.invalid/core.tar.gz",
                "sha256": "a" * 64,
                "size_bytes": 1024,
                "expanded_size_bytes": 4096,
                "platform": "linux-amd64",
                "media_type": "application/gzip",
            }
        ],
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


class RecordingFetcher:
    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, int]] = []

    def fetch(self, url: str, *, max_bytes: int) -> bytes:
        self.calls.append((url, max_bytes))
        return self.responses[url]


class RecordingVerifier:
    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.calls: list[tuple[Path, Path, Path]] = []
        self.manifest_bytes = b""
        self.signature_bytes = b""
        self.manifest_mode = 0
        self.signature_mode = 0

    def verify(
        self,
        manifest_path: Path,
        signature_path: Path,
        public_key_path: Path,
    ) -> bytes:
        self.calls.append((manifest_path, signature_path, public_key_path))
        self.manifest_bytes = manifest_path.read_bytes()
        self.signature_bytes = signature_path.read_bytes()
        self.manifest_mode = stat.S_IMODE(manifest_path.stat().st_mode)
        self.signature_mode = stat.S_IMODE(signature_path.stat().st_mode)
        if self.reject:
            raise UpdateSignatureError(UpdateErrorKind.SIGNATURE_INVALID)
        return self.manifest_bytes


def _source(
    tmp_path: Path,
    *,
    manifest: bytes,
    signature: bytes = b"s" * 64,
    verifier: RecordingVerifier | None = None,
) -> tuple[HttpsReleaseSource, RecordingFetcher, RecordingVerifier, Path]:
    manifest_url = "https://updates.example.invalid/beta/manifest.json"
    signature_url = "https://updates.example.invalid/beta/manifest.sig"
    fetcher = RecordingFetcher({manifest_url: manifest, signature_url: signature})
    actual_verifier = verifier or RecordingVerifier()
    public_key = tmp_path / "public.pem"
    public_key.write_text("synthetic public test key", encoding="utf-8")
    source = HttpsReleaseSource(
        manifest_url=manifest_url,
        signature_url=signature_url,
        public_key_path=public_key,
        staging_dir=tmp_path / "staging",
        loader=VerifiedManifestLoader(actual_verifier),
        fetcher=fetcher,
    )
    return source, fetcher, actual_verifier, public_key


def test_fetches_bounded_bytes_verifies_then_cleans_private_staging(tmp_path: Path) -> None:
    source, fetcher, verifier, public_key = _source(tmp_path, manifest=_manifest_bytes())

    manifest = source.fetch(UpdateChannel.BETA)

    assert manifest.release_id == "ailen-0.4.1-beta.1"
    assert fetcher.calls == [
        ("https://updates.example.invalid/beta/manifest.json", 1024 * 1024),
        ("https://updates.example.invalid/beta/manifest.sig", 64),
    ]
    assert verifier.manifest_bytes == _manifest_bytes()
    assert verifier.signature_bytes == b"s" * 64
    assert verifier.manifest_mode == 0o600
    assert verifier.signature_mode == 0o600
    assert verifier.calls[0][2] == public_key
    assert not verifier.calls[0][0].exists()
    assert not verifier.calls[0][1].exists()
    assert stat.S_IMODE((tmp_path / "staging").stat().st_mode) == 0o700


def test_rejects_channel_mismatch_after_verified_parse(tmp_path: Path) -> None:
    source, _, verifier, _ = _source(tmp_path, manifest=_manifest_bytes("stable"))

    with pytest.raises(UpdateFailure) as caught:
        source.fetch(UpdateChannel.BETA)

    assert caught.value.kind is UpdateErrorKind.INCOMPATIBLE
    assert len(verifier.calls) == 1


@pytest.mark.parametrize(
    ("manifest", "signature"),
    [
        (b"x" * (1024 * 1024 + 1), b"s" * 64),
        (_manifest_bytes(), b"s" * 65),
        (_manifest_bytes(), b"s" * 63),
    ],
)
def test_enforces_size_caps_even_when_fetcher_violates_contract(
    tmp_path: Path,
    manifest: bytes,
    signature: bytes,
) -> None:
    source, _, verifier, _ = _source(
        tmp_path,
        manifest=manifest,
        signature=signature,
    )

    with pytest.raises(UpdateFailure) as caught:
        source.fetch(UpdateChannel.BETA)

    assert caught.value.kind is UpdateErrorKind.INTEGRITY
    assert verifier.calls == []


def test_signature_failure_wins_over_invalid_json_and_cleans_files(tmp_path: Path) -> None:
    verifier = RecordingVerifier(reject=True)
    source, _, _, _ = _source(tmp_path, manifest=b"not-json", verifier=verifier)

    with pytest.raises(UpdateSignatureError):
        source.fetch(UpdateChannel.BETA)

    assert len(verifier.calls) == 1
    assert not verifier.calls[0][0].exists()
    assert not verifier.calls[0][1].exists()


@pytest.mark.parametrize(
    "url",
    [
        "http://updates.example.invalid/manifest.json",
        "https://user:password@updates.example.invalid/manifest.json",
        "https://updates.example.invalid/manifest.json#fragment",
        "https:///manifest.json",
    ],
)
def test_https_policy_rejects_unsafe_urls_without_echoing_them(url: str) -> None:
    with pytest.raises(UpdateFailure) as caught:
        HttpsUrlPolicy().validate(url)

    assert caught.value.kind is UpdateErrorKind.NETWORK
    assert url not in str(caught.value)
    assert "password" not in str(caught.value)


def test_redirect_handler_validates_every_target_before_following() -> None:
    handler = ValidatingRedirectHandler(HttpsUrlPolicy())
    request = Request("https://updates.example.invalid/manifest.json")

    with pytest.raises(UpdateFailure) as caught:
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            Message(),
            "http://updates.example.invalid/manifest.json",
        )

    assert caught.value.kind is UpdateErrorKind.NETWORK


class FakeResponse:
    def __init__(self, body: bytes, final_url: str) -> None:
        self._body = body
        self._final_url = final_url

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self._body if amount < 0 else self._body[:amount]

    def geturl(self) -> str:
        return self._final_url


class FakeOpener:
    def __init__(self, response: FakeResponse | BaseException) -> None:
        self._response = response
        self.requests: list[tuple[str, float]] = []

    def open(self, request: Request, timeout: float) -> FakeResponse:
        self.requests.append((request.full_url, timeout))
        if isinstance(self._response, BaseException):
            raise self._response
        return self._response


def test_byte_fetcher_rejects_oversized_response() -> None:
    opener = FakeOpener(
        FakeResponse(b"12345", "https://updates.example.invalid/manifest.json")
    )
    fetcher = HttpsByteFetcher(opener=opener)

    with pytest.raises(UpdateFailure) as caught:
        fetcher.fetch("https://updates.example.invalid/manifest.json", max_bytes=4)

    assert caught.value.kind is UpdateErrorKind.INTEGRITY


def test_byte_fetcher_revalidates_final_url_after_redirect() -> None:
    opener = FakeOpener(FakeResponse(b"safe", "http://updates.example.invalid/final"))
    fetcher = HttpsByteFetcher(opener=opener)

    with pytest.raises(UpdateFailure) as caught:
        fetcher.fetch("https://updates.example.invalid/start", max_bytes=4)

    assert caught.value.kind is UpdateErrorKind.NETWORK


def test_byte_fetcher_redacts_http_error_body_and_url() -> None:
    private_url = "https://updates.example.invalid/manifest?token=synthetic-secret"
    error = urllib.error.HTTPError(
        private_url,
        503,
        "private-body",
        Message(),
        None,
    )
    fetcher = HttpsByteFetcher(opener=FakeOpener(error))

    with pytest.raises(UpdateFailure) as caught:
        fetcher.fetch(private_url, max_bytes=1024)

    assert caught.value.kind is UpdateErrorKind.NETWORK
    assert "synthetic-secret" not in str(caught.value)
    assert "private-body" not in str(caught.value)


def test_byte_fetcher_wraps_http_protocol_errors() -> None:
    error = http.client.IncompleteRead(b"private-partial-body", 100)
    fetcher = HttpsByteFetcher(opener=FakeOpener(error))

    with pytest.raises(UpdateFailure) as caught:
        fetcher.fetch("https://updates.example.invalid/manifest", max_bytes=1024)

    assert caught.value.kind is UpdateErrorKind.NETWORK
    assert "private-partial-body" not in str(caught.value)


def test_source_rejects_staging_directory_owned_by_another_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _, verifier, _ = _source(tmp_path, manifest=_manifest_bytes())
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir(mode=0o700)
    real_lstat = Path.lstat

    def foreign_owner_lstat(path: Path) -> os.stat_result:
        result = real_lstat(path)
        if path == staging_dir:
            values = list(result)
            values[4] = os.geteuid() + 1
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "lstat", foreign_owner_lstat)

    with pytest.raises(UpdateFailure) as caught:
        source.fetch(UpdateChannel.BETA)

    assert caught.value.kind is UpdateErrorKind.INTEGRITY
    assert verifier.calls == []


def test_source_type_is_release_manifest(tmp_path: Path) -> None:
    source, _, _, _ = _source(tmp_path, manifest=_manifest_bytes())

    result = source.fetch(UpdateChannel.BETA)

    assert isinstance(result, ReleaseManifest)
