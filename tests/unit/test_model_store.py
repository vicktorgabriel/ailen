"""Unit tests for ModelStore storage management and path security."""

import hashlib
from tempfile import TemporaryDirectory

import pytest

from ailen.models.store import ModelStore


def test_model_store_lifecycle_and_path_security() -> None:
    with TemporaryDirectory() as tmpdir:
        store = ModelStore(base_dir=tmpdir)
        store.ensure_directory()

        # 1. Path resolution
        path = store.get_model_path("test-model-0.5b")
        assert path.name == "test-model-0.5b.gguf"
        assert not store.exists("test-model-0.5b")
        assert store.get_size("test-model-0.5b") == 0

        # 2. Path traversal security checks
        with pytest.raises(ValueError, match="Invalid model_id containing path separators"):
            store.get_model_path("../secret")

        with pytest.raises(ValueError, match="Invalid model_id containing path separators"):
            store.get_model_path("sub/dir/model")

        with pytest.raises(ValueError, match="Invalid model_id containing path separators"):
            store.get_model_path("model\x00evil")

        # 3. Create dummy artifact and verify SHA-256
        content = b"DUMMY_GGUF_MODEL_DATA_12345"
        expected_sha = hashlib.sha256(content).hexdigest()
        path.write_bytes(content)

        assert store.exists("test-model-0.5b") is True
        assert store.get_size("test-model-0.5b") == len(content)
        assert store.verify("test-model-0.5b", expected_sha) is True
        assert store.verify("test-model-0.5b", "0" * 64) is False

        # 4. List installed
        installed = store.list_installed()
        assert len(installed) == 1
        assert installed[0]["model_id"] == "test-model-0.5b"
        assert installed[0]["size_bytes"] == len(content)

        # 5. Remove
        removed = store.remove("test-model-0.5b")
        assert removed is True
        assert store.exists("test-model-0.5b") is False
