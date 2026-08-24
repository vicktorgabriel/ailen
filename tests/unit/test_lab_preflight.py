"""Unit tests for LabPreflightChecker."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

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


def _vision_library_item(checker: LabPreflightChecker):
    # Detector-readiness tests must not depend on whether a webcam happens to
    # be connected to the host running the unit suite.
    with patch("ailen.runtime.preflight.HardwareDetector.detect") as detect:
        detect.return_value.cameras = [object()]
        report = checker.run_all(no_camera=False, no_audio=True, no_ai=True)
    items = [c for c in report.checks if c.name in {"Vision Library", "Vision & Camera"}]
    assert len(items) == 1
    return items[0]


def test_preflight_yunet_missing_model_fails_closed() -> None:
    cfg = AILENConfig()
    cfg.vision.detector = "yunet"
    cfg.vision.detector_model_path = "/tmp/definitivamente-inexistente-yunet.onnx"

    with TemporaryDirectory() as tmpdir:
        store = SpeechAssetStore(base_dir=tmpdir)
        checker = LabPreflightChecker(config=cfg, speech_store=store)
        item = _vision_library_item(checker)

    assert item.status == "FAIL"
    assert "YuNet unavailable" in item.detail


def test_preflight_yunet_corrupt_model_fails_closed() -> None:
    import tempfile

    cfg = AILENConfig()
    cfg.speech.stt_engine = "mock"
    cfg.speech.tts_engine = "mock"
    with tempfile.TemporaryDirectory() as tmp:
        bogus = Path(tmp) / "bogus.onnx"
        bogus.write_bytes(b"not-an-onnx-model")
        cfg.vision.detector = "yunet"
        cfg.vision.detector_model_path = str(bogus)

        store = SpeechAssetStore(base_dir=tmp)
        checker = LabPreflightChecker(config=cfg, speech_store=store)
        item = _vision_library_item(checker)

    # A PASS must never come from the mere existence of the file.
    assert item.status == "FAIL"


def test_preflight_yunet_invalid_score_threshold_fails() -> None:
    cfg = AILENConfig()
    cfg.vision.detector = "yunet"
    cfg.vision.detector_score_threshold = 0.0

    with TemporaryDirectory() as tmpdir:
        store = SpeechAssetStore(base_dir=tmpdir)
        checker = LabPreflightChecker(config=cfg, speech_store=store)
        item = _vision_library_item(checker)

    assert item.status == "FAIL"
    assert "score_valid=False" in item.detail


def test_preflight_haar_loadable_passes_or_skips() -> None:
    try:
        import cv2  # noqa: F401
    except ImportError:
        pytest.skip("opencv not installed")

    cfg = AILENConfig()
    cfg.speech.stt_engine = "mock"
    cfg.speech.tts_engine = "mock"
    cfg.vision.detector = "haar"
    with TemporaryDirectory() as tmpdir:
        store = SpeechAssetStore(base_dir=tmpdir)
        checker = LabPreflightChecker(config=cfg, speech_store=store)
        item = _vision_library_item(checker)
    assert item.status == "PASS"
    assert "experimental" in item.detail


def test_preflight_yunet_with_real_lab_model_passes_when_available() -> None:
    model_path = Path("runtime/lab/vision_models/face_detection_yunet_2023mar.onnx")
    if not model_path.is_file():
        pytest.skip("LAB YuNet model not present on this host")

    cfg = AILENConfig()
    cfg.speech.stt_engine = "mock"
    cfg.speech.tts_engine = "mock"
    cfg.vision.detector = "yunet"
    cfg.vision.detector_model_path = str(model_path)
    cfg.vision.detector_score_threshold = 0.8

    with TemporaryDirectory() as tmpdir:
        store = SpeechAssetStore(base_dir=tmpdir)
        checker = LabPreflightChecker(config=cfg, speech_store=store)
        item = _vision_library_item(checker)

    assert item.status == "PASS"
    assert "YuNet ready" in item.detail
