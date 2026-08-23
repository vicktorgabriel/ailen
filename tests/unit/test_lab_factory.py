"""Unit tests for LabComponentFactory verifying real, missing, and simulated resolution."""

from ailen.core.config import AILENConfig
from ailen.hardware.contracts import (
    CameraDeviceReport,
    CpuInfo,
    HardwareCapabilityReport,
    OsFamily,
    RamInfo,
)
from ailen.runtime.factory import LabComponentFactory


def test_factory_face_headless() -> None:
    cfg = AILENConfig()
    report = HardwareCapabilityReport(
        timestamp_utc="2026-08-21T00:00:00Z",
        os_name="linux",
        os_version="6.8.0",
        os_distribution="Linux Mint",
        os_family=OsFamily.LINUX,
        cpu=CpuInfo(model="x86", architecture="x86_64", physical_cores=4, logical_cores=8),
        ram=RamInfo(total_bytes=16_000_000_000, available_bytes=12_000_000_000),
    )
    factory = LabComponentFactory(config=cfg, hardware_report=report)
    _face, status = factory.build_face(headless=True)
    assert status.state == "READY"
    assert "Headless" in status.detail


def test_factory_face_simulated() -> None:
    cfg = AILENConfig()
    factory = LabComponentFactory(config=cfg)
    _face, status = factory.build_face(simulate=True)
    assert status.state == "SIMULATED"
    assert "Simulated" in status.detail


def test_factory_vision_disabled() -> None:
    cfg = AILENConfig()
    factory = LabComponentFactory(config=cfg)
    vision, status = factory.build_vision(no_camera=True)
    assert vision is None
    assert status.state == "DISABLED"


def test_factory_vision_no_cameras_detected() -> None:
    cfg = AILENConfig()
    report = HardwareCapabilityReport(
        timestamp_utc="2026-08-21T00:00:00Z",
        os_name="linux",
        os_version="6.8.0",
        os_distribution="Linux Mint",
        os_family=OsFamily.LINUX,
        cpu=CpuInfo(model="x86", architecture="x86_64", physical_cores=4, logical_cores=8),
        ram=RamInfo(total_bytes=16_000_000_000, available_bytes=12_000_000_000),
        cameras=[],
    )
    factory = LabComponentFactory(config=cfg, hardware_report=report)
    vision, status = factory.build_vision(no_camera=False, simulate=False)
    assert vision is None
    assert status.state in ("DISABLED", "UNAVAILABLE")



def test_factory_vision_auto_selects_detected_camera_when_configured_missing() -> None:
    cfg = AILENConfig()
    cfg.vision.camera_device = "/dev/video0"
    report = HardwareCapabilityReport(
        timestamp_utc="2026-08-23T00:00:00Z",
        os_name="linux",
        os_version="6.8.0",
        os_distribution="Linux Mint",
        os_family=OsFamily.LINUX,
        cpu=CpuInfo(model="x86", architecture="x86_64", physical_cores=4, logical_cores=8),
        ram=RamInfo(total_bytes=16_000_000_000, available_bytes=12_000_000_000),
        cameras=[CameraDeviceReport(device_path="/dev/video1", index=1, name="HD Webcam")],
    )
    factory = LabComponentFactory(config=cfg, hardware_report=report)
    vision, status = factory.build_vision()
    assert vision is not None
    assert getattr(vision, "camera_device", None) == "/dev/video1"
    assert status.state == "READY"
    assert "auto-selected physical camera" in status.detail

def test_factory_vision_simulated() -> None:
    cfg = AILENConfig()
    factory = LabComponentFactory(config=cfg)
    vision, status = factory.build_vision(simulate=True)
    assert vision is not None
    assert status.state == "SIMULATED"


def test_factory_stt_missing_model_without_simulate() -> None:
    cfg = AILENConfig()
    cfg.speech.stt_engine = "vosk"
    cfg.speech.stt_model_path = "/nonexistent/vosk/path"

    factory = LabComponentFactory(config=cfg)
    stt, status = factory.build_stt(simulate=False)
    # Must NOT silently fallback to Fake as READY
    assert stt is None
    assert status.state in ("MISSING_MODEL", "UNAVAILABLE")
    assert status.state != "READY"


def test_factory_stt_simulated() -> None:
    cfg = AILENConfig()
    factory = LabComponentFactory(config=cfg)
    stt, status = factory.build_stt(simulate=True)
    assert stt is not None
    assert status.state == "SIMULATED"


def test_factory_tts_missing_model_without_simulate() -> None:
    cfg = AILENConfig()
    cfg.speech.tts_engine = "piper"
    cfg.speech.tts_model_path = "/nonexistent/model.onnx"

    factory = LabComponentFactory(config=cfg)
    tts, status = factory.build_tts(simulate=False)
    assert tts is None
    assert status.state in ("MISSING_MODEL", "UNAVAILABLE")
    assert status.state != "READY"


def test_factory_tts_simulated() -> None:
    cfg = AILENConfig()
    factory = LabComponentFactory(config=cfg)
    tts, status = factory.build_tts(simulate=True)
    assert tts is not None
    assert status.state == "SIMULATED"


def test_factory_ai_simulated() -> None:
    cfg = AILENConfig()
    factory = LabComponentFactory(config=cfg)
    backends, status = factory.build_ai_backends(simulate=True)
    assert "local" in backends
    assert status.state == "SIMULATED"


def test_factory_ai_no_runtimes_not_running() -> None:
    cfg = AILENConfig()
    factory = LabComponentFactory(config=cfg)
    backends, status = factory.build_ai_backends(simulate=False, runtime_descriptors=[])
    assert "local" not in backends
    assert status.state == "NOT_RUNNING"


def test_factory_ai_does_not_pick_arbitrary_ollama_model() -> None:
    from unittest.mock import patch

    from ailen.models.catalog import ModelCatalog
    from ailen.models.planner import ModelPlan
    from ailen.runtime.contracts import (
        ExternalRuntimeDescriptor,
        RuntimeHealth,
        RuntimeStatus,
        RuntimeType,
    )

    cfg = AILENConfig()
    desc = ModelCatalog().get_model("qwen3.5-0.8b-q8_0")
    assert desc is not None
    plan = ModelPlan(
        selected_model_id=desc.model_id,
        runtime="llama.cpp",
        device="cuda",
        gpu_layers="all",
        is_viable=True,
        model_descriptor=desc,
    )
    runtime = ExternalRuntimeDescriptor(
        runtime_type=RuntimeType.OLLAMA,
        executable_path="/usr/bin/ollama",
        endpoint="http://127.0.0.1:11434/v1",
        is_detected=True,
        status=RuntimeStatus.HEALTHY,
        health=RuntimeHealth(
            status=RuntimeStatus.HEALTHY,
            endpoint="http://127.0.0.1:11434/v1",
            is_running=True,
        ),
    )
    factory = LabComponentFactory(config=cfg)
    with patch(
        "ailen.runtime.inventory.RuntimeModelInventory.list_models",
        return_value=["qwen3.5:9b", "unrelated:latest"],
    ):
        backends, status = factory.build_ai_backends(
            model_plan=plan, runtime_descriptors=[runtime]
        )
    assert "local" not in backends
    assert status.state == "MISSING_MODEL"


def test_factory_ai_uses_exact_configured_ollama_model() -> None:
    from unittest.mock import patch

    from ailen.runtime.contracts import (
        ExternalRuntimeDescriptor,
        RuntimeHealth,
        RuntimeStatus,
        RuntimeType,
    )

    cfg = AILENConfig()
    cfg.ai.local.enabled = True
    cfg.ai.local.model = "qwen3.5:9b"
    runtime = ExternalRuntimeDescriptor(
        runtime_type=RuntimeType.OLLAMA,
        executable_path="/usr/bin/ollama",
        endpoint="http://127.0.0.1:11434/v1",
        is_detected=True,
        status=RuntimeStatus.HEALTHY,
        health=RuntimeHealth(
            status=RuntimeStatus.HEALTHY,
            endpoint="http://127.0.0.1:11434/v1",
            is_running=True,
        ),
    )
    factory = LabComponentFactory(config=cfg)
    with patch(
        "ailen.runtime.inventory.RuntimeModelInventory.list_models",
        return_value=["qwen3.5:9b"],
    ):
        backends, status = factory.build_ai_backends(runtime_descriptors=[runtime])
    assert "local" in backends
    assert getattr(backends["local"], "model", None) == "qwen3.5:9b"
    assert status.state == "READY"
