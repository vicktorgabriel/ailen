"""Hybrid deployment recommendation structure for system onboarding."""

from dataclasses import asdict, dataclass, field
from typing import Any

from ailen.domain.enums import DeviceProfile, InferenceProfile
from ailen.hardware.contracts import HardwareCapabilityReport
from ailen.hardware.detector import HardwareDetector
from ailen.models.inference_profile import recommend_inference_profile


@dataclass(frozen=True)
class RecommendedDeployment:
    """Consolidated deployment recommendation for onboarding configuration."""
    device_profile: DeviceProfile
    inference_profile: InferenceProfile
    local_model: str | None
    lan_brain_available: bool
    cloud_recommended: bool
    web_search_available: bool
    estimated_external_cost: str = "UNKNOWN"  # "NONE_LOCAL_ONLY", "UNKNOWN_EXTERNAL_PAID", "CONFIGURABLE"
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["device_profile"] = self.device_profile.value
        d["inference_profile"] = self.inference_profile.value
        return d


def create_deployment_recommendation(
    report: HardwareCapabilityReport,
    lan_brain_detected: bool = False,
    allow_remote: bool = False,
    user_preferences: dict[str, Any] | None = None,
) -> RecommendedDeployment:
    """Analyze hardware and network context to recommend the optimal onboarding topology."""
    dev_prof = HardwareDetector().recommend_profile(report).profile

    inf_rec = recommend_inference_profile(
        report=report,
        device_profile=dev_prof,
        user_preferences=user_preferences,
    )

    reasons = list(inf_rec.reason_codes)

    cloud_rec = False
    if inf_rec.profile == InferenceProfile.RULE_ONLY and allow_remote:
        cloud_rec = True
        reasons.append("CLOUD_FALLBACK_RECOMMENDED_FOR_RULE_ONLY_NODE")

    ext_cost = "NONE_LOCAL_ONLY"
    if cloud_rec or (user_preferences and user_preferences.get("enable_web_search")):
        ext_cost = "UNKNOWN_EXTERNAL_PROVIDER_COST"

    local_model: str | None = None
    if inf_rec.local_allowed:
        reasons.append("LOCAL_MODEL_SELECTION_PENDING_MODEL_PLANNER")

    return RecommendedDeployment(
        device_profile=dev_prof,
        inference_profile=inf_rec.profile,
        local_model=local_model,
        lan_brain_available=lan_brain_detected,
        cloud_recommended=cloud_rec,
        web_search_available=bool(user_preferences and user_preferences.get("enable_web_search", False)),
        estimated_external_cost=ext_cost,
        reason_codes=reasons,
    )
