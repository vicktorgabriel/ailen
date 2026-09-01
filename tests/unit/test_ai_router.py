"""Behavioral tests for dynamic local/LAN/remote routing."""

from ailen.ai.router import (
    ROUTE_DEGRADED,
    ROUTE_LAN_BRAIN,
    ROUTE_LOCAL,
    ROUTE_RULE_ONLY,
    RouteRequest,
    RuleBasedRouter,
)
from ailen.domain.enums import DeviceProfile, PrivacyLevel


def test_router_rule_only_fast_path() -> None:
    plan = RuleBasedRouter().route(RouteRequest(intent="volume"))
    assert plan.primary_backend == ROUTE_RULE_ONLY
    assert plan.context_budget == 0


def test_user_greeting_is_conversational_not_rule_only() -> None:
    plan = RuleBasedRouter().route(
        RouteRequest(intent="greeting", local_backend_available=True)
    )
    assert plan.primary_backend == ROUTE_LOCAL


def test_private_remote_requires_current_turn_sanitization_opt_in() -> None:
    plan = RuleBasedRouter().route(
        RouteRequest(
            privacy_level=PrivacyLevel.PRIVATE,
            internet_available=True,
            external_allowed=True,
            remote_backends=("remote:openai",),
            preferred_backend="remote:openai",
        )
    )
    assert plan.primary_backend == ROUTE_DEGRADED
    assert plan.reason_code == "PRIVATE_REMOTE_BLOCKED"


def test_public_remote_can_route_without_private_sanitization_flag() -> None:
    plan = RuleBasedRouter().route(
        RouteRequest(
            complexity="high",
            privacy_level=PrivacyLevel.PUBLIC,
            internet_available=True,
            external_allowed=True,
            remote_backends=("remote:openai",),
        )
    )
    assert plan.primary_backend == "remote:openai"
    assert plan.privacy_decision == "ALLOWED"


def test_private_untrusted_lan_is_blocked() -> None:
    plan = RuleBasedRouter().route(
        RouteRequest(
            privacy_level=PrivacyLevel.PRIVATE,
            local_backend_available=True,
            lan_brain_available=True,
            lan_brain_trusted=False,
        )
    )
    assert plan.primary_backend == ROUTE_LOCAL
    assert ROUTE_LAN_BRAIN not in plan.fallback_backends


def test_satellite_prefers_trusted_lan() -> None:
    plan = RuleBasedRouter().route(
        RouteRequest(
            profile=DeviceProfile.SATELLITE,
            privacy_level=PrivacyLevel.PRIVATE,
            lan_brain_available=True,
            lan_brain_trusted=True,
            local_backend_available=True,
        )
    )
    assert plan.primary_backend == ROUTE_LAN_BRAIN
    assert plan.fallback_backends == [ROUTE_LOCAL]


def test_explicit_remote_honored_even_when_not_voice_realtime_qualified() -> None:
    plan = RuleBasedRouter().route(
        RouteRequest(
            input_modality="voice",
            privacy_level=PrivacyLevel.PRIVATE,
            internet_available=True,
            external_allowed=True,
            allow_sanitized_external_prompts=True,
            remote_backends=("remote:manual",),
            preferred_backend="remote:manual",
            realtime_eligible_backends={"remote:manual": False},
        )
    )
    assert plan.primary_backend == "remote:manual"
    assert plan.reason_code == "CONFIGURED_REMOTE:MANUAL_PREFERRED"


def test_auto_voice_does_not_promote_unqualified_remote() -> None:
    plan = RuleBasedRouter().route(
        RouteRequest(
            input_modality="voice",
            privacy_level=PrivacyLevel.PRIVATE,
            internet_available=True,
            external_allowed=True,
            allow_sanitized_external_prompts=True,
            remote_backends=("remote:slow",),
            realtime_eligible_backends={"remote:slow": False},
        )
    )
    assert plan.primary_backend == ROUTE_DEGRADED
    assert plan.reason_code == "NO_REALTIME_VOICE_BACKEND"


def test_auto_voice_keeps_nonrealtime_remote_only_as_fallback() -> None:
    plan = RuleBasedRouter().route(
        RouteRequest(
            input_modality="voice",
            privacy_level=PrivacyLevel.PRIVATE,
            internet_available=True,
            external_allowed=True,
            allow_sanitized_external_prompts=True,
            local_backend_available=True,
            remote_backends=("remote:slow",),
            realtime_eligible_backends={"remote:slow": False},
        )
    )
    assert plan.primary_backend == ROUTE_LOCAL
    assert plan.fallback_backends == ["remote:slow"]


def test_no_backend_degrades_honestly() -> None:
    plan = RuleBasedRouter().route(RouteRequest(internet_available=False))
    assert plan.primary_backend == ROUTE_DEGRADED
    assert plan.reason_code == "ALL_BACKENDS_UNAVAILABLE"
