"""Tests for onboarding deployment recommendation truthfulness."""

from ailen.domain.enums import InferenceProfile
from ailen.models.deployment import create_deployment_recommendation
from tests.unit.test_inference_profile import make_report


def test_deployment_does_not_fabricate_local_model_before_planner() -> None:
    rec = create_deployment_recommendation(make_report(8192))
    assert rec.inference_profile == InferenceProfile.FAST
    assert rec.local_model is None
    assert "LOCAL_MODEL_SELECTION_PENDING_MODEL_PLANNER" in rec.reason_codes


def test_external_cost_remains_unknown_until_provider_is_configured() -> None:
    rec = create_deployment_recommendation(
        make_report(2048), allow_cloud=True, user_preferences={"enable_web_search": True}
    )
    assert rec.estimated_external_cost == "UNKNOWN_EXTERNAL_PROVIDER_COST"
