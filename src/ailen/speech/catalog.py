"""Declarative and immutable catalog for verified offline speech assets (STT and TTS).

Manages metadata for STT models (Vosk, Whisper.cpp) and TTS voices/configs (Piper).
Gender metadata is explicit and never inferred by name.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class SpeechAssetType(str, Enum):
    """Categorization of speech assets."""
    STT_MODEL = "stt_model"
    TTS_MODEL = "tts_model"
    TTS_CONFIG = "tts_config"


class SpeechGender(str, Enum):
    """Declared voice gender metadata. Never guessed from names."""
    MALE = "male"
    FEMALE = "female"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SpeechAssetDescriptor:
    """Metadata descriptor for a verified speech artifact."""
    asset_id: str
    engine: str  # "vosk", "whisper_cpp", "piper"
    asset_type: SpeechAssetType
    language: str  # "es", "multilingual"
    locale: str  # "es_ES", "es_AR", "es_MX", "global"
    quality: str  # "small", "tiny", "base", "medium", "high", "x_low"
    source_url: str
    expected_size_bytes: int
    sha256: str
    license: str
    verified_at: str  # ISO date
    source_reference: str
    downloadable: bool = True
    voice_name: str | None = None
    voice_gender: SpeechGender = SpeechGender.UNKNOWN
    associated_config_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "engine": self.engine,
            "asset_type": self.asset_type.value,
            "language": self.language,
            "locale": self.locale,
            "quality": self.quality,
            "source_url": self.source_url,
            "expected_size_bytes": self.expected_size_bytes,
            "sha256": self.sha256,
            "license": self.license,
            "verified_at": self.verified_at,
            "source_reference": self.source_reference,
            "downloadable": self.downloadable,
            "voice_name": self.voice_name,
            "voice_gender": self.voice_gender.value,
            "associated_config_id": self.associated_config_id,
        }


# Canonical verified speech assets catalog for 2026
_VERIFIED_SPEECH_ASSETS: list[SpeechAssetDescriptor] = [
    # -------------------------------------------------------------------------
    # STT: Vosk Spanish
    # -------------------------------------------------------------------------
    SpeechAssetDescriptor(
        asset_id="vosk-model-small-es-0.42",
        engine="vosk",
        asset_type=SpeechAssetType.STT_MODEL,
        language="es",
        locale="es_ES",
        quality="small",
        source_url="https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip",
        expected_size_bytes=39_817_833,
        sha256="09b239888f633ef2f0b4e09736e3d9936acfd810bc65d53fad45261762c6511f",
        license="Apache-2.0",
        verified_at="2026-08-21",
        source_reference="alphacephei.com/vosk/models",
        downloadable=True,
    ),
    # -------------------------------------------------------------------------
    # STT: Whisper.cpp
    # -------------------------------------------------------------------------
    SpeechAssetDescriptor(
        asset_id="whisper-ggml-tiny",
        engine="whisper_cpp",
        asset_type=SpeechAssetType.STT_MODEL,
        language="multilingual",
        locale="global",
        quality="tiny",
        source_url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin",
        expected_size_bytes=77_691_713,
        sha256="be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21",
        license="MIT",
        verified_at="2026-08-21",
        source_reference="huggingface.co/ggerganov/whisper.cpp",
        downloadable=True,
    ),
    SpeechAssetDescriptor(
        asset_id="whisper-ggml-base",
        engine="whisper_cpp",
        asset_type=SpeechAssetType.STT_MODEL,
        language="multilingual",
        locale="global",
        quality="base",
        source_url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
        expected_size_bytes=147_951_465,
        sha256="60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe",
        license="MIT",
        verified_at="2026-08-21",
        source_reference="huggingface.co/ggerganov/whisper.cpp",
        downloadable=True,
    ),
    # -------------------------------------------------------------------------
    # TTS: Piper Spanish (Davefx - Spain; gender not declared by model card)
    # -------------------------------------------------------------------------
    SpeechAssetDescriptor(
        asset_id="es_ES-davefx-medium",
        engine="piper",
        asset_type=SpeechAssetType.TTS_MODEL,
        language="es",
        locale="es_ES",
        quality="medium",
        source_url="https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx",
        expected_size_bytes=63_201_294,
        sha256="6658b03b1a6c316ee4c265a9896abc1393353c2d9e1bca7d66c2c442e222a917",
        license="CC0-1.0",
        verified_at="2026-08-21",
        source_reference="huggingface.co/rhasspy/piper-voices (davefx dataset)",
        downloadable=True,
        voice_name="davefx",
        voice_gender=SpeechGender.UNKNOWN,
        associated_config_id="es_ES-davefx-medium.json",
    ),
    SpeechAssetDescriptor(
        asset_id="es_ES-davefx-medium.json",
        engine="piper",
        asset_type=SpeechAssetType.TTS_CONFIG,
        language="es",
        locale="es_ES",
        quality="medium",
        source_url="https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx.json",
        expected_size_bytes=4_817,
        sha256="0e0dda87c732f6f38771ff274a6380d9252f327dca77aa2963d5fbdf9ec54842",
        license="CC0-1.0",
        verified_at="2026-08-21",
        source_reference="huggingface.co/rhasspy/piper-voices (davefx json)",
        downloadable=True,
        voice_name="davefx",
        voice_gender=SpeechGender.UNKNOWN,
    ),
    # -------------------------------------------------------------------------
    # TTS: Piper Spanish (Daniela - Argentina; gender not declared by model card)
    # -------------------------------------------------------------------------
    SpeechAssetDescriptor(
        asset_id="es_AR-daniela-high",
        engine="piper",
        asset_type=SpeechAssetType.TTS_MODEL,
        language="es",
        locale="es_AR",
        quality="high",
        source_url="https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_AR/daniela/high/es_AR-daniela-high.onnx",
        expected_size_bytes=114_199_011,
        sha256="7ceb1fc0dab349418c5b54a639ae9ee595212d7c9ea422220d8419163d5cc985",
        license="CC-BY-SA-4.0",
        verified_at="2026-08-21",
        source_reference="huggingface.co/rhasspy/piper-voices (OpenSLR 61)",
        downloadable=True,
        voice_name="daniela",
        voice_gender=SpeechGender.UNKNOWN,
        associated_config_id="es_AR-daniela-high.json",
    ),
    SpeechAssetDescriptor(
        asset_id="es_AR-daniela-high.json",
        engine="piper",
        asset_type=SpeechAssetType.TTS_CONFIG,
        language="es",
        locale="es_AR",
        quality="high",
        source_url="https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_AR/daniela/high/es_AR-daniela-high.onnx.json",
        expected_size_bytes=7_248,
        sha256="aedbf69647e1d754c62ecf8e0366ca5f16af3e768e3c6b5329af6eb6bde3852b",
        license="CC-BY-SA-4.0",
        verified_at="2026-08-21",
        source_reference="huggingface.co/rhasspy/piper-voices (daniela json)",
        downloadable=True,
        voice_name="daniela",
        voice_gender=SpeechGender.UNKNOWN,
    ),
    # -------------------------------------------------------------------------
    # TTS: Piper Spanish (Multi-speaker / Sharvard - Spain)
    # -------------------------------------------------------------------------
    SpeechAssetDescriptor(
        asset_id="es_ES-sharvard-medium",
        engine="piper",
        asset_type=SpeechAssetType.TTS_MODEL,
        language="es",
        locale="es_ES",
        quality="medium",
        source_url="https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/sharvard/medium/es_ES-sharvard-medium.onnx",
        expected_size_bytes=76_733_615,
        sha256="40febfb1679c69a4505ff311dc136e121e3419a13a290ef264fdf43ddedd0fb1",
        license="CC-BY-3.0",
        verified_at="2026-08-21",
        source_reference="huggingface.co/rhasspy/piper-voices (Spanish Harvard)",
        downloadable=True,
        voice_name="sharvard",
        voice_gender=SpeechGender.UNKNOWN,  # Multi-speaker dataset (M: 0, F: 1)
        associated_config_id="es_ES-sharvard-medium.json",
    ),
    SpeechAssetDescriptor(
        asset_id="es_ES-sharvard-medium.json",
        engine="piper",
        asset_type=SpeechAssetType.TTS_CONFIG,
        language="es",
        locale="es_ES",
        quality="medium",
        source_url="https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/sharvard/medium/es_ES-sharvard-medium.onnx.json",
        expected_size_bytes=4_903,
        sha256="7438c9b699c72b0c3388dae1b68d3f364dc66a2150fe554a1c11f03372957b2c",
        license="CC-BY-3.0",
        verified_at="2026-08-21",
        source_reference="huggingface.co/rhasspy/piper-voices (sharvard json)",
        downloadable=True,
        voice_name="sharvard",
        voice_gender=SpeechGender.UNKNOWN,
    ),
    # -------------------------------------------------------------------------
    # TTS: Piper Spanish (Carlfm - Spain x_low; gender not declared by model card)
    # -------------------------------------------------------------------------
    SpeechAssetDescriptor(
        asset_id="es_ES-carlfm-x_low",
        engine="piper",
        asset_type=SpeechAssetType.TTS_MODEL,
        language="es",
        locale="es_ES",
        quality="x_low",
        source_url="https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/carlfm/x_low/es_ES-carlfm-x_low.onnx",
        expected_size_bytes=28_130_791,
        sha256="d69677323a907cd4963f42b29c20a98b5d6bfa7f3e64df339915e4650c00d125",
        license="Public-Domain",
        verified_at="2026-08-21",
        source_reference="huggingface.co/rhasspy/piper-voices (carlfm MODEL_CARD)",
        downloadable=True,
        voice_name="carlfm",
        voice_gender=SpeechGender.UNKNOWN,
        associated_config_id="es_ES-carlfm-x_low.json",
    ),
    SpeechAssetDescriptor(
        asset_id="es_ES-carlfm-x_low.json",
        engine="piper",
        asset_type=SpeechAssetType.TTS_CONFIG,
        language="es",
        locale="es_ES",
        quality="x_low",
        source_url="https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/carlfm/x_low/es_ES-carlfm-x_low.onnx.json",
        expected_size_bytes=4_159,
        sha256="d9bdfa9ff01eb2bc9e62e7d2593939d1e4c4d8eb7cf75f972731539d12399966",
        license="Public-Domain",
        verified_at="2026-08-21",
        source_reference="huggingface.co/rhasspy/piper-voices (carlfm MODEL_CARD/json)",
        downloadable=True,
        voice_name="carlfm",
        voice_gender=SpeechGender.UNKNOWN,
    ),
]


class SpeechAssetCatalog:
    """Access layer for verified STT and TTS speech asset descriptors."""

    def __init__(self, assets: list[SpeechAssetDescriptor] | None = None) -> None:
        source_assets = list(assets) if assets is not None else list(_VERIFIED_SPEECH_ASSETS)
        asset_ids = [asset.asset_id for asset in source_assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("Duplicate speech asset_id detected in catalog")
        self._assets = {asset.asset_id: asset for asset in source_assets}
        self._validate_catalog()

    def _validate_catalog(self) -> None:
        for asset_id, desc in self._assets.items():
            if not re.fullmatch(r"[a-zA-Z0-9_.-]+", asset_id):
                raise ValueError(f"Invalid asset_id in catalog: {asset_id!r}")
            if not desc.source_url.startswith("https://"):
                raise ValueError(f"Speech asset must use HTTPS: {asset_id}")
            if len(desc.sha256) != 64 or not re.fullmatch(r"[0-9a-fA-F]{64}", desc.sha256):
                raise ValueError(f"Invalid SHA-256 for asset '{asset_id}': {desc.sha256}")
            if desc.expected_size_bytes <= 0:
                raise ValueError(f"Invalid size for asset '{asset_id}': {desc.expected_size_bytes}")
            if not desc.license.strip() or not desc.source_reference.strip() or not desc.verified_at.strip():
                raise ValueError(f"Incomplete provenance metadata for speech asset '{asset_id}'")
            if desc.associated_config_id:
                config_desc = self._assets.get(desc.associated_config_id)
                if config_desc is None or config_desc.asset_type != SpeechAssetType.TTS_CONFIG:
                    raise ValueError(
                        f"Invalid associated_config_id for '{asset_id}': {desc.associated_config_id}"
                    )

    def get(self, asset_id: str) -> SpeechAssetDescriptor | None:
        """Lookup speech asset by unique asset_id."""
        return self._assets.get(asset_id)

    def list_assets(
        self,
        engine: str | None = None,
        asset_type: SpeechAssetType | None = None,
        language: str | None = None,
        downloadable_only: bool = True,
    ) -> list[SpeechAssetDescriptor]:
        """Filter speech assets."""
        results: list[SpeechAssetDescriptor] = []
        for desc in self._assets.values():
            if downloadable_only and not desc.downloadable:
                continue
            if engine and desc.engine.lower() != engine.lower():
                continue
            if asset_type and desc.asset_type != asset_type:
                continue
            if language and desc.language.lower() != language.lower() and desc.language != "multilingual":
                continue
            results.append(desc)
        return results

    def list_voices(self, language: str = "es") -> list[SpeechAssetDescriptor]:
        """Return list of voice models (excluding separate json configs)."""
        return [
            a for a in self.list_assets(engine="piper", asset_type=SpeechAssetType.TTS_MODEL, language=language)
        ]
