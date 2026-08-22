"""Unit tests for SpeechAssetDownloader."""

import hashlib
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import pytest

from ailen.speech.catalog import SpeechAssetDescriptor, SpeechAssetType
from ailen.speech.downloader import SpeechAssetDownloader, SpeechDownloadError
from ailen.speech.store import SpeechAssetStore


def test_speech_downloader_success() -> None:
    with TemporaryDirectory() as tmpdir:
        store = SpeechAssetStore(base_dir=tmpdir)
        downloader = SpeechAssetDownloader(store=store)

        payload = b"valid onnx voice model binary content"
        sha = hashlib.sha256(payload).hexdigest()

        desc = SpeechAssetDescriptor(
            asset_id="es_ES-mock-voice",
            engine="piper",
            asset_type=SpeechAssetType.TTS_MODEL,
            language="es",
            locale="es_ES",
            quality="medium",
            source_url="https://example.com/model.onnx",
            expected_size_bytes=len(payload),
            sha256=sha,
            license="MIT",
            verified_at="2026-08-21",
            source_reference="test",
        )

        mock_resp = MagicMock()
        mock_resp.url = "https://example.com/model.onnx"
        mock_resp.read.side_effect = [payload, b""]
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with patch("urllib.request.urlopen", return_value=mock_resp):
            out = downloader.download(desc, download_associated=False)
            assert out.is_file()
            assert out.read_bytes() == payload
            assert store.verify(desc) is True


def test_speech_downloader_sha_mismatch_fails_and_cleans_up() -> None:
    with TemporaryDirectory() as tmpdir:
        store = SpeechAssetStore(base_dir=tmpdir)
        downloader = SpeechAssetDownloader(store=store)

        payload = b"some unexpected payload"
        wrong_sha = "0" * 64

        desc = SpeechAssetDescriptor(
            asset_id="es_ES-corrupt-voice",
            engine="piper",
            asset_type=SpeechAssetType.TTS_MODEL,
            language="es",
            locale="es_ES",
            quality="medium",
            source_url="https://example.com/corrupt.onnx",
            expected_size_bytes=len(payload),
            sha256=wrong_sha,
            license="MIT",
            verified_at="2026-08-21",
            source_reference="test",
        )

        mock_resp = MagicMock()
        mock_resp.url = "https://example.com/corrupt.onnx"
        mock_resp.read.side_effect = [payload, b""]
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with (
            patch("urllib.request.urlopen", return_value=mock_resp),
            pytest.raises(SpeechDownloadError, match="Checksum mismatch"),
        ):
            downloader.download(desc, download_associated=False)

        assert not store.exists(desc)
        # Ensure no leftover .tmp files
        assert not list(store.tts_dir.glob("*.tmp"))


def test_speech_downloader_non_https_rejected() -> None:
    with TemporaryDirectory() as tmpdir:
        store = SpeechAssetStore(base_dir=tmpdir)
        downloader = SpeechAssetDownloader(store=store)

        desc = SpeechAssetDescriptor(
            asset_id="insecure-voice",
            engine="piper",
            asset_type=SpeechAssetType.TTS_MODEL,
            language="es",
            locale="es_ES",
            quality="medium",
            source_url="http://insecure.example.com/model.onnx",
            expected_size_bytes=100,
            sha256="a" * 64,
            license="MIT",
            verified_at="2026-08-21",
            source_reference="test",
        )

        with pytest.raises(SpeechDownloadError, match="must use HTTPS"):
            downloader.download(desc)


def test_speech_downloader_exact_size_mismatch_fails() -> None:
    with TemporaryDirectory() as tmpdir:
        store = SpeechAssetStore(base_dir=tmpdir)
        downloader = SpeechAssetDownloader(store=store)
        payload = b"short"
        desc = SpeechAssetDescriptor(
            asset_id="short-voice",
            engine="piper",
            asset_type=SpeechAssetType.TTS_MODEL,
            language="es",
            locale="es_ES",
            quality="test",
            source_url="https://example.com/short.onnx",
            expected_size_bytes=len(payload) + 1,
            sha256=hashlib.sha256(payload).hexdigest(),
            license="MIT",
            verified_at="2026-08-21",
            source_reference="test",
        )
        mock_resp = MagicMock()
        mock_resp.url = desc.source_url
        mock_resp.geturl.return_value = desc.source_url
        mock_resp.headers = {}
        mock_resp.read.side_effect = [payload, b""]
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with (
            patch("urllib.request.urlopen", return_value=mock_resp),
            pytest.raises(SpeechDownloadError, match="Size mismatch"),
        ):
            downloader.download(desc, download_associated=False)
        assert not store.exists(desc)


def test_speech_downloader_rejects_https_downgrade_redirect() -> None:
    with TemporaryDirectory() as tmpdir:
        store = SpeechAssetStore(base_dir=tmpdir)
        downloader = SpeechAssetDownloader(store=store)
        payload = b"payload"
        desc = SpeechAssetDescriptor(
            asset_id="redirect-voice",
            engine="piper",
            asset_type=SpeechAssetType.TTS_MODEL,
            language="es",
            locale="es_ES",
            quality="test",
            source_url="https://example.com/model.onnx",
            expected_size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            license="MIT",
            verified_at="2026-08-21",
            source_reference="test",
        )
        mock_resp = MagicMock()
        mock_resp.url = "http://cdn.example.com/model.onnx"
        mock_resp.geturl.return_value = mock_resp.url
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with (
            patch("urllib.request.urlopen", return_value=mock_resp),
            pytest.raises(SpeechDownloadError, match="Insecure redirect"),
        ):
            downloader.download(desc, download_associated=False)
