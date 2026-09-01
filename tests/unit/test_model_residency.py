"""Unit tests for ModelResidencyPolicy and anti-model hopping enforcement."""

import pytest

from ailen.ai.residency import ModelResidencyPolicy
from ailen.domain.enums import InferenceProfile


def test_initial_assignment_and_keep_alive_mapping() -> None:
    policy = ModelResidencyPolicy(inference_profile=InferenceProfile.BALANCED)
    assert policy.primary_model is None
    assert policy.keep_alive == "15m"

    policy.set_primary_model("qwen3.5:9b", reason="STARTUP")
    assert policy.primary_model == "qwen3.5:9b"


def test_keep_alive_profile_defaults() -> None:
    assert ModelResidencyPolicy.get_default_keep_alive(InferenceProfile.RULE_ONLY) == "0"
    assert ModelResidencyPolicy.get_default_keep_alive(InferenceProfile.FAST) == "5m"
    assert ModelResidencyPolicy.get_default_keep_alive(InferenceProfile.BALANCED) == "15m"
    assert ModelResidencyPolicy.get_default_keep_alive(InferenceProfile.QUALITY) == "30m"


def test_same_model_is_always_allowed() -> None:
    policy = ModelResidencyPolicy(primary_model="qwen3.5:9b")
    allowed, reason = policy.can_switch_model("qwen3.5:9b", "PROMPT_TURN")
    assert allowed
    assert reason == "SAME_OR_INITIAL_MODEL"


def test_model_hopping_mid_session_is_prohibited() -> None:
    policy = ModelResidencyPolicy(primary_model="qwen3.5:9b")
    allowed, reason = policy.can_switch_model("llama3.2:3b", "QUERY_COMPLEXITY_SIMPLE")
    assert not allowed
    assert "MODEL_HOPPING_PROHIBITED" in reason

    with pytest.raises(PermissionError, match="MODEL_HOPPING_PROHIBITED"):
        policy.set_primary_model("llama3.2:3b", reason="QUERY_COMPLEXITY_SIMPLE")


def test_allowed_model_switch_reasons() -> None:
    policy = ModelResidencyPolicy(primary_model="qwen3.5:9b")

    for allowed_reason in ["PROFILE_CHANGE", "BACKEND_FAILOVER", "ADMIN_OVERRIDE", "NEW_SESSION"]:
        allowed, msg = policy.can_switch_model("llama3.2:3b", allowed_reason)
        assert allowed
        assert f"ALLOWED_REASON_{allowed_reason}" in msg

    policy.set_primary_model("llama3.2:3b", reason="BACKEND_FAILOVER")
    assert policy.primary_model == "llama3.2:3b"


def test_memory_pressure_thresholds_are_profile_bounded() -> None:
    fast = ModelResidencyPolicy(inference_profile=InferenceProfile.FAST)
    balanced = ModelResidencyPolicy(inference_profile=InferenceProfile.BALANCED)

    assert fast.minimum_free_memory_mb == 700
    assert fast.should_release(available_memory_mb=699) is True
    assert fast.should_release(available_memory_mb=700) is False
    assert balanced.minimum_free_memory_mb == 1200
