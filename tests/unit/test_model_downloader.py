"""Unit tests for ModelDownloader streaming and SHA-256 fail-closed verification."""

import hashlib
import io
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import pytest

from ailen.models.catalog import ModelDescriptor
from ailen.models.downloader import ModelDownloader, ModelDownloadError
from ailen.models.store import ModelStore


def _create_mock_response(payload: bytes, final_url: str = "https://mock.local/model.gguf") -> MagicMock:
    resp = MagicMock()
    resp.geturl.return_value = final_url
    resp.headers = {"Content-Length": str(len(payload))}
    resp_stream = io.BytesIO(payload)
    resp.read.side_effect = resp_stream.read
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = None
    return resp


def test_model_downloader_success_and_sha_match() -> None:
    dummy_payload = b"GGUF_TEST_PAYLOAD_CHUNK_DATA_" * 1000
    expected_sha = hashlib.sha256(dummy_payload).hexdigest()

    mock_resp = _create_mock_response(dummy_payload)

    with patch("urllib.request.urlopen", return_value=mock_resp), TemporaryDirectory() as tmpdir:
        store = ModelStore(base_dir=tmpdir)
        downloader = ModelDownloader(store=store)

        descriptor = ModelDescriptor(
            model_id="test-download-model",
            display_name="Test Download Model",
            family="test",
            runtime="llama.cpp",
            artifact_format="gguf",
            quantization="q4_k_m",
            parameter_class="tiny",
            disk_size_bytes=len(dummy_payload),
            source_url="https://mock.local/model.gguf",
            sha256=expected_sha,
            downloadable=True,
            source_reference="test",
        )

        progress_calls = []

        def on_progress(done: int, total: int) -> None:
            progress_calls.append((done, total))

        target_path = downloader.download(descriptor, progress_callback=on_progress)
        assert target_path.is_file()
        assert target_path.stat().st_size == len(dummy_payload)
        assert store.verify("test-download-model", expected_sha) is True
        assert len(progress_calls) > 0


def test_model_downloader_fail_closed_on_sha_mismatch() -> None:
    dummy_payload = b"GGUF_CORRUPTED_DATA"
    wrong_sha = "f" * 64

    mock_resp = _create_mock_response(dummy_payload)

    with patch("urllib.request.urlopen", return_value=mock_resp), TemporaryDirectory() as tmpdir:
        store = ModelStore(base_dir=tmpdir)
        downloader = ModelDownloader(store=store)

        descriptor = ModelDescriptor(
            model_id="test-mismatch-model",
            display_name="Test Mismatch Model",
            family="test",
            runtime="llama.cpp",
            artifact_format="gguf",
            quantization="q4_k_m",
            parameter_class="tiny",
            disk_size_bytes=len(dummy_payload),
            source_url="https://mock.local/model.gguf",
            sha256=wrong_sha,
            downloadable=True,
            source_reference="test",
        )

        with pytest.raises(ModelDownloadError, match="Integrity check failed"):
            downloader.download(descriptor)

        # Assert target file was NOT created and temp files were deleted (fail-closed)
        assert not store.exists("test-mismatch-model")
        assert len(list(store.base_dir.glob("*.tmp*"))) == 0


def test_model_downloader_rejects_insecure_redirect_downgrade() -> None:
    dummy_payload = b"GGUF_DATA"
    expected_sha = hashlib.sha256(dummy_payload).hexdigest()

    # Response simulates redirect downgrade to http://insecure
    mock_resp = _create_mock_response(dummy_payload, final_url="http://insecure.local/model.gguf")

    with patch("urllib.request.urlopen", return_value=mock_resp), TemporaryDirectory() as tmpdir:
        store = ModelStore(base_dir=tmpdir)
        downloader = ModelDownloader(store=store)

        descriptor = ModelDescriptor(
            model_id="test-downgrade-model",
            display_name="Test Downgrade Model",
            family="test",
            runtime="llama.cpp",
            artifact_format="gguf",
            quantization="q4_k_m",
            parameter_class="tiny",
            disk_size_bytes=len(dummy_payload),
            source_url="https://mock.local/model.gguf",
            sha256=expected_sha,
            downloadable=True,
            source_reference="test",
        )

        with pytest.raises(ModelDownloadError, match="Redirected to insecure non-HTTPS URL"):
            downloader.download(descriptor)


def test_model_downloader_insufficient_disk_space() -> None:
    with TemporaryDirectory() as tmpdir:
        store = ModelStore(base_dir=tmpdir)
        downloader = ModelDownloader(store=store)

        # Huge model requiring 1000 Terabytes
        descriptor = ModelDescriptor(
            model_id="huge-model",
            display_name="Huge Model",
            family="huge",
            runtime="llama.cpp",
            artifact_format="gguf",
            quantization="q4_k_m",
            parameter_class="huge",
            disk_size_bytes=1000 * 1024 * 1024 * 1024 * 1024,
            source_url="https://mock.local/huge.gguf",
            sha256="0" * 64,
            downloadable=True,
            source_reference="test",
        )

        with pytest.raises(ModelDownloadError, match="Insufficient disk space"):
            downloader.download(descriptor)


def test_model_downloader_returns_existing_verified_artifact_without_network() -> None:
    payload = b"GGUF_EXISTING_VERIFIED"
    sha = hashlib.sha256(payload).hexdigest()

    with TemporaryDirectory() as tmpdir:
        store = ModelStore(base_dir=tmpdir)
        store.ensure_directory()
        target = store.get_model_path("existing-model")
        target.write_bytes(payload)
        downloader = ModelDownloader(store=store)
        descriptor = ModelDescriptor(
            model_id="existing-model",
            display_name="Existing Model",
            family="test",
            runtime="llama.cpp",
            artifact_format="gguf",
            quantization="q4_0",
            parameter_class="tiny",
            disk_size_bytes=len(payload),
            source_url="https://mock.local/model.gguf",
            sha256=sha,
            downloadable=True,
            source_reference="test",
        )

        with patch("urllib.request.urlopen") as mocked_urlopen:
            result = downloader.download(descriptor)

        assert result == target
        mocked_urlopen.assert_not_called()


def test_model_downloader_refuses_to_overwrite_existing_corrupt_artifact() -> None:
    payload = b"GGUF_EXPECTED"
    sha = hashlib.sha256(payload).hexdigest()

    with TemporaryDirectory() as tmpdir:
        store = ModelStore(base_dir=tmpdir)
        store.ensure_directory()
        target = store.get_model_path("existing-corrupt")
        target.write_bytes(b"CORRUPT")
        downloader = ModelDownloader(store=store)
        descriptor = ModelDescriptor(
            model_id="existing-corrupt",
            display_name="Existing Corrupt",
            family="test",
            runtime="llama.cpp",
            artifact_format="gguf",
            quantization="q4_0",
            parameter_class="tiny",
            disk_size_bytes=len(payload),
            source_url="https://mock.local/model.gguf",
            sha256=sha,
            downloadable=True,
            source_reference="test",
        )

        with patch("urllib.request.urlopen") as mocked_urlopen, pytest.raises(
            ModelDownloadError, match="failed checksum verification"
        ):
            downloader.download(descriptor)

        mocked_urlopen.assert_not_called()
        assert target.read_bytes() == b"CORRUPT"
