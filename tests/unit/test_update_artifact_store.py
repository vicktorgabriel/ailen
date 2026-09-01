"""Behavioral tests for the immutable content-addressed artifact store."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

from ailen.updates.artifact_store import ContentAddressedArtifactStore
from ailen.updates.contracts import ArtifactKind, ArtifactSpec, UpdateErrorKind, UpdateFailure


def _spec(data: bytes, *, artifact_id: str = "ailen-core-linux-amd64") -> ArtifactSpec:
    return ArtifactSpec(
        artifact_id=artifact_id,
        kind=ArtifactKind.RELEASE,
        url="https://updates.example.invalid/core.tar.gz",
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        expanded_size_bytes=max(len(data), 1) * 4,
        platform="linux-amd64",
        media_type="application/gzip",
    )


def _stage(store: ContentAddressedArtifactStore, operation_id: str, data: bytes) -> Path:
    path = store.stage_path(operation_id)
    path.write_bytes(data)
    return path


@pytest.mark.parametrize("operation_id", ["../escape", "a/b", "", ".", ".."])
def test_stage_path_rejects_traversal_and_invalid_ids(
    tmp_path: Path,
    operation_id: str,
) -> None:
    store = ContentAddressedArtifactStore(tmp_path / "store")

    with pytest.raises(UpdateFailure) as caught:
        store.stage_path(operation_id)

    assert caught.value.kind is UpdateErrorKind.INTEGRITY
    assert not (tmp_path / "escape.part").exists()


@pytest.mark.parametrize("digest", ["../escape", "A" * 64, "a" * 63, "g" * 64])
def test_object_path_rejects_invalid_digest(tmp_path: Path, digest: str) -> None:
    store = ContentAddressedArtifactStore(tmp_path / "store")

    with pytest.raises(UpdateFailure) as caught:
        store.object_path(digest)

    assert caught.value.kind is UpdateErrorKind.INTEGRITY


def test_paths_are_deterministic_and_confined_to_store(tmp_path: Path) -> None:
    root = tmp_path / "store"
    digest = "ab" + "c" * 62
    store = ContentAddressedArtifactStore(root)

    stage = store.stage_path("operation-1")
    object_path = store.object_path(digest)

    assert stage == root / "staging" / "operation-1.part"
    assert object_path == root / "objects" / "ab" / digest
    assert stage.parent.is_dir()
    assert stat.S_IMODE(stage.parent.stat().st_mode) == 0o700


def test_construction_is_side_effect_free(tmp_path: Path) -> None:
    root = tmp_path / "store"

    ContentAddressedArtifactStore(root)

    assert not root.exists()


def test_commit_verifies_and_atomically_installs_read_only_object(tmp_path: Path) -> None:
    root = tmp_path / "store"
    data = b"verified synthetic artifact"
    spec = _spec(data)
    store = ContentAddressedArtifactStore(root)
    staged = _stage(store, "operation-1", data)

    target = store.commit(staged, spec)

    assert target == root / "objects" / spec.sha256[:2] / spec.sha256
    assert target.read_bytes() == data
    assert stat.S_IMODE(target.stat().st_mode) == 0o444
    assert not staged.exists()


@pytest.mark.parametrize("failure", ["size", "hash"])
def test_integrity_failure_never_creates_object_and_preserves_stage(
    tmp_path: Path,
    failure: str,
) -> None:
    expected = b"expected artifact"
    actual = expected + b"x" if failure == "size" else b"unexpected-artf"
    assert len(actual) != len(expected) or hashlib.sha256(actual).digest() != hashlib.sha256(
        expected
    ).digest()
    if failure == "hash":
        actual = b"x" * len(expected)
    spec = _spec(expected)
    store = ContentAddressedArtifactStore(tmp_path / "store")
    staged = _stage(store, "operation-1", actual)

    with pytest.raises(UpdateFailure) as caught:
        store.commit(staged, spec)

    assert caught.value.kind is UpdateErrorKind.INTEGRITY
    assert not store.object_path(spec.sha256).exists()
    assert staged.exists()


def test_valid_existing_object_is_deduplicated(tmp_path: Path) -> None:
    data = b"shared immutable artifact"
    spec = _spec(data)
    store = ContentAddressedArtifactStore(tmp_path / "store")
    first = store.commit(_stage(store, "operation-1", data), spec)
    second_stage = _stage(store, "operation-2", data)

    second = store.commit(second_stage, spec)

    assert second == first
    assert first.read_bytes() == data
    assert not second_stage.exists()


def test_corrupt_existing_object_fails_without_overwrite(tmp_path: Path) -> None:
    data = b"canonical artifact"
    corrupt = b"corrupted artifact"
    assert len(data) == len(corrupt)
    spec = _spec(data)
    store = ContentAddressedArtifactStore(tmp_path / "store")
    target = store.commit(_stage(store, "operation-1", data), spec)
    target.chmod(0o644)
    target.write_bytes(corrupt)
    staged = _stage(store, "operation-2", data)

    with pytest.raises(UpdateFailure) as caught:
        store.commit(staged, spec)

    assert caught.value.kind is UpdateErrorKind.INTEGRITY
    assert target.read_bytes() == corrupt
    assert staged.exists()


def test_remove_refuses_protected_digest_then_removes_unprotected_object(tmp_path: Path) -> None:
    data = b"protected artifact"
    spec = _spec(data)
    store = ContentAddressedArtifactStore(tmp_path / "store")
    target = store.commit(_stage(store, "operation-1", data), spec)

    assert store.remove(spec.sha256, frozenset({spec.sha256})) is False
    assert target.exists()
    assert store.remove(spec.sha256, frozenset()) is True
    assert not target.exists()
    assert store.remove(spec.sha256, frozenset()) is False


def test_commit_rejects_symlink_stage_without_touching_target(tmp_path: Path) -> None:
    data = b"outside data"
    spec = _spec(data)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(data)
    store = ContentAddressedArtifactStore(tmp_path / "store")
    staged = store.stage_path("operation-1")
    os.symlink(outside, staged)

    with pytest.raises(UpdateFailure) as caught:
        store.commit(staged, spec)

    assert caught.value.kind is UpdateErrorKind.INTEGRITY
    assert outside.read_bytes() == data
    assert not store.object_path(spec.sha256).exists()


def test_commit_and_remove_reject_symlink_object_without_following_it(tmp_path: Path) -> None:
    data = b"canonical object"
    spec = _spec(data)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside remains")
    store = ContentAddressedArtifactStore(tmp_path / "store")
    staged = _stage(store, "operation-1", data)
    target = store.object_path(spec.sha256)
    target.parent.mkdir(mode=0o700, parents=True)
    os.symlink(outside, target)

    with pytest.raises(UpdateFailure):
        store.commit(staged, spec)
    with pytest.raises(UpdateFailure):
        store.remove(spec.sha256, frozenset())

    assert target.is_symlink()
    assert outside.read_bytes() == b"outside remains"
    assert staged.exists()


def test_symlinked_store_root_is_rejected_without_writes(tmp_path: Path) -> None:
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    linked_root = tmp_path / "linked-root"
    os.symlink(real_root, linked_root)
    store = ContentAddressedArtifactStore(linked_root)

    with pytest.raises(UpdateFailure):
        store.stage_path("operation-1")

    assert list(real_root.iterdir()) == []


@pytest.mark.parametrize("root", [Path("/"), Path.home()])
def test_broad_store_roots_are_refused(root: Path) -> None:
    store = ContentAddressedArtifactStore(root)

    with pytest.raises(UpdateFailure):
        store.stage_path("operation-1")
