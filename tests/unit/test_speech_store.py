"""Unit tests for SpeechAssetStore."""

import hashlib
from tempfile import TemporaryDirectory

import pytest

from ailen.speech.catalog import SpeechAssetCatalog, SpeechAssetDescriptor, SpeechAssetType
from ailen.speech.store import SpeechAssetStore


def test_speech_store_paths_and_traversal_protection() -> None:
    with TemporaryDirectory() as tmpdir:
        store = SpeechAssetStore(base_dir=tmpdir)
        store.ensure_directories()

        assert store.stt_dir.is_dir()
        assert store.tts_dir.is_dir()

        catalog = SpeechAssetCatalog()
        vosk_desc = catalog.get("vosk-model-small-es-0.42")
        assert vosk_desc is not None
        vosk_path = store.get_asset_path(vosk_desc)
        assert vosk_path.parent == store.stt_dir

        piper_desc = catalog.get("es_ES-davefx-medium")
        assert piper_desc is not None
        piper_path = store.get_asset_path(piper_desc)
        assert piper_path.parent == store.tts_dir
        assert piper_path.name == "es_ES-davefx-medium.onnx"

        # Traversal protection
        malicious = SpeechAssetDescriptor(
            asset_id="../../etc/passwd",
            engine="piper",
            asset_type=SpeechAssetType.TTS_MODEL,
            language="es",
            locale="es_ES",
            quality="medium",
            source_url="https://example.com/model.onnx",
            expected_size_bytes=1000,
            sha256="a" * 64,
            license="MIT",
            verified_at="2026-08-21",
            source_reference="test",
        )
        with pytest.raises(ValueError, match="Invalid asset_id"):
            store.get_asset_path(malicious)


def test_speech_store_verify_hash() -> None:
    with TemporaryDirectory() as tmpdir:
        store = SpeechAssetStore(base_dir=tmpdir)
        store.ensure_directories()

        content = b"fake voice onnx model payload data"
        sha = hashlib.sha256(content).hexdigest()

        desc = SpeechAssetDescriptor(
            asset_id="test-voice",
            engine="piper",
            asset_type=SpeechAssetType.TTS_MODEL,
            language="es",
            locale="es_ES",
            quality="medium",
            source_url="https://example.com/test.onnx",
            expected_size_bytes=len(content),
            sha256=sha,
            license="MIT",
            verified_at="2026-08-21",
            source_reference="test",
        )

        assert not store.exists(desc)
        target = store.get_asset_path(desc)
        target.write_bytes(content)

        assert store.exists(desc)
        assert store.verify(desc) is True

        # Corrupt file
        target.write_bytes(b"corrupted data")
        assert store.verify(desc) is False


def test_vosk_verification_requires_authoritative_archive() -> None:
    with TemporaryDirectory() as tmpdir:
        store = SpeechAssetStore(base_dir=tmpdir)
        store.ensure_directories()
        desc = SpeechAssetCatalog().get("vosk-model-small-es-0.42")
        assert desc is not None
        model_dir = store.get_asset_path(desc)
        model_dir.mkdir(parents=True)
        (model_dir / "dummy.conf").write_text("present", encoding="utf-8")

        assert store.exists(desc) is True
        assert store.verify(desc) is False
