"""AI routing contracts and rule-based deterministic router for AILEN.

The Router decides backend execution order. Core never selects model names directly.
See docs/architecture/MODULE_CONTRACTS.md section 6 and ADR-003.
"""

from dataclasses import dataclass, field

from ailen.ai.privacy import OutboundPrivacyPolicy
from ailen.domain.enums import DeviceProfile, PrivacyLevel

# Canonical backend identifiers
ROUTE_RULE_ONLY: str = "rule"
ROUTE_LOCAL: str = "local"
ROUTE_LAN_BRAIN: str = "lan_brain"
ROUTE_CLOUD: str = "cloud"
ROUTE_DEGRADED: str = "degraded"


@dataclass
class RouteRequest:
    """Input for the AI routing decision."""

    intent: str = "chat"
    complexity: str = "low"  # "low", "medium", "high"
    profile: DeviceProfile = DeviceProfile.HYBRID
    privacy_level: PrivacyLevel = PrivacyLevel.PRIVATE
    internet_available: bool = False
    lan_brain_available: bool = False
    lan_brain_trusted: bool = False
    local_backend_available: bool = False
    cloud_allowed: bool = False
    budget_exceeded: bool = False
    latency_preference: str = "normal"  # "low", "normal", "relaxed"
    preferred_backend: str = ""  # explicit deployment preference: local/lan_brain/cloud


@dataclass
class RoutePlan:
    """Output of the deterministic routing decision."""

    primary_backend: str  # "rule", "local", "lan_brain", "cloud", "degraded"
    fallback_backends: list[str] = field(default_factory=list)
    reason_code: str = "UNSPECIFIED"
    context_budget: int = 2048
    request_timeout: float = 10.0
    privacy_decision: str = "ALLOWED"
    estimated_remote_allowance: bool = False


# Intents that MUST NEVER call an LLM (PRODUCT_BEHAVIOR.md section 9).
RULE_ONLY_INTENTS: frozenset[str] = frozenset({
    "volume",
    "playback",
    "timer",
    "clock",
    "greeting",
    "mode_change",
    "system_status",
    "animation",
    "notes",
    "pause",
    "resume",
    "next_track",
    "stop_music",
})


def classify_fast_path_intent(text: str) -> str | None:
    """Classify only unequivocal local commands; ambiguous language stays in chat.

    This classifier is preparatory for R3C tool execution and is intentionally
    conservative: false negatives cost one LLM turn, while false positives could
    execute the wrong local action.
    """
    if not text:
        return None
    clean = " ".join(text.lower().strip().split()).strip(" ¿?¡!.,;:")

    clock_phrases = {
        "qué hora es", "que hora es", "decime la hora", "dime la hora",
        "hora actual", "qué hora tenemos", "que hora tenemos",
    }
    if clean in clock_phrases:
        return "clock"

    if any(
        marker in clean
        for marker in (
            "poné un temporizador", "pone un temporizador", "pon un temporizador",
            "iniciá un temporizador", "inicia un temporizador",
            "creá un temporizador", "crea un temporizador",
            "configurá un temporizador", "configura un temporizador",
            "poné una alarma", "pone una alarma", "pon una alarma",
        )
    ):
        return "timer"

    if (
        clean in {
            "mute", "silencio", "subí el volumen", "sube el volumen", "subir volumen",
            "bajá el volumen", "baja el volumen", "bajar volumen",
        }
        or any(clean.startswith(prefix) for prefix in (
            "subí el volumen ", "sube el volumen ", "bajá el volumen ", "baja el volumen ",
            "poné el volumen ", "pone el volumen ", "pon el volumen ",
        ))
    ):
        return "volume"

    playback_phrases = {
        "pausá la música", "pausa la música", "reanuda la música", "reanudá la música",
        "seguí la música", "sigue la música", "siguiente canción", "siguiente tema",
        "pará la música", "para la música", "detené la música", "deten la música",
        "poné música", "pone música", "pon música", "pausar música", "reanudar música",
    }
    if clean in playback_phrases:
        return "playback"

    if clean in {
        "estado del sistema", "cómo está el sistema", "como está el sistema",
        "como esta el sistema", "diagnóstico del sistema", "diagnostico del sistema",
        "estado de la batería", "estado de la bateria", "cuánta batería queda",
        "cuanta bateria queda",
    }:
        return "system_status"

    if any(clean.startswith(prefix) for prefix in (
        "anotá ", "anota ", "anotar ", "tomá nota ", "toma nota ",
        "guardá una nota ", "guarda una nota ", "creá una nota ", "crea una nota ",
    )):
        return "notes"

    return None


class RuleBasedRouter:
    """Deterministic routing. No LLM used for routing; clear, auditable decision rules."""

    def route(self, request: RouteRequest) -> RoutePlan:
        """Compute an ordered execution plan for the incoming request."""
        # 1. Rule-Only Fast Path
        if request.intent in RULE_ONLY_INTENTS:
            return RoutePlan(
                primary_backend=ROUTE_RULE_ONLY,
                fallback_backends=[],
                reason_code="RULE_ONLY_INTENT",
                context_budget=0,
                request_timeout=2.0,
                privacy_decision="LOCAL_RULE_ONLY",
                estimated_remote_allowance=False,
            )

        # 2. Check outbound privacy restrictions for remote backends
        cloud_permitted, _cloud_privacy_reason = OutboundPrivacyPolicy.is_destination_allowed(
            request.privacy_level,
            ROUTE_CLOUD,
        )

        lan_permitted, _lan_privacy_reason = OutboundPrivacyPolicy.is_destination_allowed(
            request.privacy_level,
            ROUTE_LAN_BRAIN,
            lan_trusted=request.lan_brain_trusted,
        )

        # 3. Check Cloud availability & budget constraints
        can_use_cloud = (
            request.internet_available
            and request.cloud_allowed
            and cloud_permitted
            and not request.budget_exceeded
        )

        can_use_lan = request.lan_brain_available and lan_permitted
        can_use_local = request.local_backend_available

        preferred_plan = self._route_preferred_backend(
            request,
            can_use_local=can_use_local,
            can_use_lan=can_use_lan,
            can_use_cloud=can_use_cloud,
        )
        if preferred_plan is not None:
            return preferred_plan

        # 4. Route by DeviceProfile
        if request.profile == DeviceProfile.SATELLITE:
            return self._route_satellite(request, can_use_lan, can_use_cloud, cloud_permitted)

        if request.profile == DeviceProfile.CLOUD:
            return self._route_cloud_first(request, can_use_cloud, can_use_lan, can_use_local, cloud_permitted)

        if request.profile == DeviceProfile.LOCAL:
            return self._route_local_first(request, can_use_local, can_use_lan, can_use_cloud, cloud_permitted)

        if request.profile == DeviceProfile.LAN_BRAIN:
            return self._route_lan_brain_node(request, can_use_local)

        # Default: HYBRID Profile
        return self._route_hybrid(
            request,
            can_use_local,
            can_use_lan,
            can_use_cloud,
            cloud_permitted,
        )

    def _route_preferred_backend(
        self,
        request: RouteRequest,
        *,
        can_use_local: bool,
        can_use_lan: bool,
        can_use_cloud: bool,
    ) -> RoutePlan | None:
        """Honor an explicit deployment backend preference when it is currently usable."""
        preferred = request.preferred_backend.strip().lower()
        available = {
            ROUTE_LOCAL: can_use_local,
            ROUTE_LAN_BRAIN: can_use_lan,
            ROUTE_CLOUD: can_use_cloud,
        }
        if preferred not in available or not available[preferred]:
            return None

        ordered = [preferred]
        for candidate in (ROUTE_LOCAL, ROUTE_LAN_BRAIN, ROUTE_CLOUD):
            if candidate != preferred and available[candidate]:
                ordered.append(candidate)
        return RoutePlan(
            primary_backend=ordered[0],
            fallback_backends=ordered[1:],
            reason_code=f"CONFIGURED_{preferred.upper()}_PREFERRED",
            context_budget=4096 if preferred != ROUTE_LOCAL else 2048,
            request_timeout=15.0 if preferred == ROUTE_LAN_BRAIN else 10.0,
            privacy_decision="ALLOWED",
            estimated_remote_allowance=preferred == ROUTE_CLOUD,
        )

    # -------------------------------------------------------------------------
    # Profile Routing Strategies
    # -------------------------------------------------------------------------

    def _route_satellite(
        self,
        request: RouteRequest,
        can_use_lan: bool,
        can_use_cloud: bool,
        cloud_permitted: bool,
    ) -> RoutePlan:
        """Satellite profile: prefers LAN Brain, fallbacks to Cloud if allowed."""
        plan: list[str] = []
        if can_use_lan:
            plan.append(ROUTE_LAN_BRAIN)
        if can_use_cloud:
            plan.append(ROUTE_CLOUD)

        if not plan:
            reason = self._diagnose_missing_reason(request, cloud_permitted)
            return RoutePlan(ROUTE_DEGRADED, [], reason, 0, 2.0, "DEGRADED", False)

        primary, fallbacks = plan[0], plan[1:]
        reason = "SATELLITE_LAN_PREFERRED" if primary == ROUTE_LAN_BRAIN else "SATELLITE_CLOUD_FALLBACK"
        timeout = 15.0 if primary == ROUTE_LAN_BRAIN else 10.0
        return RoutePlan(primary, fallbacks, reason, 2048, timeout, "ALLOWED", primary == ROUTE_CLOUD)

    def _route_cloud_first(
        self,
        request: RouteRequest,
        can_use_cloud: bool,
        can_use_lan: bool,
        can_use_local: bool,
        cloud_permitted: bool,
    ) -> RoutePlan:
        """Cloud profile: prefers Cloud for chat, fallbacks to LAN/Local."""
        plan: list[str] = []
        if can_use_cloud:
            plan.append(ROUTE_CLOUD)
        if can_use_lan:
            plan.append(ROUTE_LAN_BRAIN)
        if can_use_local:
            plan.append(ROUTE_LOCAL)

        if not plan:
            reason = self._diagnose_missing_reason(request, cloud_permitted)
            return RoutePlan(ROUTE_DEGRADED, [], reason, 0, 2.0, "DEGRADED", False)

        primary, fallbacks = plan[0], plan[1:]
        reason = "CLOUD_PROFILE_PREFERRED" if primary == ROUTE_CLOUD else f"CLOUD_FALLBACK_{primary.upper()}"
        return RoutePlan(primary, fallbacks, reason, 4096, 10.0, "ALLOWED", primary == ROUTE_CLOUD)

    def _route_local_first(
        self,
        request: RouteRequest,
        can_use_local: bool,
        can_use_lan: bool,
        can_use_cloud: bool,
        cloud_permitted: bool,
    ) -> RoutePlan:
        """Local profile: prefers Local execution, fallbacks to LAN Brain."""
        plan: list[str] = []
        if can_use_local:
            plan.append(ROUTE_LOCAL)
        if can_use_lan:
            plan.append(ROUTE_LAN_BRAIN)
        if can_use_cloud and request.cloud_allowed:
            plan.append(ROUTE_CLOUD)

        if not plan:
            reason = self._diagnose_missing_reason(request, cloud_permitted)
            return RoutePlan(ROUTE_DEGRADED, [], reason, 0, 2.0, "DEGRADED", False)

        primary, fallbacks = plan[0], plan[1:]
        reason = "LOCAL_PROFILE_PREFERRED" if primary == ROUTE_LOCAL else f"LOCAL_FALLBACK_{primary.upper()}"
        timeout = 20.0 if primary == ROUTE_LOCAL else 15.0
        return RoutePlan(primary, fallbacks, reason, 2048, timeout, "ALLOWED", primary == ROUTE_CLOUD)

    def _route_lan_brain_node(self, request: RouteRequest, can_use_local: bool) -> RoutePlan:
        """LAN Brain profile: operates primarily as local server."""
        if can_use_local:
            return RoutePlan(ROUTE_LOCAL, [], "LAN_BRAIN_LOCAL_NODE", 4096, 20.0, "ALLOWED", False)
        return RoutePlan(ROUTE_DEGRADED, [], "LOCAL_UNAVAILABLE", 0, 2.0, "DEGRADED", False)

    def _route_hybrid(
        self,
        request: RouteRequest,
        can_use_local: bool,
        can_use_lan: bool,
        can_use_cloud: bool,
        cloud_permitted: bool,
    ) -> RoutePlan:
        """Hybrid profile: balances local privacy/speed with cloud capabilities."""
        # A. Private or Restricted Privacy Level -> NEVER Cloud
        if not cloud_permitted:
            plan: list[str] = []
            if can_use_local:
                plan.append(ROUTE_LOCAL)
            if can_use_lan:
                plan.append(ROUTE_LAN_BRAIN)

            if not plan:
                reason = "PRIVATE_REMOTE_BLOCKED" if request.privacy_level is PrivacyLevel.PRIVATE else "RESTRICTED_CLOUD_BLOCKED"
                if not request.local_backend_available and not request.lan_brain_available:
                    reason = "PRIVATE_LOCAL_UNAVAILABLE"
                return RoutePlan(ROUTE_DEGRADED, [], reason, 0, 2.0, "PRIVACY_BLOCKED", False)

            primary, fallbacks = plan[0], plan[1:]
            reason = "PRIVACY_LOCAL_ONLY" if primary == ROUTE_LOCAL else "PRIVACY_LAN_BRAIN"
            return RoutePlan(primary, fallbacks, reason, 2048, 15.0, "LOCAL_RESTRICTED", False)

        # B. Public Privacy Level
        plan = []
        # Low latency preference or low complexity: try local first
        if request.latency_preference == "low" or request.complexity == "low":
            if can_use_local:
                plan.append(ROUTE_LOCAL)
            if can_use_lan:
                plan.append(ROUTE_LAN_BRAIN)
            if can_use_cloud:
                plan.append(ROUTE_CLOUD)
        else:
            # High complexity or normal: try cloud first if available, then LAN, then Local
            if can_use_cloud:
                plan.append(ROUTE_CLOUD)
            if can_use_lan:
                plan.append(ROUTE_LAN_BRAIN)
            if can_use_local:
                plan.append(ROUTE_LOCAL)

        if not plan:
            reason = self._diagnose_missing_reason(request, cloud_permitted)
            return RoutePlan(ROUTE_DEGRADED, [], reason, 0, 2.0, "DEGRADED", False)

        primary, fallbacks = plan[0], plan[1:]
        if primary == ROUTE_CLOUD:
            reason = "CLOUD_FAST_PATH"
        elif primary == ROUTE_LOCAL:
            reason = "HYBRID_LOCAL_PREFERRED"
        else:
            reason = "HYBRID_LAN_PREFERRED"

        return RoutePlan(primary, fallbacks, reason, 4096, 10.0, "ALLOWED", primary == ROUTE_CLOUD)

    def _diagnose_missing_reason(self, request: RouteRequest, cloud_permitted: bool) -> str:
        """Produce precise diagnostic reason code when no backends are available."""
        if not cloud_permitted:
            return "PRIVATE_REMOTE_BLOCKED"
        if request.budget_exceeded:
            return "CLOUD_BUDGET_EXCEEDED"
        if not request.internet_available and not request.local_backend_available and not request.lan_brain_available:
            return "ALL_BACKENDS_UNAVAILABLE"
        if not request.local_backend_available:
            return "LOCAL_UNAVAILABLE"
        if not request.lan_brain_available:
            return "LAN_UNAVAILABLE"
        return "NO_BACKEND_AVAILABLE"
