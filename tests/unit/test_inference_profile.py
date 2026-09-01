from ailen.domain.enums import DeviceProfile, InferenceProfile
from ailen.hardware.contracts import (
    CpuInfo,
    DiskInfo,
    GpuInfo,
    HardwareCapabilityReport,
    OsFamily,
    RamInfo,
)
from ailen.models.inference_profile import recommend_inference_profile


def make_report(
    ram_mb: int,
    gpus: list[GpuInfo] | None = None,
    has_avx2: bool = True,
    os_name: str = "linux",
) -> HardwareCapabilityReport:
    """Helper to build HardwareCapabilityReport."""
    total_bytes = ram_mb * 1024 * 1024
    ram = RamInfo(
        total_bytes=total_bytes,
        available_bytes=int(total_bytes * 0.8),
    )
    cpu = CpuInfo(
        model="Test CPU",
        physical_cores=4,
        logical_cores=8,
        architecture="x86_64",
        has_avx=True,
        has_avx2=has_avx2,
        has_neon=False,
        flags=["avx", "avx2"] if has_avx2 else ["avx"],
    )
    disk = DiskInfo(
        path="/",
        total_bytes=100_000_000_000,
        free_bytes=50_000_000_000,
    )
    return HardwareCapabilityReport(
        timestamp_utc="2026-08-22T00:00:00Z",
        os_name=os_name,
        os_version="6.8.0",
        os_distribution="Linux Mint 22.3",
        os_family=OsFamily.LINUX,
        cpu=cpu,
        ram=ram,
        gpus=gpus or [],
        disk=disk,
    )


def test_missing_or_zero_ram_returns_rule_only() -> None:
    rep = make_report(0)
    rep = HardwareCapabilityReport(
        timestamp_utc="2026-08-22T00:00:00Z",
        os_name="linux",
        os_version="6.8.0",
        os_distribution="Linux Mint 22.3",
        os_family=OsFamily.LINUX,
        cpu=rep.cpu,
        ram=RamInfo(total_bytes=0, available_bytes=0),
        gpus=[],
        disk=rep.disk,
    )
    rec = recommend_inference_profile(rep)
    assert rec.profile == InferenceProfile.RULE_ONLY
    assert not rec.local_allowed
    assert "HARDWARE_RAM_UNKNOWN" in rec.reason_codes


def test_2gb_cpu_only_satellite_tier() -> None:
    rep = make_report(2048)  # 2 GB
    rec = recommend_inference_profile(rep)
    assert rec.profile == InferenceProfile.RULE_ONLY
    assert not rec.local_allowed
    assert "RAM_UNDER_3500MB_FORCES_RULE_ONLY" in rec.reason_codes


def test_4gb_cpu_only_exposes_bounded_local_fast_path_by_default() -> None:
    rep = make_report(4096)  # 4 GB (e.g. Netbook SF20BA)
    rec = recommend_inference_profile(rep)
    assert rec.profile == InferenceProfile.FAST
    assert rec.local_allowed
    assert rec.preferred_runtime == "llama.cpp"
    assert rec.max_model_ram_mb == 1400
    assert "TARGET_4GB_BENCHMARK_REQUIRED" in rec.reason_codes


def test_legacy_4gb_opt_in_no_longer_changes_the_canonical_profile() -> None:
    rep = make_report(4096)
    rec = recommend_inference_profile(rep, user_preferences={"allow_4gb_cpu_llm": True})
    assert rec.profile == InferenceProfile.FAST
    assert rec.local_allowed
    assert rec.preferred_runtime == "llama.cpp"
    assert rec.max_model_ram_mb == 1400


def test_8gb_cpu_only_fast_tier() -> None:
    rep = make_report(8192)  # 8 GB (e.g. Banghó Zero G05)
    rec = recommend_inference_profile(rep)
    assert rec.profile == InferenceProfile.FAST
    assert rec.local_allowed
    assert rec.preferred_runtime == "llama.cpp"
    assert rec.max_model_ram_mb == 3000


def test_16gb_cpu_only_balanced_tier() -> None:
    rep = make_report(16384)  # 16 GB CPU workstation
    rec = recommend_inference_profile(rep)
    assert rec.profile == InferenceProfile.BALANCED
    assert rec.local_allowed
    assert rec.preferred_runtime == "llama.cpp"
    assert rec.max_model_ram_mb > 5000


def test_32gb_and_64gb_cpu_envelopes_keep_scaling() -> None:
    rec_32 = recommend_inference_profile(make_report(32768))
    rec_64 = recommend_inference_profile(make_report(65536))

    assert rec_32.max_model_ram_mb > 6000
    assert rec_32.recommended_context == 8192
    assert rec_64.max_model_ram_mb > rec_32.max_model_ram_mb
    assert rec_64.recommended_context == 16384


def test_modest_gpu_tier() -> None:
    gpu = GpuInfo(
        vendor="nvidia",
        model="GTX 1650",
        vram_total_mb=4096,
        vram_available_mb=3800,
        is_dedicated=True,
        backend="cuda",
    )
    rep = make_report(8192, gpus=[gpu])
    rec = recommend_inference_profile(rep)
    assert rec.profile == InferenceProfile.FAST
    assert rec.local_allowed
    assert rec.preferred_runtime == "ollama"


def test_medium_gpu_tier() -> None:
    gpu = GpuInfo(
        vendor="nvidia",
        model="RTX 3070",
        vram_total_mb=8192,
        vram_available_mb=7500,
        is_dedicated=True,
        backend="cuda",
    )
    rep = make_report(16384, gpus=[gpu])
    rec = recommend_inference_profile(rep)
    assert rec.profile == InferenceProfile.BALANCED
    assert rec.local_allowed
    assert rec.preferred_runtime == "ollama"


def test_asrock_lab_gpu_quality_tier() -> None:
    # Asrock: 48 GB RAM + RTX 3060 12 GB
    gpu = GpuInfo(
        vendor="nvidia",
        model="NVIDIA GeForce RTX 3060",
        vram_total_mb=12288,
        vram_available_mb=11500,
        is_dedicated=True,
        backend="cuda",
    )
    rep = make_report(49152, gpus=[gpu])
    rec = recommend_inference_profile(rep)
    assert rec.profile == InferenceProfile.QUALITY
    assert rec.local_allowed
    assert rec.preferred_runtime == "ollama"
    assert rec.recommended_context == 8192


def test_shared_gpu_memory_is_not_added_to_dedicated_vram_budget() -> None:
    dedicated = GpuInfo(
        vendor="nvidia",
        model="Dedicated 8 GB",
        vram_total_mb=8192,
        vram_available_mb=7000,
        is_dedicated=True,
        backend="cuda",
    )
    shared = GpuInfo(
        vendor="intel",
        model="Shared iGPU",
        vram_total_mb=8192,
        vram_available_mb=7000,
        is_dedicated=False,
        backend="vulkan",
    )

    rec = recommend_inference_profile(make_report(32768, gpus=[dedicated, shared]))

    assert rec.max_model_vram_mb == min(7000, int(8192 * 0.8))
    assert "DEDICATED_GPU_DETECTED_VRAM_8192MB" in rec.reason_codes


def test_user_forced_profile_override() -> None:
    rep = make_report(49152)
    rec = recommend_inference_profile(rep, user_preferences={"force_inference_profile": "FAST"})
    assert rec.profile == InferenceProfile.FAST
    assert "USER_FORCED_INFERENCE_PROFILE_FAST" in rec.reason_codes


def test_device_profile_satellite_restricts_local() -> None:
    gpu = GpuInfo(
        vendor="nvidia",
        model="RTX 3060",
        vram_total_mb=12288,
        vram_available_mb=11500,
        is_dedicated=True,
        backend="cuda",
    )
    rep = make_report(49152, gpus=[gpu])
    rec = recommend_inference_profile(rep, device_profile=DeviceProfile.SATELLITE)
    assert rec.profile == InferenceProfile.RULE_ONLY
    assert not rec.local_allowed


def test_user_cannot_force_profile_above_hardware_capability() -> None:
    rep = make_report(8192)
    rec = recommend_inference_profile(rep, user_preferences={"force_inference_profile": "QUALITY"})
    assert rec.profile == InferenceProfile.FAST
    assert "USER_PROFILE_UPSHIFT_QUALITY_BLOCKED_BY_HARDWARE" in rec.reason_codes
