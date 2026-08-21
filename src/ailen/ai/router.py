"""AI routing contracts and rule-based router for AILEN.

El Router decide el backend; Core nunca selecciona nombres de modelos.
Ver docs/architecture/MODULE_CONTRACTS.md sección 6.
"""

from dataclasses import dataclass, field

from ailen.domain.enums import DeviceProfile, PrivacyLevel


@dataclass
class RouteRequest:
    """Input for the AI routing decision."""
    intent: str = "chat"
    complexity: str = "low"  # "low", "medium", "high"
    profile: DeviceProfile = DeviceProfile.HYBRID
    privacy_level: PrivacyLevel = PrivacyLevel.PRIVATE
    internet_available: bool = False
    lan_brain_available: bool = False
    local_backend_available: bool = False
    cloud_allowed: bool = False
    budget_exceeded: bool = False
    latency_preference: str = "normal"  # "low", "normal", "relaxed"


@dataclass
class RoutePlan:
    """Output of the routing decision."""
    primary_backend: str  # "rule", "local", "lan_brain", "cloud"
    fallback_backends: list[str] = field(default_factory=list)
    reason_code: str = "UNSPECIFIED"
    context_budget: int = 2048
    request_timeout: float = 10.0


# Intents que nunca deben usar LLM (PRODUCT_BEHAVIOR.md sección 9).
RULE_ONLY_INTENTS: frozenset[str] = frozenset({
    "volume", "playback", "timer", "clock", "greeting",
    "mode_change", "system_status", "animation",
})


class RuleBasedRouter:
    """Deterministic routing. Sin LLM para decidir; reglas claras y registrables."""

    def route(self, request: RouteRequest) -> RoutePlan:
        """Decide backend order for a request."""
        if request.intent in RULE_ONLY_INTENTS:
            return RoutePlan(
                primary_backend="rule",
                fallback_backends=[],
                reason_code="RULE_ONLY_INTENT",
                context_budget=0,
                request_timeout=2.0,
            )

        if request.privacy_level is PrivacyLevel.PRIVATE:
            # Privacidad estricta: nunca cloud aunque esté disponible.
            return self._private_route(request)
        return self._standard_route(request)

    def _private_route(self, request: RouteRequest) -> RoutePlan:
        fallbacks: list[str] = []
        if request.local_backend_available:
            if request.lan_brain_available:
                fallbacks.append("lan_brain")
            return RoutePlan("local", fallbacks, "PRIVACY_LOCAL_ONLY", 2048, 15.0)
        if request.lan_brain_available:
            return RoutePlan("lan_brain", [], "PRIVACY_LAN_BRAIN", 4096, 15.0)
        return RoutePlan("rule", [], "PRIVACY_NO_BACKEND", 0, 2.0)

    def _standard_route(self, request: RouteRequest) -> RoutePlan:
        plan: list[str] = []
        if request.latency_preference != "low" and request.local_backend_available:
            plan.append("local")
        if request.lan_brain_available:
            plan.append("lan_brain")
        if request.internet_available and request.cloud_allowed and not request.budget_exceeded:
            plan.append("cloud")
        if request.latency_preference == "low" and request.local_backend_available:
            plan.insert(0, "local")

        if not plan:
            return RoutePlan("rule", [], "NO_BACKEND_AVAILABLE", 0, 2.0)

        primary, fallbacks = plan[0], plan[1:]
        reason = f"ORDER_{primary.upper()}_FIRST"
        if primary == "cloud" and request.budget_exceeded is False:
            reason = "CLOUD_ALLOWED_WITHIN_BUDGET" if len(plan) == 1 else reason
        return RoutePlan(primary, fallbacks, reason, 4096, 10.0)
