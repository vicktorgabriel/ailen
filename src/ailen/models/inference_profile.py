"""Deterministic inference profile recommendation for heterogeneous hardware."""

from dataclasses import asdict, dataclass, field, replace
from typing import Any

from ailen.domain.enums import DeviceProfile, InferenceProfile
from ailen.hardware.contracts import HardwareCapabilityReport


@dataclass(frozen=True)
class InferenceRecommendation:
    """Deterministic recommendation for local inference tier and memory budget."""

    profile: InferenceProfile
    local_allowed: bool
    preferred_runtime: str
    max_model_ram_mb: int
    max_model_vram_mb: int
    recommended_context: int
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["profile"] = self.profile.value
        return data


_PROFILE_RANK = {
    InferenceProfile.RULE_ONLY: 0,
    InferenceProfile.FAST: 1,
    InferenceProfile.BALANCED: 2,
    InferenceProfile.QUALITY: 3,
}


def _apply_user_profile_cap(
    recommendation: InferenceRecommendation,
    requested: InferenceProfile | None,
) -> InferenceRecommendation:
    """Allow user preference to reduce load, never to exceed measured capability."""
    if requested is None or requested == recommendation.profile:
        return recommendation

    reasons = list(recommendation.reason_codes)
    if _PROFILE_RANK[requested] > _PROFILE_RANK[recommendation.profile]:
        reasons.append(f"USER_PROFILE_UPSHIFT_{requested.value}_BLOCKED_BY_HARDWARE")
        return replace(recommendation, reason_codes=reasons)

    reasons.append(f"USER_FORCED_INFERENCE_PROFILE_{requested.value}")
    if requested == InferenceProfile.RULE_ONLY:
        return InferenceRecommendation(
            profile=InferenceProfile.RULE_ONLY,
            local_allowed=False,
            preferred_runtime="none",
            max_model_ram_mb=0,
            max_model_vram_mb=0,
            recommended_context=1024,
            reason_codes=reasons,
        )

    context = 2048 if requested == InferenceProfile.FAST else 4096
    return replace(recommendation, profile=requested, recommended_context=min(context, recommendation.recommended_context), reason_codes=reasons)


def recommend_inference_profile(
    report: HardwareCapabilityReport,
    device_profile: DeviceProfile | None = None,
    user_preferences: dict[str, Any] | None = None,
) -> InferenceRecommendation:
    """Evaluate measured hardware and produce a safe inference recommendation.

    CPU-only is first-class. User preferences may conservatively lower the tier,
    but cannot force a tier above the capability established by measured hardware.
    """
    prefs = user_preferences or {}
    reasons: list[str] = []

    requested_profile: InferenceProfile | None = None
    requested_raw = prefs.get("force_inference_profile")
    if isinstance(requested_raw, str) and requested_raw in InferenceProfile._value2member_map_:
        requested_profile = InferenceProfile(requested_raw)

    if not report.ram or report.ram.total_bytes <= 0:
        return InferenceRecommendation(
            profile=InferenceProfile.RULE_ONLY,
            local_allowed=False,
            preferred_runtime="none",
            max_model_ram_mb=0,
            max_model_vram_mb=0,
            recommended_context=1024,
            reason_codes=["HARDWARE_RAM_UNKNOWN", "INFERENCE_PROFILE_RULE_ONLY_NO_RAM_MEASUREMENT"],
        )

    ram_total_mb = int(report.ram.total_bytes / (1024 * 1024))
    ram_avail_mb = int(report.ram.available_bytes / (1024 * 1024)) if report.ram.available_bytes else ram_total_mb

    if device_profile in (DeviceProfile.SATELLITE, DeviceProfile.CLOUD):
        return InferenceRecommendation(
            profile=InferenceProfile.RULE_ONLY,
            local_allowed=False,
            preferred_runtime="none",
            max_model_ram_mb=0,
            max_model_vram_mb=0,
            recommended_context=1024,
            reason_codes=[f"DEVICE_PROFILE_{device_profile.value}_RESTRICTS_LOCAL_LLM"],
        )

    vram_total_mb = 0
    vram_avail_mb = 0
    has_dedicated_gpu = False
    for gpu in report.gpus or []:
        if gpu.vram_total_mb and gpu.vram_total_mb > 0:
            vram_total_mb += gpu.vram_total_mb
            vram_avail_mb += gpu.vram_available_mb or gpu.vram_total_mb
            if gpu.is_dedicated and gpu.vram_total_mb >= 2048:
                has_dedicated_gpu = True

    if has_dedicated_gpu:
        reasons.append(f"DEDICATED_GPU_DETECTED_VRAM_{vram_total_mb}MB")
        if vram_total_mb >= 10000 and ram_total_mb >= 14000:
            reasons.append("HIGH_VRAM_HIGH_RAM_ENABLES_QUALITY")
            baseline = InferenceRecommendation(
                InferenceProfile.QUALITY, True, "ollama", int(ram_total_mb * 0.6),
                min(vram_avail_mb, int(vram_total_mb * 0.85)), 8192, reasons,
            )
        elif vram_total_mb >= 5500:
            reasons.append("MEDIUM_VRAM_ENABLES_BALANCED")
            baseline = InferenceRecommendation(
                InferenceProfile.BALANCED, True, "ollama", int(ram_total_mb * 0.5),
                min(vram_avail_mb, int(vram_total_mb * 0.8)), 4096, reasons,
            )
        else:
            reasons.append("MODEST_GPU_ENABLES_FAST")
            baseline = InferenceRecommendation(
                InferenceProfile.FAST, True, "ollama", int(ram_total_mb * 0.5),
                min(vram_avail_mb, int(vram_total_mb * 0.75)), 2048, reasons,
            )
        return _apply_user_profile_cap(baseline, requested_profile)

    reasons.append("CPU_ONLY_OR_SHARED_VRAM")
    if ram_total_mb < 3500:
        reasons.append("RAM_UNDER_3500MB_FORCES_RULE_ONLY")
        baseline = InferenceRecommendation(InferenceProfile.RULE_ONLY, False, "none", 0, 0, 1024, reasons)
    elif ram_total_mb < 6500:
        if bool(prefs.get("allow_4gb_cpu_llm", False)):
            reasons.append("EXPERIMENTAL_4GB_FAST_OPT_IN")
            baseline = InferenceRecommendation(InferenceProfile.FAST, True, "llama.cpp", 1200, 0, 1024, reasons)
        else:
            reasons.append("RAM_4GB_CPU_TIER_DEFAULT_RULE_ONLY_CONSERVATIVE")
            baseline = InferenceRecommendation(InferenceProfile.RULE_ONLY, False, "none", 0, 0, 1024, reasons)
    elif ram_total_mb < 12500:
        reasons.append("RAM_8GB_CPU_ENABLES_FAST_TIER")
        baseline = InferenceRecommendation(
            InferenceProfile.FAST, True, "llama.cpp", min(3500, int(ram_avail_mb * 0.75)), 0, 2048, reasons
        )
    else:
        reasons.append("RAM_16GB_PLUS_CPU_ENABLES_BALANCED_TIER")
        baseline = InferenceRecommendation(
            InferenceProfile.BALANCED, True, "llama.cpp", min(int(ram_total_mb * 0.45), int(ram_avail_mb * 0.8)), 0, 4096, reasons
        )

    return _apply_user_profile_cap(baseline, requested_profile)
