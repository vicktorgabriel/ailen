"""Acceptance tests for the complete signed Lab update vertical.

All release bytes, trust material, transport responses, installation roots and
journal files live under ``tmp_path``.  The production HTTPS policy still sees
HTTPS URLs, while injected fetcher/opener boundaries guarantee no network or
system service access.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import random
import shutil
import subprocess
import tarfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import pytest

from ailen.updates.activation import (
    AppliancePaths,
    HealthGateResult,
    PreparedRelease,
    ReleaseActivator,
    SafeReleaseExtractor,
)
from ailen.updates.artifact_store import ContentAddressedArtifactStore
from ailen.updates.contracts import (
    ArtifactKind,
    ArtifactSpec,
    OperationStatus,
    ReleaseManifest,
    UpdateChannel,
    UpdateErrorKind,
    UpdateFailure,
    UpdatePhase,
)
from ailen.updates.downloader import (
    CancellationToken,
    DownloadProgress,
    HttpsArtifactDownloader,
)
from ailen.updates.journal import OperationJournal
from ailen.updates.service import LocalUpdateService
from ailen.updates.signatures import OpenSslEd25519Verifier, VerifiedManifestLoader
from ailen.updates.source import HttpsReleaseSource

_MANIFEST_URL = "https://updates.example.invalid/beta/manifest.json"
_SIGNATURE_URL = "https://updates.example.invalid/beta/manifest.json.sig"


def _run_checked(arguments: list[str]) -> None:
    subprocess.run(
        arguments,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=True,
    )


@dataclass(frozen=True)
class _KeyPair:
    private: Path
    public: Path


def _key_pair(root: Path) -> _KeyPair:
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("OpenSSL is not installed")
    root.mkdir(mode=0o700, parents=True)
    private = root / "ephemeral-test-private.pem"
    public = root / "ephemeral-test-public.pem"
    _run_checked([openssl, "genpkey", "-algorithm", "Ed25519", "-out", str(private)])
    _run_checked([openssl, "pkey", "-in", str(private), "-pubout", "-out", str(public)])
    public.chmod(0o644)
    return _KeyPair(private=private, public=public)


def _archive(root: Path, version: str, *, payload_size: int = 0) -> tuple[Path, int]:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = root / f"ailen-{version}.tar.gz"
    files = {
        "VERSION": f"{version}\n".encode(),
        "health/ready": b"ready\n",
    }
    if payload_size:
        files["payload/model.bin"] = random.Random(401_001).randbytes(payload_size)
    with tarfile.open(path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mode = 0o644
            member.mtime = 0
            member.uid = 0
            member.gid = 0
            archive.addfile(member, io.BytesIO(content))
    return path, sum(len(content) for content in files.values())


@dataclass(frozen=True)
class _SignedRelease:
    release_id: str
    version: str
    sequence: int
    manifest_bytes: bytes
    signature_bytes: bytes
    artifact_bytes: bytes
    spec: ArtifactSpec


class _ByteFetcher:
    def __init__(self) -> None:
        self.responses: dict[str, bytes] = {}
        self.calls: list[tuple[str, int]] = []

    def fetch(self, url: str, *, max_bytes: int) -> bytes:
        self.calls.append((url, max_bytes))
        return self.responses[url]


class _MemoryResponse:
    def __init__(
        self,
        *,
        url: str,
        status: int,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        self._url = url
        self.status = status
        self.headers = headers
        self._body = io.BytesIO(body)

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self._url

    def close(self) -> None:
        self._body.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class _ArtifactOpener:
    def __init__(self) -> None:
        self.artifacts: dict[str, tuple[bytes, str]] = {}
        self.requests: list[tuple[str, str, str]] = []

    def open(
        self,
        request: urllib.request.Request,
        timeout: float,
    ) -> _MemoryResponse:
        _ = timeout
        url = request.full_url
        data, etag = self.artifacts[url]
        headers = {key.lower(): value for key, value in request.header_items()}
        range_header = headers.get("range", "")
        if_range = headers.get("if-range", "")
        self.requests.append((url, range_header, if_range))
        if range_header:
            start = int(range_header.removeprefix("bytes=").removesuffix("-"))
            body = data[start:]
            response_headers = {
                "Content-Length": str(len(body)),
                "Content-Range": f"bytes {start}-{len(data) - 1}/{len(data)}",
                "ETag": etag,
            }
            return _MemoryResponse(
                url=url,
                status=206,
                body=body,
                headers=response_headers,
            )
        return _MemoryResponse(
            url=url,
            status=200,
            body=data,
            headers={"Content-Length": str(len(data)), "ETag": etag},
        )


class _Publisher:
    def __init__(
        self,
        root: Path,
        keys: _KeyPair,
        fetcher: _ByteFetcher,
        opener: _ArtifactOpener,
    ) -> None:
        self._root = root
        self._keys = keys
        self._fetcher = fetcher
        self._opener = opener

    def publish(
        self,
        version: str,
        sequence: int,
        *,
        payload_size: int = 0,
    ) -> _SignedRelease:
        openssl = shutil.which("openssl")
        assert openssl is not None
        release_root = self._root / version
        archive_path, expanded_size = _archive(
            release_root,
            version,
            payload_size=payload_size,
        )
        artifact = archive_path.read_bytes()
        digest = hashlib.sha256(artifact).hexdigest()
        release_id = f"ailen-{version}"
        artifact_url = f"https://updates.example.invalid/artifacts/{version}.tar.gz"
        document = {
            "schema_version": 1,
            "release_id": release_id,
            "version": version,
            "sequence": sequence,
            "channel": "beta",
            "platforms": ["linux-amd64"],
            "config_schema_min": 1,
            "config_schema_max": 1,
            "migration_from_db_schema_min": 4,
            "migration_from_db_schema_max": 4,
            "db_schema_after": 4,
            "rollback_db_schema_min": 4,
            "rollback_db_schema_max": 4,
            "release_notes": f"Synthetic signed release {version}.",
            "artifacts": [
                {
                    "artifact_id": f"ailen-core-linux-amd64-{version}",
                    "kind": "release",
                    "url": artifact_url,
                    "sha256": digest,
                    "size_bytes": len(artifact),
                    "expanded_size_bytes": expanded_size + 4096,
                    "platform": "linux-amd64",
                    "media_type": "application/gzip",
                }
            ],
        }
        manifest_bytes = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest_path = release_root / "manifest.json"
        signature_path = release_root / "manifest.json.sig"
        manifest_path.write_bytes(manifest_bytes)
        _run_checked(
            [
                openssl,
                "pkeyutl",
                "-sign",
                "-inkey",
                str(self._keys.private),
                "-rawin",
                "-in",
                str(manifest_path),
                "-out",
                str(signature_path),
            ]
        )
        signature = signature_path.read_bytes()
        assert len(signature) == 64
        spec = ArtifactSpec(
            artifact_id=f"ailen-core-linux-amd64-{version}",
            kind=ArtifactKind.RELEASE,
            url=artifact_url,
            sha256=digest,
            size_bytes=len(artifact),
            expanded_size_bytes=expanded_size + 4096,
            platform="linux-amd64",
            media_type="application/gzip",
        )
        self._fetcher.responses = {
            _MANIFEST_URL: manifest_bytes,
            _SIGNATURE_URL: signature,
        }
        self._opener.artifacts[artifact_url] = (artifact, f'"fixture-{sequence}"')
        return _SignedRelease(
            release_id=release_id,
            version=version,
            sequence=sequence,
            manifest_bytes=manifest_bytes,
            signature_bytes=signature,
            artifact_bytes=artifact,
            spec=spec,
        )


class _Preparer:
    def __init__(self, paths: AppliancePaths) -> None:
        self._paths = paths
        self._extractor = SafeReleaseExtractor()

    def prepare(
        self,
        artifact_path: Path,
        manifest: ReleaseManifest,
        spec: ArtifactSpec,
    ) -> PreparedRelease:
        return self._extractor.prepare(artifact_path, manifest, spec, self._paths)


class _Preflight:
    def check(self, release_dir: Path) -> HealthGateResult:
        healthy = (release_dir / "VERSION").is_file() and (
            release_dir / "health" / "ready"
        ).is_file()
        return HealthGateResult(
            healthy,
            "PREFLIGHT_OK" if healthy else "PREFLIGHT_FAILED",
            "synthetic",
        )


class _Controller:
    def __init__(self) -> None:
        self.running: Path | None = None
        self.calls: list[tuple[str, Path | None]] = []

    def stop(self) -> None:
        self.calls.append(("stop", None))
        self.running = None

    def start(self, release_dir: Path) -> None:
        if not release_dir.is_dir():
            raise RuntimeError("synthetic release missing")
        self.calls.append(("start", release_dir))
        self.running = release_dir


class _Health:
    def __init__(self, *healthy: bool) -> None:
        self._results = list(healthy)

    def wait_healthy(self, timeout_seconds: float) -> HealthGateResult:
        assert timeout_seconds == 1.0
        healthy = self._results.pop(0) if self._results else True
        return HealthGateResult(
            healthy,
            "HEALTHY" if healthy else "HEALTH_FAILED",
            "synthetic",
        )


class _Ids:
    def __init__(self) -> None:
        self._value = 0

    def operation(self) -> str:
        self._value += 1
        return f"operation-{self._value}"

    def approval(self) -> str:
        return f"approval-{self._value}"


@dataclass
class _Vertical:
    paths: AppliancePaths
    source: HttpsReleaseSource
    store: ContentAddressedArtifactStore
    downloader: HttpsArtifactDownloader
    journal: OperationJournal
    preparer: _Preparer
    activator: ReleaseActivator
    controller: _Controller
    ids: _Ids

    def service(
        self,
        *,
        current_sequence: int = 401_000,
        installed_version: str = "0.4.0-dev.0",
    ) -> LocalUpdateService:
        return LocalUpdateService(
            source=self.source,
            downloader=self.downloader,
            journal=self.journal,
            channel=UpdateChannel.BETA,
            platform="linux-amd64",
            config_schema=1,
            current_db_schema=4,
            current_sequence=current_sequence,
            installed_version=installed_version,
            mode="LAB_SIMULATION",
            operation_id_factory=self.ids.operation,
            approval_token_factory=self.ids.approval,
            preparer=self.preparer,
            activator=self.activator,
        )


def _vertical(tmp_path: Path, *health: bool) -> tuple[_Vertical, _Publisher, _ByteFetcher, _ArtifactOpener]:
    keys = _key_pair(tmp_path / "trust")
    fetcher = _ByteFetcher()
    opener = _ArtifactOpener()
    publisher = _Publisher(tmp_path / "publisher", keys, fetcher, opener)
    paths = AppliancePaths(
        install_root=(tmp_path / "appliance" / "install").resolve(),
        state_root=(tmp_path / "appliance" / "state").resolve(),
    )
    store = ContentAddressedArtifactStore(paths.state_root / "artifacts")
    journal = OperationJournal(paths.state_root / "provisioning" / "operations")
    source = HttpsReleaseSource(
        manifest_url=_MANIFEST_URL,
        signature_url=_SIGNATURE_URL,
        public_key_path=keys.public,
        staging_dir=paths.state_root / "provisioning" / "manifest-staging",
        loader=VerifiedManifestLoader(OpenSslEd25519Verifier()),
        fetcher=fetcher,
    )
    downloader = HttpsArtifactDownloader(store=store, opener=opener)
    controller = _Controller()
    activator = ReleaseActivator(
        paths=paths,
        journal=journal,
        preflight=_Preflight(),
        controller=controller,
        health=_Health(*health),
        probation_timeout_seconds=1.0,
    )
    vertical = _Vertical(
        paths=paths,
        source=source,
        store=store,
        downloader=downloader,
        journal=journal,
        preparer=_Preparer(paths),
        activator=activator,
        controller=controller,
        ids=_Ids(),
    )
    return vertical, publisher, fetcher, opener


def _wait_for_phase(
    service: LocalUpdateService,
    operation_id: str,
    expected: frozenset[UpdatePhase],
) -> OperationStatus:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        status = service.status(operation_id)
        if status.phase in expected:
            return status
        time.sleep(0.01)
    raise AssertionError(f"operation did not reach expected phase: {service.status(operation_id)}")


def _download_and_prepare(
    service: LocalUpdateService,
    release: _SignedRelease,
) -> str:
    checked = service.check()
    assert checked.ok is True
    planned = service.plan(release.release_id)
    assert planned.ok is True
    assert planned.operation_id
    assert planned.approval_token
    started = service.start_download(release.release_id, planned.approval_token)
    assert started.ok is True
    status = _wait_for_phase(
        service,
        planned.operation_id,
        frozenset({UpdatePhase.PREPARED, UpdatePhase.FAILED}),
    )
    assert status.phase is UpdatePhase.PREPARED
    return planned.operation_id


def _link_target(link: Path) -> Path:
    raw = Path(os.readlink(link))
    return (link.parent / raw).resolve(strict=True)


def test_signed_release_reaches_active_without_external_side_effects(tmp_path: Path) -> None:
    vertical, publisher, fetcher, _ = _vertical(tmp_path, True)
    release = publisher.publish("0.4.1-beta.1", 401_001)
    outside = tmp_path / "outside-appliance.txt"
    outside.write_text("unchanged", encoding="utf-8")
    service = vertical.service()
    try:
        operation_id = _download_and_prepare(service, release)

        result = service.activate(operation_id)

        assert result.ok is True
        assert result.code == "ACTIVATED"
        status = service.status(operation_id)
        assert status.phase is UpdatePhase.ACTIVE
        assert _link_target(vertical.paths.current_link).name == release.version
        active = vertical.paths.releases_dir / release.version
        assert (active / "VERSION").read_text(encoding="utf-8") == f"{release.version}\n"
        target = vertical.store.object_path(release.spec.sha256)
        assert target.read_bytes() == release.artifact_bytes
        assert hashlib.sha256(target.read_bytes()).hexdigest() == release.spec.sha256
        assert fetcher.calls[:2] == [
            (_MANIFEST_URL, 1024 * 1024),
            (_SIGNATURE_URL, 64),
        ]
        assert outside.read_text(encoding="utf-8") == "unchanged"
        assert not (tmp_path / "escape").exists()
    finally:
        service.close()


def test_unhealthy_signed_candidate_rolls_back_to_previous_release(tmp_path: Path) -> None:
    vertical, publisher, _, _ = _vertical(tmp_path, True, False)
    release_a = publisher.publish("0.4.1-beta.1", 401_001)
    service = vertical.service()
    database_sentinel = tmp_path / "private-memory.sqlite"
    database_sentinel.write_bytes(b"synthetic database sentinel")
    original_database_digest = hashlib.sha256(database_sentinel.read_bytes()).hexdigest()
    try:
        operation_a = _download_and_prepare(service, release_a)
        assert service.activate(operation_a).ok is True
        active_a = vertical.paths.releases_dir / release_a.version
        assert _link_target(vertical.paths.current_link) == active_a

        release_b = publisher.publish("0.4.2-beta.1", 401_002)
        operation_b = _download_and_prepare(service, release_b)
        attempted_b = vertical.paths.releases_dir / release_b.version

        result = service.activate(operation_b)

        assert result.ok is False
        assert result.code == "ACTIVATION"
        record = vertical.journal.read(operation_b)
        assert record.phase is UpdatePhase.ROLLED_BACK
        assert record.error_kind is UpdateErrorKind.ACTIVATION
        assert record.error_message == "candidate health gate failed"
        assert _link_target(vertical.paths.current_link) == active_a
        assert active_a.is_dir()
        assert attempted_b.is_dir()
        assert vertical.store.object_path(release_a.spec.sha256).is_file()
        assert vertical.store.object_path(release_b.spec.sha256).is_file()
        assert hashlib.sha256(database_sentinel.read_bytes()).hexdigest() == original_database_digest

        snapshot = service.snapshot()
        assert snapshot.effective_version == release_a.version
        assert snapshot.candidate_version == release_b.version
        assert snapshot.candidate_release_id == release_b.release_id
        assert snapshot.operation is not None
        assert snapshot.operation.phase is UpdatePhase.ROLLED_BACK
        public_text = (
            f"{snapshot.detail} {snapshot.release_notes} "
            f"{snapshot.operation.error_message}"
        )
        assert str(tmp_path) not in public_text
    finally:
        service.close()


def test_interrupted_download_is_reverified_reapproved_and_resumed(tmp_path: Path) -> None:
    vertical, publisher, _, opener = _vertical(tmp_path, True)
    release = publisher.publish(
        "0.4.1-beta.1",
        401_001,
        payload_size=256 * 1024,
    )
    first_service = vertical.service()
    checked = first_service.check()
    assert checked.ok is True
    planned = first_service.plan(release.release_id)
    assert planned.ok is True
    operation_id = planned.operation_id
    first_service.close()

    vertical.journal.transition(
        operation_id,
        expected=frozenset({UpdatePhase.PLANNED}),
        phase=UpdatePhase.DOWNLOADING,
    )
    token = CancellationToken()

    def cancel_after_first_chunk(progress: DownloadProgress) -> None:
        if progress.downloaded_bytes:
            token.cancel()

    transfer_id = f"{operation_id}-1"
    with pytest.raises(UpdateFailure) as cancelled:
        vertical.downloader.download(
            release.spec,
            transfer_id,
            token,
            cancel_after_first_chunk,
        )
    assert cancelled.value.kind is UpdateErrorKind.CANCELLED
    partial = vertical.store.stage_path(transfer_id)
    partial_size = partial.stat().st_size
    assert 0 < partial_size < release.spec.size_bytes

    resumed_service = vertical.service()
    try:
        assert resumed_service.check().ok is True
        resumed_plan = resumed_service.plan(release.release_id)
        assert resumed_plan.code == "RESUME_APPROVAL_REQUIRED"
        assert resumed_plan.operation_id == operation_id

        started = resumed_service.start_download(
            release.release_id,
            resumed_plan.approval_token,
        )
        assert started.ok is True
        status = _wait_for_phase(
            resumed_service,
            operation_id,
            frozenset({UpdatePhase.PREPARED, UpdatePhase.FAILED}),
        )

        assert status.phase is UpdatePhase.PREPARED
        target = vertical.store.object_path(release.spec.sha256)
        assert target.stat().st_size == release.spec.size_bytes
        assert target.read_bytes() == release.artifact_bytes
        assert any(
            url == release.spec.url
            and range_header == f"bytes={partial_size}-"
            and if_range == f'"fixture-{release.sequence}"'
            for url, range_header, if_range in opener.requests
        )
        assert not partial.exists()
        assert not partial.with_name(f"{partial.name}.json").exists()
        objects = [path for path in (vertical.paths.state_root / "artifacts" / "objects").rglob("*") if path.is_file()]
        assert objects == [target]
    finally:
        resumed_service.close()
