"""Tests for detached Ed25519 verification of exact manifest bytes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from ailen.updates.contracts import UpdateErrorKind, UpdateManifestError
from ailen.updates.signatures import (
    OpenSslEd25519Verifier,
    UpdateSignatureError,
    VerifiedManifestLoader,
)


def _manifest_bytes(release_id: str = "ailen-0.4.1-beta.1") -> bytes:
    document = {
        "schema_version": 1,
        "release_id": release_id,
        "version": "0.4.1-beta.1",
        "sequence": 401001,
        "channel": "beta",
        "platforms": ["linux-amd64"],
        "config_schema_min": 1,
        "config_schema_max": 1,
        "migration_from_db_schema_min": 4,
        "migration_from_db_schema_max": 4,
        "db_schema_after": 4,
        "rollback_db_schema_min": 4,
        "rollback_db_schema_max": 4,
        "release_notes": "Synthetic signed fixture.",
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


def _run_checked(args: list[str]) -> None:
    subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=True,
    )


def _signed_files(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("OpenSSL is not installed")

    private_key = tmp_path / "ephemeral-test-private.pem"
    public_key = tmp_path / "ephemeral-test-public.pem"
    manifest = tmp_path / "manifest.json"
    signature = tmp_path / "manifest.sig"
    manifest.write_bytes(_manifest_bytes())
    _run_checked([openssl, "genpkey", "-algorithm", "Ed25519", "-out", str(private_key)])
    _run_checked(
        [openssl, "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)]
    )
    public_key.chmod(0o644)
    _run_checked(
        [
            openssl,
            "pkeyutl",
            "-sign",
            "-inkey",
            str(private_key),
            "-rawin",
            "-in",
            str(manifest),
            "-out",
            str(signature),
        ]
    )
    assert signature.stat().st_size == 64
    return manifest, signature, public_key, private_key


def test_verifies_exact_signed_bytes_and_loads_manifest(tmp_path: Path) -> None:
    manifest_path, signature_path, public_key_path, _ = _signed_files(tmp_path)
    loader = VerifiedManifestLoader(OpenSslEd25519Verifier())

    manifest = loader.load(manifest_path, signature_path, public_key_path)

    assert manifest.release_id == "ailen-0.4.1-beta.1"


def test_changed_manifest_byte_fails_closed(tmp_path: Path) -> None:
    manifest_path, signature_path, public_key_path, _ = _signed_files(tmp_path)
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")

    with pytest.raises(UpdateSignatureError) as caught:
        OpenSslEd25519Verifier().verify(manifest_path, signature_path, public_key_path)

    assert caught.value.kind is UpdateErrorKind.SIGNATURE_INVALID


@pytest.mark.parametrize("signature_size", [0, 63, 65])
def test_rejects_non_ed25519_signature_size(tmp_path: Path, signature_size: int) -> None:
    manifest_path, signature_path, public_key_path, _ = _signed_files(tmp_path)
    signature_path.write_bytes(b"x" * signature_size)

    with pytest.raises(UpdateSignatureError, match="signature") as caught:
        OpenSslEd25519Verifier().verify(manifest_path, signature_path, public_key_path)

    assert caught.value.kind is UpdateErrorKind.SIGNATURE_INVALID


def test_rejects_missing_or_broken_public_key_without_path_leak(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    signature_path = tmp_path / "manifest.sig"
    missing_key = tmp_path / "missing-public.pem"
    manifest_path.write_bytes(_manifest_bytes())
    signature_path.write_bytes(b"x" * 64)

    with pytest.raises(UpdateSignatureError) as missing:
        OpenSslEd25519Verifier().verify(manifest_path, signature_path, missing_key)
    assert missing.value.kind is UpdateErrorKind.SIGNATURE_INVALID
    assert str(tmp_path) not in str(missing.value)

    broken_key = tmp_path / "broken-public.pem"
    broken_key.write_text("not a public key", encoding="utf-8")
    with pytest.raises(UpdateSignatureError) as broken:
        OpenSslEd25519Verifier().verify(manifest_path, signature_path, broken_key)
    assert broken.value.kind is UpdateErrorKind.SIGNATURE_INVALID
    assert "not a public key" not in str(broken.value)


def test_rejects_symlinked_inputs_before_process_start(tmp_path: Path) -> None:
    manifest_path, signature_path, public_key_path, _ = _signed_files(tmp_path)
    manifest_link = tmp_path / "manifest-link.json"
    os.symlink(manifest_path, manifest_link)

    with pytest.raises(UpdateSignatureError, match="regular file"):
        OpenSslEd25519Verifier().verify(manifest_link, signature_path, public_key_path)


def test_rejects_oversized_manifest_before_process_start(tmp_path: Path) -> None:
    manifest_path = tmp_path / "oversized.json"
    signature_path = tmp_path / "manifest.sig"
    public_key_path = tmp_path / "public.pem"
    manifest_path.write_bytes(b"x" * (1024 * 1024 + 1))
    signature_path.write_bytes(b"x" * 64)
    public_key_path.write_text("synthetic", encoding="utf-8")

    with pytest.raises(UpdateSignatureError, match="size limit"):
        OpenSslEd25519Verifier().verify(manifest_path, signature_path, public_key_path)


def test_default_key_permissions_reject_group_or_world_writable_key(tmp_path: Path) -> None:
    manifest_path, signature_path, public_key_path, _ = _signed_files(tmp_path)
    public_key_path.chmod(0o666)

    with pytest.raises(UpdateSignatureError, match="permissions"):
        OpenSslEd25519Verifier().verify(manifest_path, signature_path, public_key_path)


def test_timeout_is_classified_as_verifier_unavailable(tmp_path: Path) -> None:
    manifest_path, signature_path, public_key_path, _ = _signed_files(tmp_path)

    def timeout_runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd="openssl", timeout=3.0)

    verifier = OpenSslEd25519Verifier(binary="openssl", runner=timeout_runner)
    with pytest.raises(UpdateSignatureError) as caught:
        verifier.verify(manifest_path, signature_path, public_key_path)

    assert caught.value.kind is UpdateErrorKind.SIGNATURE_UNAVAILABLE
    assert "openssl" not in str(caught.value).lower()


def test_missing_binary_is_classified_as_verifier_unavailable(tmp_path: Path) -> None:
    manifest_path, signature_path, public_key_path, _ = _signed_files(tmp_path)
    verifier = OpenSslEd25519Verifier(binary="/definitely/missing/openssl")

    with pytest.raises(UpdateSignatureError) as caught:
        verifier.verify(manifest_path, signature_path, public_key_path)

    assert caught.value.kind is UpdateErrorKind.SIGNATURE_UNAVAILABLE


def test_loader_verifies_before_attempting_to_parse(tmp_path: Path) -> None:
    calls: list[str] = []

    class RejectingVerifier:
        def verify(
            self,
            manifest_path: Path,
            signature_path: Path,
            public_key_path: Path,
        ) -> bytes:
            calls.append("verify")
            raise UpdateSignatureError(UpdateErrorKind.SIGNATURE_INVALID)

    manifest_path = tmp_path / "invalid.json"
    signature_path = tmp_path / "manifest.sig"
    public_key_path = tmp_path / "public.pem"
    manifest_path.write_bytes(b"not-json")
    signature_path.write_bytes(b"x" * 64)
    public_key_path.write_text("synthetic", encoding="utf-8")

    with pytest.raises(UpdateSignatureError):
        VerifiedManifestLoader(RejectingVerifier()).load(
            manifest_path, signature_path, public_key_path
        )

    assert calls == ["verify"]


def test_loader_parses_only_after_successful_verification(tmp_path: Path) -> None:
    calls: list[str] = []

    class AcceptingVerifier:
        def verify(
            self,
            manifest_path: Path,
            signature_path: Path,
            public_key_path: Path,
        ) -> bytes:
            calls.append("verify")
            return manifest_path.read_bytes()

    manifest_path = tmp_path / "invalid.json"
    signature_path = tmp_path / "manifest.sig"
    public_key_path = tmp_path / "public.pem"
    manifest_path.write_bytes(b"not-json")
    signature_path.write_bytes(b"x" * 64)
    public_key_path.write_text("synthetic", encoding="utf-8")

    with pytest.raises(UpdateManifestError):
        VerifiedManifestLoader(AcceptingVerifier()).load(
            manifest_path, signature_path, public_key_path
        )

    assert calls == ["verify"]


def test_loader_parses_the_exact_bytes_returned_by_verifier(tmp_path: Path) -> None:
    class ReplacingVerifier:
        def verify(
            self,
            manifest_path: Path,
            signature_path: Path,
            public_key_path: Path,
        ) -> bytes:
            verified_bytes = manifest_path.read_bytes()
            manifest_path.write_bytes(_manifest_bytes("ailen-unverified-replacement"))
            return verified_bytes

    manifest_path = tmp_path / "manifest.json"
    signature_path = tmp_path / "manifest.sig"
    public_key_path = tmp_path / "public.pem"
    manifest_path.write_bytes(_manifest_bytes())
    signature_path.write_bytes(b"x" * 64)
    public_key_path.write_text("synthetic", encoding="utf-8")

    manifest = VerifiedManifestLoader(ReplacingVerifier()).load(
        manifest_path,
        signature_path,
        public_key_path,
    )

    assert manifest.release_id == "ailen-0.4.1-beta.1"
