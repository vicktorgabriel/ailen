"""Unit tests for ModelPlanner and ModelPlan decisions."""

import pytest

from ailen.domain.enums import DeviceProfile, InferenceProfile
from ailen.hardware.detector import HardwareDetector
from ailen.hardware.fake import FakeHardwareAdapter
from ailen.models.catalog import (
    ModelCatalog,
    ModelDescriptor,
    ModelPurpose,
    ModelQualificationStatus,
)
from ailen.models.planner import ModelPlanner


def test_planner_selects_verified_gpu_sanity_model_on_lab_pc() -> None:
    adapter = FakeHardwareAdapter.create_lab_pc_preset()
    detector = HardwareDetector(adapter=adapter)
    report = detector.detect()

    planner = ModelPlanner()
    plan = planner.plan(report, profile=DeviceProfile.LOCAL, prefer_gpu=True)

    assert plan.is_viable is True
    assert plan.selected_model_id == "qwen3.5-0.8b-q8_0"
    assert plan.device == "cuda"
    assert plan.gpu_layers == "all"
    assert plan.estimated_vram_mb == 1400
    assert "OFFLOAD_ALL_LAYERS" in plan.reason_codes


def test_planner_selects_cpu_small_model_on_bangho() -> None:
    adapter = FakeHardwareAdapter.create_bangho_preset()
    detector = HardwareDetector(adapter=adapter)
    report = detector.detect()

    planner = ModelPlanner()
    plan = planner.plan(report, profile=DeviceProfile.HYBRID, prefer_gpu=True)

    assert plan.is_viable is True
    assert plan.selected_model_id == "qwen3.5-0.8b-q8_0"
    assert plan.device == "cpu"
    assert plan.gpu_layers == 0
    assert plan.estimated_ram_mb == 1200
    assert any("CPU_RAM_FIT" in r for r in plan.reason_codes)


def test_planner_produces_viable_tiny_model_on_sf20ba_without_avx2() -> None:
    adapter = FakeHardwareAdapter.create_sf20ba_preset()
    detector = HardwareDetector(adapter=adapter)
    report = detector.detect()

    planner = ModelPlanner()
    plan = planner.plan(report, profile=DeviceProfile.HYBRID)
    assert plan.is_viable is True
    # Qwen 3.5 0.8B (Q8_0 or Q4_0) or Qwen 2.5 0.5B (which don't require AVX2)
    assert plan.selected_model_id in ("qwen3.5-0.8b-q8_0", "qwen3.5-0.8b-q4_0", "qwen2.5-0.5b-instruct-q4_k_m")


def test_fast_profile_has_a_verified_downloadable_candidate() -> None:
    adapter = FakeHardwareAdapter.create_sf20ba_preset()
    report = HardwareDetector(adapter=adapter).detect()

    plan = ModelPlanner().plan(
        report,
        profile=DeviceProfile.HYBRID,
        inference_profile=InferenceProfile.FAST,
    )

    assert plan.is_viable is True
    assert plan.selected_model_id == "qwen3.5-0.8b-q4_0"
    assert plan.model_descriptor is not None
    assert plan.model_descriptor.downloadable is True


def test_8gb_planner_never_exceeds_canonical_model_memory_envelope() -> None:
    oversized = ModelDescriptor(
        model_id="synthetic-oversized-fast",
        display_name="Synthetic oversized fast model",
        family="test",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4",
        parameter_class="small",
        ram_requirement_mb=3100,
        vram_requirement_mb=3100,
        disk_size_bytes=100_000_000,
        suitability_profiles=[DeviceProfile.HYBRID],
        purposes=[ModelPurpose.FAST],
        downloadable=False,
    )
    report = HardwareDetector(adapter=FakeHardwareAdapter.create_bangho_preset()).detect()

    plan = ModelPlanner(ModelCatalog([oversized])).plan(
        report,
        profile=DeviceProfile.HYBRID,
        inference_profile=InferenceProfile.FAST,
        require_downloadable=False,
    )

    assert plan.is_viable is False
    assert "NO_VIABLE_LOCAL_MODEL" in plan.reason_codes


def test_planner_produces_no_model_plan_on_satellite() -> None:
    adapter = FakeHardwareAdapter.create_satellite_preset()
    detector = HardwareDetector(adapter=adapter)
    report = detector.detect()

    planner = ModelPlanner()
    plan = planner.plan(report, profile=DeviceProfile.SATELLITE)

    assert plan.is_viable is False
    assert plan.selected_model_id is None
    assert "SATELLITE_NO_LOCAL_LLM" in plan.reason_codes


def test_planner_validation_and_unknown_ram() -> None:
    from ailen.hardware.contracts import RamInfo

    planner = ModelPlanner()
    adapter = FakeHardwareAdapter.create_lab_pc_preset()
    detector = HardwareDetector(adapter=adapter)
    report = detector.detect()

    # 1. Invalid fraction parameter
    with pytest.raises(ValueError, match="max_ram_fraction must be in"):
        planner.plan(report, max_ram_fraction=0.0)

    with pytest.raises(ValueError, match="max_vram_fraction must be in"):
        planner.plan(report, max_vram_fraction=1.5)

    # 2. Unknown / zero RAM probe
    unmeasured_adapter = FakeHardwareAdapter(ram=RamInfo(total_bytes=0, available_bytes=0))
    unmeasured_report = HardwareDetector(adapter=unmeasured_adapter).detect()
    plan_unmeasured = planner.plan(unmeasured_report)

    assert plan_unmeasured.is_viable is False
    assert "HARDWARE_RAM_UNKNOWN" in plan_unmeasured.reason_codes
    assert "LOCAL_PLAN_BLOCKED_INSUFFICIENT_EVIDENCE" in plan_unmeasured.reason_codes


def _ranked_test_catalog() -> ModelCatalog:
    return ModelCatalog(
        [
            ModelDescriptor(
                model_id="small-qualified",
                display_name="Small qualified",
                family="test",
                runtime="llama.cpp",
                artifact_format="gguf",
                quantization="q4_k_m",
                parameter_class="tiny",
                ram_requirement_mb=900,
                vram_requirement_mb=1000,
                disk_size_bytes=100_000_000,
                suitability_profiles=[DeviceProfile.HYBRID],
                purposes=[ModelPurpose.BALANCED],
                quality_rank=20,
                qualification_status=ModelQualificationStatus.QUALIFIED,
                benchmark_status="measured_target",
            ),
            ModelDescriptor(
                model_id="larger-qualified",
                display_name="Larger qualified",
                family="test",
                runtime="llama.cpp",
                artifact_format="gguf",
                quantization="q4_k_m",
                parameter_class="small",
                ram_requirement_mb=2400,
                vram_requirement_mb=2600,
                disk_size_bytes=200_000_000,
                suitability_profiles=[DeviceProfile.HYBRID],
                purposes=[ModelPurpose.BALANCED],
                quality_rank=80,
                qualification_status=ModelQualificationStatus.QUALIFIED,
                benchmark_status="measured_target",
            ),
        ]
    )


def test_8gb_planner_selects_best_qualified_quality_that_fits() -> None:
    report = HardwareDetector(adapter=FakeHardwareAdapter.create_bangho_preset()).detect()

    plan = ModelPlanner(_ranked_test_catalog()).plan(
        report,
        profile=DeviceProfile.HYBRID,
        require_downloadable=False,
    )

    assert plan.selected_model_id == "larger-qualified"
    assert plan.fallback_model_ids == ["small-qualified"]
    assert plan.model_descriptor is not None
    assert plan.model_descriptor.quality_rank == 80


def test_4gb_planner_keeps_small_model_when_higher_quality_does_not_fit() -> None:
    report = HardwareDetector(adapter=FakeHardwareAdapter.create_sf20ba_preset()).detect()

    plan = ModelPlanner(_ranked_test_catalog()).plan(
        report,
        profile=DeviceProfile.HYBRID,
        require_downloadable=False,
    )

    assert plan.selected_model_id == "small-qualified"
    assert "larger-qualified" not in plan.fallback_model_ids
