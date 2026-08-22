"""Unit tests for LabAiPreparer inspection, dry-run, and model preparation."""

from unittest.mock import MagicMock, patch

from ailen.core.config import AILENConfig
from ailen.models.catalog import ModelDescriptor, ModelPurpose
from ailen.models.planner import ModelPlan
from ailen.runtime.prepare import LabAiPreparer


def test_prepare_ai_dry_run_inspection() -> None:
    cfg = AILENConfig()
    preparer = LabAiPreparer(config=cfg)

    report, code = preparer.run(auto_download=False, start_runtime=False, purpose=ModelPurpose.BALANCED)
    assert code == 0
    assert report.hardware is not None
    assert report.plan is not None
    assert isinstance(report.runtimes, list)


def test_prepare_ai_auto_download_mock(tmp_path) -> None:
    cfg = AILENConfig()
    mock_store = MagicMock()
    mock_store.base_dir = tmp_path
    mock_store.exists.return_value = False
    mock_store.get_model_path.return_value = tmp_path / "model.gguf"

    preparer = LabAiPreparer(config=cfg, store=mock_store)

    fake_desc = ModelDescriptor(
        model_id="qwen3.5-0.8b-q4_0",
        display_name="Qwen 3.5 0.8B (Q4_0)",
        family="qwen",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_0",
        parameter_class="tiny",
        context_default=2048,
        ram_requirement_mb=900,
        vram_requirement_mb=1100,
        disk_size_bytes=563_036_064,
        source_url="https://example.com/model.gguf",
        sha256="57d1997790d1744fba5b40a7317df71ea5e2acee28c47e78f0cce39c0703f8cf",
        downloadable=True,
        source_reference="test",
    )

    from ailen.hardware.contracts import CpuInfo, HardwareCapabilityReport, OsFamily, RamInfo

    fake_hw = HardwareCapabilityReport(
        timestamp_utc="2026-08-21T00:00:00Z",
        os_name="linux",
        os_version="6.8.0",
        os_distribution="Linux Mint",
        os_family=OsFamily.LINUX,
        cpu=CpuInfo(model="x86", architecture="x86_64", physical_cores=4, logical_cores=8),
        ram=RamInfo(total_bytes=16_000_000_000, available_bytes=12_000_000_000),
    )

    with patch("ailen.hardware.detector.HardwareDetector.detect", return_value=fake_hw), \
         patch("ailen.models.planner.ModelPlanner.plan", return_value=ModelPlan(
             selected_model_id="qwen3.5-0.8b-q4_0",
             is_viable=True,
             model_descriptor=fake_desc,
         )), \
         patch("ailen.models.downloader.ModelDownloader.download", return_value=tmp_path / "model.gguf"):

        report, code = preparer.run(auto_download=True, start_runtime=False)
        assert code == 0
        assert report.model_installed is True
