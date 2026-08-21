"""Unit tests for HardwareDetector and ProfileRecommendation."""

from ailen.domain.enums import DeviceProfile
from ailen.hardware.detector import HardwareDetector
from ailen.hardware.fake import FakeHardwareAdapter


def test_detector_with_lab_pc_preset() -> None:
    adapter = FakeHardwareAdapter.create_lab_pc_preset()
    detector = HardwareDetector(adapter=adapter)
    report = detector.detect()

    assert report.cpu.model == "AMD Ryzen 5 5500"
    assert report.ram.total_gb == 48.0
    assert len(report.gpus) == 1
    assert report.gpus[0].vendor == "nvidia"
    assert report.gpus[0].vram_total_mb == 12288

    rec = detector.recommend_profile(report)
    assert rec.profile == DeviceProfile.LOCAL
    assert rec.local_inference_capable is True
    assert rec.gpu_inference_capable is True
    assert "LAN_BRAIN_CAPABLE" in rec.reason_codes
    assert "LOCAL_MEDIUM_MODEL_CAPABLE" in rec.reason_codes


def test_detector_with_bangho_preset() -> None:
    adapter = FakeHardwareAdapter.create_bangho_preset()
    detector = HardwareDetector(adapter=adapter)
    report = detector.detect()

    rec = detector.recommend_profile(report)
    assert rec.profile == DeviceProfile.HYBRID
    assert rec.local_inference_capable is True
    assert rec.gpu_inference_capable is False
    assert "LOCAL_SMALL_MODEL_CAPABLE" in rec.reason_codes


def test_detector_with_sf20ba_preset_no_avx2() -> None:
    adapter = FakeHardwareAdapter.create_sf20ba_preset()
    detector = HardwareDetector(adapter=adapter)
    report = detector.detect()

    rec = detector.recommend_profile(report)
    # 4GB without AVX2 falls back to Cloud profile with no local inference
    assert rec.profile == DeviceProfile.CLOUD
    assert rec.local_inference_capable is False
    assert "CPU_NO_AVX2" in rec.reason_codes
    assert "NO_LOCAL_INFERENCE" in rec.reason_codes


def test_detector_with_satellite_preset() -> None:
    adapter = FakeHardwareAdapter.create_satellite_preset()
    detector = HardwareDetector(adapter=adapter)
    report = detector.detect()

    rec = detector.recommend_profile(report)
    assert rec.profile == DeviceProfile.SATELLITE
    assert rec.local_inference_capable is False
    assert "RAM_LIMITED_SATELLITE" in rec.reason_codes


def test_detector_with_unknown_ram_probe() -> None:
    from ailen.hardware.contracts import RamInfo

    adapter = FakeHardwareAdapter(ram=RamInfo(total_bytes=0, available_bytes=0))
    detector = HardwareDetector(adapter=adapter)
    report = detector.detect()

    rec = detector.recommend_profile(report)
    assert rec.profile == DeviceProfile.CLOUD
    assert rec.local_inference_capable is False
    assert "HARDWARE_RAM_UNKNOWN" in rec.reason_codes
    assert "LOCAL_PLAN_BLOCKED_INSUFFICIENT_EVIDENCE" in rec.reason_codes
