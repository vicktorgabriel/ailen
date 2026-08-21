"""Unit tests for RuleBasedRouter."""

from ailen.ai.router import (
    ROUTE_CLOUD,
    ROUTE_DEGRADED,
    ROUTE_LAN_BRAIN,
    ROUTE_LOCAL,
    ROUTE_RULE_ONLY,
    RouteRequest,
    RuleBasedRouter,
)
from ailen.domain.enums import DeviceProfile, PrivacyLevel


def test_router_rule_only_fast_path() -> None:
    router = RuleBasedRouter()
    req = RouteRequest(intent="volume", privacy_level=PrivacyLevel.PUBLIC)
    plan = router.route(req)

    assert plan.primary_backend == ROUTE_RULE_ONLY
    assert plan.fallback_backends == []
    assert plan.reason_code == "RULE_ONLY_INTENT"
    assert plan.context_budget == 0


def test_router_hybrid_private_blocks_cloud() -> None:
    router = RuleBasedRouter()
    req = RouteRequest(
        intent="chat",
        profile=DeviceProfile.HYBRID,
        privacy_level=PrivacyLevel.PRIVATE,
        internet_available=True,
        cloud_allowed=True,
        local_backend_available=True,
        lan_brain_available=True,
        lan_brain_trusted=True,
    )
    plan = router.route(req)

    assert plan.primary_backend == ROUTE_LOCAL
    assert plan.fallback_backends == [ROUTE_LAN_BRAIN]
    assert ROUTE_CLOUD not in plan.fallback_backends
    assert plan.estimated_remote_allowance is False


def test_router_private_does_not_use_untrusted_lan_by_default() -> None:
    router = RuleBasedRouter()
    req = RouteRequest(
        intent="chat",
        profile=DeviceProfile.HYBRID,
        privacy_level=PrivacyLevel.PRIVATE,
        local_backend_available=True,
        lan_brain_available=True,
    )
    plan = router.route(req)
    assert plan.primary_backend == ROUTE_LOCAL
    assert ROUTE_LAN_BRAIN not in plan.fallback_backends


def test_router_satellite_prefers_lan_brain() -> None:
    router = RuleBasedRouter()
    req = RouteRequest(
        intent="chat",
        profile=DeviceProfile.SATELLITE,
        privacy_level=PrivacyLevel.PUBLIC,
        internet_available=True,
        cloud_allowed=True,
        lan_brain_available=True,
    )
    plan = router.route(req)

    assert plan.primary_backend == ROUTE_LAN_BRAIN
    assert plan.fallback_backends == [ROUTE_CLOUD]
    assert plan.reason_code == "SATELLITE_LAN_PREFERRED"


def test_router_cloud_first_with_local_fallback() -> None:
    router = RuleBasedRouter()
    req = RouteRequest(
        intent="chat",
        profile=DeviceProfile.CLOUD,
        privacy_level=PrivacyLevel.PUBLIC,
        internet_available=True,
        cloud_allowed=True,
        local_backend_available=True,
        lan_brain_available=True,
    )
    plan = router.route(req)

    assert plan.primary_backend == ROUTE_CLOUD
    assert plan.fallback_backends == [ROUTE_LAN_BRAIN, ROUTE_LOCAL]
    assert plan.reason_code == "CLOUD_PROFILE_PREFERRED"


def test_router_cloud_budget_exceeded_fallback() -> None:
    router = RuleBasedRouter()
    req = RouteRequest(
        intent="chat",
        profile=DeviceProfile.HYBRID,
        privacy_level=PrivacyLevel.PUBLIC,
        internet_available=True,
        cloud_allowed=True,
        budget_exceeded=True,
        local_backend_available=True,
    )
    plan = router.route(req)

    # Cloud is blocked due to budget exceeded -> local chosen
    assert plan.primary_backend == ROUTE_LOCAL
    assert ROUTE_CLOUD not in plan.fallback_backends


def test_router_offline_degraded_when_no_backends() -> None:
    router = RuleBasedRouter()
    req = RouteRequest(
        intent="chat",
        profile=DeviceProfile.HYBRID,
        privacy_level=PrivacyLevel.PUBLIC,
        internet_available=False,
        cloud_allowed=False,
        local_backend_available=False,
        lan_brain_available=False,
    )
    plan = router.route(req)

    assert plan.primary_backend == ROUTE_DEGRADED
    assert plan.reason_code == "ALL_BACKENDS_UNAVAILABLE"
