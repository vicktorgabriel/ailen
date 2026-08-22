"""Speech preparation workflow for Lab Mode (inspect, download, verify STT and TTS assets)."""

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from ailen.audio.piper_backend import resolve_piper_executable
from ailen.core.config import AILENConfig
from ailen.speech.catalog import SpeechAssetCatalog, SpeechAssetDescriptor
from ailen.speech.downloader import SpeechAssetDownloader
from ailen.speech.store import SpeechAssetStore

logger = logging.getLogger(__name__)


@dataclass
class SpeechComponentReport:
    """Report for STT or TTS component asset readiness."""
    engine: str
    target_asset: SpeechAssetDescriptor | None
    is_installed: bool
    is_verified: bool
    resolved_path: Path | None
    runtime_available: bool
    runtime_detail: str


@dataclass
class PrepareSpeechReport:
    """Overall speech preparation report."""
    stt: SpeechComponentReport
    tts: SpeechComponentReport
    config_sample_stt_path: str
    config_sample_tts_model_path: str
    config_sample_tts_config_path: str

    @property
    def is_ready_for_audio(self) -> bool:
        return (
            self.stt.is_installed
            and self.stt.is_verified
            and self.tts.is_installed
            and self.tts.is_verified
            and self.tts.runtime_available
        )


class LabSpeechPreparer:
    """Coordinates inspection, downloading, and configuration generation for speech assets."""

    def __init__(
        self,
        config: AILENConfig | None = None,
        store: SpeechAssetStore | None = None,
        catalog: SpeechAssetCatalog | None = None,
        downloader: SpeechAssetDownloader | None = None,
    ) -> None:
        self.config = config or AILENConfig()
        self.store = store or SpeechAssetStore()
        self.catalog = catalog or SpeechAssetCatalog()
        self.downloader = downloader or SpeechAssetDownloader(store=self.store, catalog=self.catalog)

    def get_default_stt_asset(self, engine: str = "vosk") -> SpeechAssetDescriptor | None:
        """Resolve standard verified STT model for engine."""
        if engine.lower() == "vosk":
            return self.catalog.get("vosk-model-small-es-0.42")
        if engine.lower() == "whisper_cpp":
            return self.catalog.get("whisper-ggml-tiny")
        return None

    def get_default_tts_asset(self, voice_key: str | None = None) -> SpeechAssetDescriptor | None:
        """Resolve standard verified Piper voice model."""
        if voice_key:
            return self.catalog.get(voice_key)
        # Default recommendation: Davefx (Spanish, Spain medium quality)
        return self.catalog.get("es_ES-davefx-medium")

    def inspect(
        self,
        stt_engine: str | None = None,
        voice_key: str | None = None,
    ) -> PrepareSpeechReport:
        """Inspect disk, store and binaries for STT and TTS readiness."""
        target_stt_engine = (stt_engine or self.config.speech.stt_engine or "vosk").lower()
        if target_stt_engine == "mock":
            target_stt_engine = "vosk"

        stt_desc = self.get_default_stt_asset(target_stt_engine)
        stt_installed = self.store.exists(stt_desc) if stt_desc else False
        stt_verified = self.store.verify(stt_desc) if (stt_desc and stt_installed) else False
        stt_path = self.store.get_asset_path(stt_desc) if stt_desc else None

        # STT Runtime availability
        stt_runtime_ok = True
        stt_runtime_detail = "Ready"
        if target_stt_engine == "vosk":
            import importlib.util
            if importlib.util.find_spec("vosk") is None:
                stt_runtime_ok = False
                stt_runtime_detail = "vosk package missing (run: pip install -e '.[stt-vosk]')"
        elif target_stt_engine == "whisper_cpp":
            if not shutil.which("whisper-cli") and not shutil.which("main"):
                stt_runtime_ok = False
                stt_runtime_detail = "whisper-cli binary missing from PATH"

        stt_rep = SpeechComponentReport(
            engine=target_stt_engine,
            target_asset=stt_desc,
            is_installed=stt_installed,
            is_verified=stt_verified,
            resolved_path=stt_path,
            runtime_available=stt_runtime_ok,
            runtime_detail=stt_runtime_detail,
        )

        # TTS inspection
        tts_desc = self.get_default_tts_asset(voice_key)
        tts_installed = self.store.exists(tts_desc) if tts_desc else False
        tts_verified = self.store.verify(tts_desc) if (tts_desc and tts_installed) else False
        tts_path = self.store.get_asset_path(tts_desc) if tts_desc else None

        piper_bin = resolve_piper_executable("piper")
        tts_runtime_ok = bool(piper_bin)
        tts_runtime_detail = f"Found '{piper_bin}'" if piper_bin else "piper binary missing from PATH"

        tts_rep = SpeechComponentReport(
            engine="piper",
            target_asset=tts_desc,
            is_installed=tts_installed,
            is_verified=tts_verified,
            resolved_path=tts_path,
            runtime_available=tts_runtime_ok,
            runtime_detail=tts_runtime_detail,
        )

        # Generate sample config paths
        sample_stt_str = str(stt_path) if stt_path else ""
        sample_tts_model_str = str(tts_path) if tts_path else ""
        sample_tts_config_str = ""
        if tts_desc and tts_desc.associated_config_id:
            cfg_desc = self.catalog.get(tts_desc.associated_config_id)
            if cfg_desc:
                sample_tts_config_str = str(self.store.get_asset_path(cfg_desc))

        return PrepareSpeechReport(
            stt=stt_rep,
            tts=tts_rep,
            config_sample_stt_path=sample_stt_str,
            config_sample_tts_model_path=sample_tts_model_str,
            config_sample_tts_config_path=sample_tts_config_str,
        )

    def run_prepare(
        self,
        auto_download: bool = False,
        stt_engine: str | None = None,
        voice_key: str | None = None,
    ) -> tuple[PrepareSpeechReport, int]:
        """Interactive/CLI preparation routine."""
        report = self.inspect(stt_engine=stt_engine, voice_key=voice_key)

        print("\n============================================================")
        print("AILEN — LAB SPEECH ASSETS PREPARATION")
        print("============================================================\n")

        print("1. Speech-to-Text (STT):")
        print(f"   Engine: {report.stt.engine}")
        if report.stt.target_asset:
            print(f"   Recommended Model: {report.stt.target_asset.asset_id} ({report.stt.target_asset.expected_size_bytes / (1024*1024):.1f} MB)")
            print(f"   Installed: {'YES' if report.stt.is_installed else 'NO'}")
            print(f"   Verified SHA-256: {'YES' if report.stt.is_verified else 'NO'}")
            print(f"   Target Path: {report.stt.resolved_path}")
        print(f"   Runtime Status: {report.stt.runtime_detail}")

        print("\n2. Text-to-Speech (TTS):")
        print("   Engine: piper")
        if report.tts.target_asset:
            print(f"   Recommended Voice: {report.tts.target_asset.asset_id} ({report.tts.target_asset.voice_gender.value})")
            print(f"   Installed: {'YES' if report.tts.is_installed else 'NO'}")
            print(f"   Verified SHA-256: {'YES' if report.tts.is_verified else 'NO'}")
            print(f"   Target Path: {report.tts.resolved_path}")
        print(f"   Runtime Status: {report.tts.runtime_detail}")

        if not auto_download:
            needs_dl = (not report.stt.is_installed or not report.stt.is_verified) or (not report.tts.is_installed or not report.tts.is_verified)
            if needs_dl:
                print("\n[!] Assets missing or unverified. Run with '--yes' to download approved models.")
            else:
                print("\n[OK] All speech assets are downloaded and verified.")
            return report, 0

        # Auto download branch
        print("\n--> Downloading approved speech assets...")
        try:
            if report.stt.target_asset and (not report.stt.is_installed or not report.stt.is_verified):
                print(f"Downloading STT asset: {report.stt.target_asset.asset_id}...")
                self.downloader.download(report.stt.target_asset)
                print("STT download complete.")

            if report.tts.target_asset and (not report.tts.is_installed or not report.tts.is_verified):
                print(f"Downloading TTS voice asset: {report.tts.target_asset.asset_id}...")
                self.downloader.download(report.tts.target_asset, download_associated=True)
                print("TTS voice download complete.")

            # Re-inspect
            updated_report = self.inspect(stt_engine=stt_engine, voice_key=voice_key)
            print("\n[OK] Speech preparation finished successfully.")
            return updated_report, 0

        except Exception as exc:  # noqa: BLE001
            print(f"\n[ERROR] Speech download failed: {exc}")
            return report, 1
