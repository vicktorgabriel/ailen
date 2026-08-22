"""Unit tests for SpeechAssetCatalog."""

import pytest

from ailen.speech.catalog import (
    SpeechAssetCatalog,
    SpeechAssetDescriptor,
    SpeechAssetType,
    SpeechGender,
)


def test_speech_catalog_load_default() -> None:
    cat = SpeechAssetCatalog()
    assets = cat.list_assets()
    assert len(assets) >= 8

    # Verify Vosk STT model exists
    vosk_desc = cat.get("vosk-model-small-es-0.42")
    assert vosk_desc is not None
    assert vosk_desc.engine == "vosk"
    assert vosk_desc.asset_type == SpeechAssetType.STT_MODEL
    assert vosk_desc.expected_size_bytes == 39_817_833
    assert len(vosk_desc.sha256) == 64
    assert vosk_desc.license == "Apache-2.0"

    # Verify Whisper model exists
    whisper_desc = cat.get("whisper-ggml-tiny")
    assert whisper_desc is not None
    assert whisper_desc.engine == "whisper_cpp"
    assert whisper_desc.expected_size_bytes == 77_691_713
    assert len(whisper_desc.sha256) == 64

    # Verify Piper Spanish voices exist
    davefx = cat.get("es_ES-davefx-medium")
    assert davefx is not None
    assert davefx.engine == "piper"
    assert davefx.asset_type == SpeechAssetType.TTS_MODEL
    assert davefx.voice_gender == SpeechGender.UNKNOWN
    assert davefx.associated_config_id == "es_ES-davefx-medium.json"

    daniela = cat.get("es_AR-daniela-high")
    assert daniela is not None
    assert daniela.voice_gender == SpeechGender.UNKNOWN
    assert daniela.associated_config_id == "es_AR-daniela-high.json"

    sharvard = cat.get("es_ES-sharvard-medium")
    assert sharvard is not None
    assert sharvard.voice_gender == SpeechGender.UNKNOWN  # Multi-speaker dataset


def test_speech_catalog_filter_voices() -> None:
    cat = SpeechAssetCatalog()
    voices = cat.list_voices(language="es")
    assert len(voices) >= 4
    voice_ids = [v.asset_id for v in voices]
    assert "es_ES-davefx-medium" in voice_ids
    assert "es_AR-daniela-high" in voice_ids
    assert "es_ES-sharvard-medium" in voice_ids
    assert "es_ES-carlfm-x_low" in voice_ids


def test_speech_catalog_invalid_sha_fails_validation() -> None:
    invalid_desc = SpeechAssetDescriptor(
        asset_id="invalid-sha-asset",
        engine="vosk",
        asset_type=SpeechAssetType.STT_MODEL,
        language="es",
        locale="es_ES",
        quality="small",
        source_url="https://example.com/asset.zip",
        expected_size_bytes=1000,
        sha256="invalid_short_hash",
        license="MIT",
        verified_at="2026-08-21",
        source_reference="test",
    )
    with pytest.raises(ValueError, match="Invalid SHA-256"):
        SpeechAssetCatalog(assets=[invalid_desc])


def test_speech_catalog_duplicate_id_rejected() -> None:
    base = SpeechAssetDescriptor(
        asset_id="duplicate",
        engine="piper",
        asset_type=SpeechAssetType.TTS_MODEL,
        language="es",
        locale="es_ES",
        quality="test",
        source_url="https://example.com/a.onnx",
        expected_size_bytes=1,
        sha256="a" * 64,
        license="MIT",
        verified_at="2026-08-21",
        source_reference="test",
    )
    with pytest.raises(ValueError, match="Duplicate speech asset_id"):
        SpeechAssetCatalog(assets=[base, base])
