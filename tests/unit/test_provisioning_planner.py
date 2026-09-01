"""Hardware-driven provisioning plans never silently install candidates."""

from __future__ import annotations

import json
from pathlib import Path

from ailen.domain.enums import DeviceProfile
from ailen.hardware.contracts import (
    CpuInfo,
    DiskInfo,
    GpuInfo,
    HardwareCapabilityReport,
    OsFamily,
    RamInfo,
)
from ailen.models.catalog import ModelCatalog, ModelDescriptor, ModelPurpose
from ailen.provisioning.planner import (
    HardwareModelQualification,
    HardwareQualificationStore,
    ProvisioningPlanner,
    hardware_class_id,
)


def _report(
    ram_mb: int,
    available_mb: int,
    *,
    avx2: bool = True,
    vram_mb: int = 0,
) -> HardwareCapabilityReport:
    gpus = []
    if vram_mb:
        gpus.append(
            GpuInfo(
                vendor="nvidia",
                model=f"synthetic-{vram_mb}",
                is_dedicated=True,
                vram_total_mb=vram_mb,
                vram_available_mb=int(vram_mb * 0.9),
                backend="cuda",
            )
        )
    return HardwareCapabilityReport(
        timestamp_utc="2026-09-01T00:00:00Z",
        os_name="linux",
        os_version="test",
        os_distribution="test",
        os_family=OsFamily.LINUX,
        cpu=CpuInfo(
            model="synthetic",
            architecture="x86_64",
            flags=["avx2"] if avx2 else [],
            has_avx2=avx2,
        ),
        ram=RamInfo(
            total_bytes=ram_mb * 1024 * 1024,
            available_bytes=available_mb * 1024 * 1024,
        ),
        gpus=gpus,
        disk=DiskInfo(
            path="/test",
            total_bytes=100 * 1024**3,
            free_bytes=80 * 1024**3,
        ),
    )


def _model(model_id: str, ram: int, vram: int, quality: int) -> ModelDescriptor:
    return ModelDescriptor(
        model_id=model_id,
        display_name=model_id,
        family="synthetic",
        runtime="llama.cpp",
        artifact_format="gguf",
        quantization="q4_k_m",
        parameter_class="test",
        ram_requirement_mb=ram,
        vram_requirement_mb=vram,
        disk_size_bytes=ram * 500_000,
        source_url=f"https://models.example/{model_id}.gguf",
        sha256="a" * 64,
        downloadable=True,
        license_name="Apache-2.0",
        source_reference=f"synthetic/{model_id}",
        suitability_profiles=[DeviceProfile.HYBRID, DeviceProfile.LOCAL],
        purposes=[ModelPurpose.FAST, ModelPurpose.BALANCED, ModelPurpose.QUALITY],
        quality_rank=quality,
        supported_runtimes=["llama.cpp", "ollama"],
    )


MODELS = ModelCatalog(
    [
        _model("small", 900, 1000, 20),
        _model("medium", 2400, 2600, 60),
        _model("large", 5600, 5600, 90),
        _model("xlarge", 9000, 8500, 120),
        _model("xxlarge", 16000, 16000, 150),
    ]
)


def _qualified_store(*reports: HardwareCapabilityReport) -> HardwareQualificationStore:
    evidence = []
    for report in reports:
        hardware_class = hardware_class_id(report)
        for model in MODELS.list_models():
            usable_vram_mb = max(
                (
                    int((gpu.vram_available_mb or 0) * 0.8)
                    for gpu in report.gpus
                    if gpu.is_dedicated and gpu.backend == "cuda"
                ),
                default=0,
            )
            uses_cuda = (
                usable_vram_mb > 0
                and model.vram_requirement_mb <= usable_vram_mb
            )
            evidence.append(
                HardwareModelQualification(
                    model_id=model.model_id,
                    hardware_class=hardware_class,
                    status="qualified",
                    quality_score=model.quality_rank / 150,
                    ttfa_ms=500.0,
                    tokens_per_second=20.0,
                    runtime="llama.cpp",
                    context_tokens=model.context_default,
                    evidence_reference=f"synthetic:{hardware_class}:{model.model_id}",
                    execution_device="cuda" if uses_cuda else "cpu",
                    gpu_layers="all" if uses_cuda else 0,
                    peak_vram_mb=(model.vram_requirement_mb if uses_cuda else None),
                )
            )
    return HardwareQualificationStore(evidence)


def _runtime_evidence(
    report: HardwareCapabilityReport,
    *,
    model_id: str = "large",
    runtime: str,
    quality_score: float = 0.8,
    ttfa_ms: float = 500.0,
    tokens_per_second: float = 20.0,
    execution_device: str = "cpu",
    gpu_layers: int | str = 0,
    peak_rss_mb: int | None = None,
    peak_vram_mb: int | None = None,
    context_tokens: int = 4096,
) -> HardwareModelQualification:
    return HardwareModelQualification(
        model_id=model_id,
        hardware_class=hardware_class_id(report),
        status="qualified",
        quality_score=quality_score,
        ttfa_ms=ttfa_ms,
        tokens_per_second=tokens_per_second,
        runtime=runtime,
        context_tokens=context_tokens,
        evidence_reference=f"synthetic:{runtime}:{model_id}",
        execution_device=execution_device,
        gpu_layers=gpu_layers,
        peak_rss_mb=peak_rss_mb,
        peak_vram_mb=peak_vram_mb,
    )


def test_default_catalog_has_no_silent_production_install_without_target_evidence() -> None:
    report = _report(8192, 6500)
    plan = ProvisioningPlanner().plan(report)

    assert plan.primary_model_id is None
    assert plan.auto_download_allowed is False
    assert plan.candidate_model_ids
    assert "NO_TARGET_QUALIFIED_MODEL" in plan.reason_codes


def test_4gb_without_avx2_selects_only_safe_small_qualified_model() -> None:
    report = _report(4096, 2800, avx2=False)
    plan = ProvisioningPlanner(
        catalog=MODELS,
        qualifications=_qualified_store(report),
    ).plan(report)

    assert plan.primary_model_id == "small"
    assert plan.estimated_model_ram_mb == 900
    assert plan.reserved_system_ram_mb >= 700
    assert plan.auto_download_allowed is True


def test_8gb_and_16gb_scale_quality_inside_memory_envelope() -> None:
    report_8 = _report(8192, 6500)
    report_16 = _report(16384, 14500)
    store = _qualified_store(report_8, report_16)
    planner = ProvisioningPlanner(catalog=MODELS, qualifications=store)

    assert planner.plan(report_8).primary_model_id == "medium"
    assert planner.plan(report_16).primary_model_id == "large"


def test_32gb_and_64gb_cpu_can_select_qualified_models_above_old_cap() -> None:
    report_32 = _report(32768, 30000)
    report_64 = _report(65536, 60000)
    planner = ProvisioningPlanner(
        catalog=MODELS,
        qualifications=_qualified_store(report_32, report_64),
    )

    plan_32 = planner.plan(report_32)
    plan_64 = planner.plan(report_64)

    assert plan_32.primary_model_id == "xxlarge"
    assert plan_32.estimated_model_ram_mb == 16000
    assert plan_64.primary_model_id == "xxlarge"
    assert plan_64.context_tokens >= plan_32.context_tokens


def test_gpu_profiles_scale_without_forcing_smallest_model() -> None:
    reports = [
        _report(8192, 6500, vram_mb=6144),
        _report(16384, 14500, vram_mb=8192),
        _report(24576, 22000, vram_mb=12288),
        _report(65536, 60000, vram_mb=24576),
    ]
    planner = ProvisioningPlanner(
        catalog=MODELS,
        qualifications=_qualified_store(*reports),
    )

    assert [planner.plan(report).primary_model_id for report in reports] == [
        "medium",
        "large",
        "xlarge",
        "xxlarge",
    ]
    assert [planner.plan(report).gpu_layers for report in reports] == [
        "all",
        "all",
        "all",
        "all",
    ]


def test_runtime_selection_uses_llama_cpp_when_it_is_the_only_qualified_runtime() -> None:
    report = _report(16384, 14500, vram_mb=8192)
    planner = ProvisioningPlanner(
        catalog=MODELS,
        qualifications=HardwareQualificationStore(
            [_runtime_evidence(report, runtime="llama.cpp")]
        ),
    )

    plan = planner.plan(report)

    assert plan.primary_model_id == "large"
    assert plan.runtime == "llama.cpp"
    assert plan.gpu_layers == 0
    assert "CPU_INFERENCE_ZERO_GPU_LAYERS" in plan.reason_codes


def test_runtime_selection_uses_ollama_when_it_is_the_only_qualified_runtime() -> None:
    report = _report(16384, 14500, vram_mb=8192)
    planner = ProvisioningPlanner(
        catalog=MODELS,
        qualifications=HardwareQualificationStore(
            [_runtime_evidence(report, runtime="ollama")]
        ),
    )

    plan = planner.plan(report)

    assert plan.primary_model_id == "large"
    assert plan.runtime == "ollama"
    assert plan.execution_device == "cpu"
    assert plan.gpu_layers == 0


def test_multiple_qualified_runtimes_compete_on_measured_evidence() -> None:
    report = _report(16384, 14500, vram_mb=8192)
    llama = _runtime_evidence(
        report,
        runtime="llama.cpp",
        quality_score=0.9,
        ttfa_ms=350.0,
        tokens_per_second=28.0,
    )
    ollama = _runtime_evidence(
        report,
        runtime="ollama",
        quality_score=0.8,
        ttfa_ms=600.0,
        tokens_per_second=18.0,
    )
    planner = ProvisioningPlanner(
        catalog=MODELS,
        qualifications=HardwareQualificationStore([llama, ollama]),
    )

    plan = planner.plan(report)

    assert plan.runtime == "llama.cpp"
    assert "RUNTIME_QUALIFICATION_LLAMA_CPP_SELECTED" in plan.reason_codes


def test_gpu_offload_is_selected_only_when_the_runtime_evidence_measured_it() -> None:
    report = _report(16384, 14500, vram_mb=8192)
    cpu_planner = ProvisioningPlanner(
        catalog=MODELS,
        qualifications=HardwareQualificationStore(
            [_runtime_evidence(report, model_id="medium", runtime="llama.cpp")]
        ),
    )
    cuda_planner = ProvisioningPlanner(
        catalog=MODELS,
        qualifications=HardwareQualificationStore(
            [
                _runtime_evidence(
                    report,
                    model_id="medium",
                    runtime="llama.cpp",
                    execution_device="cuda",
                    gpu_layers="all",
                    peak_vram_mb=2600,
                )
            ]
        ),
    )

    cpu_plan = cpu_planner.plan(report)
    cuda_plan = cuda_planner.plan(report)

    assert cpu_plan.execution_device == "cpu"
    assert cpu_plan.gpu_layers == 0
    assert "CPU_INFERENCE_ZERO_GPU_LAYERS" in cpu_plan.reason_codes
    assert cuda_plan.execution_device == "cuda"
    assert cuda_plan.gpu_layers == "all"
    assert "OFFLOAD_ALL_LAYERS" in cuda_plan.reason_codes


def test_runtime_qualifications_are_indexed_without_cross_runtime_overwrite() -> None:
    report = _report(16384, 14500)
    llama = _runtime_evidence(report, runtime="llama.cpp")
    ollama = _runtime_evidence(report, runtime="ollama")
    store = HardwareQualificationStore([llama, ollama])
    hardware_class = hardware_class_id(report)

    assert store.get(hardware_class, "large", "llama.cpp") == llama
    assert store.get(hardware_class, "large", "ollama") == ollama
    assert store.qualified_for_model(hardware_class, "large") == [llama, ollama]


def test_install_plan_is_declarative_and_requires_consent() -> None:
    report = _report(8192, 6500)
    plan = ProvisioningPlanner(
        catalog=MODELS,
        qualifications=_qualified_store(report),
    ).plan(report)

    assert plan.runtime in {"llama.cpp", "ollama"}
    assert plan.context_tokens > 0
    assert plan.download_size_bytes > 0
    assert plan.required_assets == ("stt", "tts", "facepack")
    assert "download_model:medium" in plan.consent_actions
    assert plan.artifact_sha256 == "a" * 64
    assert plan.artifact_url.startswith("https://")
    assert plan.os_name == "linux"
    assert plan.cpu_architecture == "x86_64"
    assert plan.cpu_logical_cores is None
    assert plan.disk_free_bytes == 80 * 1024**3
    assert plan.dedicated_vram_available_mb == 0


def test_measured_context_caps_the_activated_runtime_plan() -> None:
    report = _report(32768, 30000)
    planner = ProvisioningPlanner(
        catalog=MODELS,
        qualifications=HardwareQualificationStore(
            [
                _runtime_evidence(
                    report,
                    model_id="xlarge",
                    runtime="llama.cpp",
                    context_tokens=1024,
                )
            ]
        ),
    )

    plan = planner.plan(report)

    assert plan.primary_model_id == "xlarge"
    assert plan.context_tokens == 1024


def test_qualified_manual_lab_override_is_honored_without_bypassing_fit() -> None:
    report = _report(16384, 14500)
    planner = ProvisioningPlanner(
        catalog=MODELS,
        qualifications=_qualified_store(report),
    )

    plan = planner.plan(report, manual_model_override="medium")

    assert plan.primary_model_id == "medium"
    assert plan.auto_download_allowed is True
    assert "MANUAL_MODEL_OVERRIDE_SELECTED" in plan.reason_codes


def test_unqualified_manual_lab_override_remains_candidate_only() -> None:
    report = _report(8192, 6500)

    plan = ProvisioningPlanner(catalog=MODELS).plan(
        report,
        manual_model_override="medium",
    )

    assert plan.primary_model_id is None
    assert plan.auto_download_allowed is False
    assert plan.candidate_model_ids[0] == "medium"
    assert "MANUAL_MODEL_OVERRIDE_NOT_TARGET_QUALIFIED" in plan.reason_codes


def test_qualification_store_is_hardware_scoped_and_versioned(tmp_path: Path) -> None:
    report = _report(8192, 6500)
    record = HardwareModelQualification(
        model_id="medium",
        hardware_class=hardware_class_id(report),
        status="qualified",
        quality_score=0.8,
        ttfa_ms=450.0,
        tokens_per_second=25.0,
        runtime="llama.cpp",
        context_tokens=2048,
        evidence_reference="lab-report:test",
    )
    (tmp_path / "medium.json").write_text(
        json.dumps(
            {"schema_version": 1, "qualification": record.__dict__},
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    store = HardwareQualificationStore.from_directory(tmp_path)

    assert store.get(hardware_class_id(report), "medium", "llama.cpp") == record
    assert store.get("different-hardware", "medium", "llama.cpp") is None
