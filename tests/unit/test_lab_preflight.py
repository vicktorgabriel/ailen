"""Unit tests for LabPreflightChecker."""

from tempfile import TemporaryDirectory

from ailen.core.config import AILENConfig
from ailen.runtime.preflight import LabPreflightChecker
from ailen.speech.store import SpeechAssetStore


def test_lab_preflight_missing_assets_reports_not_ready() -> None:
    cfg = AILENConfig()
    cfg.speech.stt_engine = "mock"
    cfg.speech.tts_engine = "mock"

    with TemporaryDirectory() as tmpdir:
        store = SpeechAssetStore(base_dir=tmpdir)
        checker = LabPreflightChecker(config=cfg, speech_store=store)

        report = checker.run_all()
        assert report.overall_status == "NOT_READY_FOR_LIVE_TEST"
        assert len(report.missing_required) > 0

        # Check item names present
        names = [c.name for c in report.checks]
        assert "Face GUI" in names
        assert "Vision & Camera" in names or "Vision Library" in names or "Camera Hardware" in names
        assert "Audio Input" in names
        assert "Audio Output" in names
        assert "STT Engine" in names
        assert "TTS Engine" in names


def test_lab_preflight_skipped_flags() -> None:
    cfg = AILENConfig()
    with TemporaryDirectory() as tmpdir:
        store = SpeechAssetStore(base_dir=tmpdir)
        checker = LabPreflightChecker(config=cfg, speech_store=store)

        report = checker.run_all(headless=True, no_camera=True, no_audio=True, no_ai=True)
        states = {c.name: c.status for c in report.checks}
        assert states["Face GUI"] == "SKIP"
        assert states["Vision & Camera"] == "SKIP"
        assert states["Audio I/O"] == "SKIP"
        assert states["STT"] == "SKIP"
        assert states["TTS"] == "SKIP"
        assert states["Local AI"] == "SKIP"
