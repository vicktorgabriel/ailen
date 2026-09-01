"""Deterministic capability routing for local, LAN and named remote AI backends."""

from __future__ import annotations

from dataclasses import dataclass, field

from ailen.ai.privacy import OutboundPrivacyPolicy
from ailen.domain.enums import DeviceProfile, PrivacyLevel

ROUTE_RULE_ONLY = "rule"
ROUTE_LOCAL = "local"
ROUTE_LAN_BRAIN = "lan_brain"
ROUTE_DEGRADED = "degraded"
REMOTE_ROUTE_PREFIX = "remote:"


def is_remote_route(backend: str) -> bool:
    """Return whether an observable backend ID represents a remote provider."""

    return backend.startswith(REMOTE_ROUTE_PREFIX) and len(backend) > len(
        REMOTE_ROUTE_PREFIX
    )


@dataclass
class RouteRequest:
    """Inputs for one auditable routing decision."""

    intent: str = "chat"
    complexity: str = "low"
    profile: DeviceProfile = DeviceProfile.HYBRID
    privacy_level: PrivacyLevel = PrivacyLevel.PRIVATE
    internet_available: bool = False
    lan_brain_available: bool = False
    lan_brain_trusted: bool = False
    local_backend_available: bool = False
    external_allowed: bool = False
    allow_sanitized_external_prompts: bool = False
    remote_backends: tuple[str, ...] = ()
    budget_blocked_backends: frozenset[str] = frozenset()
    latency_preference: str = "normal"
    input_modality: str = "text"
    preferred_backend: str = ""
    backend_priorities: dict[str, int] = field(default_factory=dict)
    backend_timeouts: dict[str, float] = field(default_factory=dict)
    realtime_eligible_backends: dict[str, bool] = field(default_factory=dict)
    acoustic_confidence: float | None = None
    utterance_interrupted: bool = False
    utterance_truncated: bool = False


@dataclass
class RoutePlan:
    """Ordered backend execution plan."""

    primary_backend: str
    fallback_backends: list[str] = field(default_factory=list)
    reason_code: str = "UNSPECIFIED"
    context_budget: int = 2048
    request_timeout: float = 10.0
    privacy_decision: str = "ALLOWED"
    estimated_remote_allowance: bool = False
    allow_sanitized_external: bool = False
    lan_trusted: bool = False


RULE_ONLY_INTENTS: frozenset[str] = frozenset(
    {
        "volume",
        "playback",
        "timer",
        "clock",
        "mode_change",
        "system_status",
        "animation",
        "notes",
        "pause",
        "resume",
        "next_track",
        "stop_music",
    }
)


def classify_fast_path_intent(text: str) -> str | None:
    """Classify only unequivocal local commands; ambiguous language stays chat."""

    if not text:
        return None
    clean = " ".join(text.lower().strip().split()).strip(" ¿?¡!.,;:")
    if clean in {
        "qué hora es",
        "que hora es",
        "decime la hora",
        "dime la hora",
        "hora actual",
        "qué hora tenemos",
        "que hora tenemos",
    }:
        return "clock"
    if any(
        marker in clean
        for marker in (
            "poné un temporizador",
            "pone un temporizador",
            "pon un temporizador",
            "iniciá un temporizador",
            "inicia un temporizador",
            "creá un temporizador",
            "crea un temporizador",
            "configurá un temporizador",
            "configura un temporizador",
            "poné una alarma",
            "pone una alarma",
            "pon una alarma",
        )
    ):
        return "timer"
    if clean in {
        "mute",
        "silencio",
        "subí el volumen",
        "sube el volumen",
        "subir volumen",
        "bajá el volumen",
        "baja el volumen",
        "bajar volumen",
    } or any(
        clean.startswith(prefix)
        for prefix in (
            "subí el volumen ",
            "sube el volumen ",
            "bajá el volumen ",
            "baja el volumen ",
            "poné el volumen ",
            "pone el volumen ",
            "pon el volumen ",
        )
    ):
        return "volume"
    if clean in {
        "pausá la música",
        "pausa la música",
        "reanuda la música",
        "reanudá la música",
        "seguí la música",
        "sigue la música",
        "siguiente canción",
        "siguiente tema",
        "pará la música",
        "para la música",
        "detené la música",
        "deten la música",
        "poné música",
        "pone música",
        "pon música",
        "pausar música",
        "reanudar música",
    }:
        return "playback"
    if clean in {
        "estado del sistema",
        "cómo está el sistema",
        "como está el sistema",
        "como esta el sistema",
        "diagnóstico del sistema",
        "diagnostico del sistema",
        "estado de la batería",
        "estado de la bateria",
        "cuánta batería queda",
        "cuanta bateria queda",
    }:
        return "system_status"
    if any(
        clean.startswith(prefix)
        for prefix in (
            "anotá ",
            "anota ",
            "anotar ",
            "tomá nota ",
            "toma nota ",
            "guardá una nota ",
            "guarda una nota ",
            "creá una nota ",
            "crea una nota ",
        )
    ):
        return "notes"
    return None


class RuleBasedRouter:
    """Choose capability groups first and priorities only within/fallback groups."""

    def route(self, request: RouteRequest) -> RoutePlan:
        if request.intent in RULE_ONLY_INTENTS:
            return RoutePlan(
                primary_backend=ROUTE_RULE_ONLY,
                reason_code="RULE_ONLY_INTENT",
                context_budget=0,
                request_timeout=2.0,
                privacy_decision="LOCAL_RULE_ONLY",
            )

        remote_privacy_allowed, _ = OutboundPrivacyPolicy.is_destination_allowed(
            request.privacy_level,
            f"{REMOTE_ROUTE_PREFIX}provider",
        )
        sanitized_remote = (
            request.privacy_level is PrivacyLevel.PRIVATE
            and request.allow_sanitized_external_prompts
        )
        can_use_remote = remote_privacy_allowed or sanitized_remote
        remotes = self._eligible_remotes(request) if can_use_remote else []

        lan_allowed, _ = OutboundPrivacyPolicy.is_destination_allowed(
            request.privacy_level,
            ROUTE_LAN_BRAIN,
            lan_trusted=request.lan_brain_trusted,
        )
        local = [ROUTE_LOCAL] if request.local_backend_available else []
        lan = [ROUTE_LAN_BRAIN] if request.lan_brain_available and lan_allowed else []

        explicit = request.preferred_backend.strip().lower()
        available = [*local, *lan, *remotes]
        if explicit not in {"", "auto"} and explicit in available:
            fallbacks = self._sort_by_priority(
                [backend for backend in available if backend != explicit], request
            )
            return self._build_plan(
                [explicit, *fallbacks],
                request,
                reason=f"CONFIGURED_{explicit.upper()}_PREFERRED",
                sanitized_remote=sanitized_remote,
            )

        realtime_remotes = [
            backend
            for backend in remotes
            if request.realtime_eligible_backends.get(backend, False)
        ]
        deferred_remotes = [backend for backend in remotes if backend not in realtime_remotes]

        if request.input_modality == "voice" and request.complexity != "high":
            ordered = [*local, *lan, *realtime_remotes]
            if ordered:
                ordered.extend(deferred_remotes)
                return self._build_plan(
                    ordered,
                    request,
                    reason="AUTO_VOICE_LOW_LATENCY",
                    sanitized_remote=sanitized_remote,
                )
            if deferred_remotes:
                return self._degraded("NO_REALTIME_VOICE_BACKEND", request)

        if request.profile is DeviceProfile.SATELLITE:
            ordered = [*lan, *local, *remotes]
            reason = "SATELLITE_LAN_PREFERRED" if lan else "SATELLITE_FALLBACK"
        elif request.profile is DeviceProfile.CLOUD:
            ordered = [*remotes, *lan, *local]
            reason = "REMOTE_PROFILE_PREFERRED"
        elif request.profile in {DeviceProfile.LOCAL, DeviceProfile.LAN_BRAIN}:
            ordered = [*local, *lan, *remotes]
            reason = "LOCAL_PROFILE_PREFERRED" if local else "LOCAL_PROFILE_FALLBACK"
        elif request.complexity == "high" or request.latency_preference == "relaxed":
            ordered = [*remotes, *lan, *local]
            reason = "AUTO_CAPABILITY_ESCALATION"
        elif request.complexity == "low" or request.latency_preference == "low":
            ordered = [*local, *lan, *remotes]
            reason = (
                "HYBRID_LOCAL_PREFERRED"
                if local
                else "HYBRID_LAN_PREFERRED"
                if lan
                else "AUTO_REMOTE_ONLY"
            )
        else:
            ordered = [*remotes, *lan, *local]
            reason = "AUTO_REMOTE_CAPABLE" if remotes else "HYBRID_FALLBACK"

        if not ordered:
            return self._degraded(self._missing_reason(request, can_use_remote), request)
        return self._build_plan(
            ordered,
            request,
            reason=reason,
            sanitized_remote=sanitized_remote,
        )

    @staticmethod
    def _eligible_remotes(request: RouteRequest) -> list[str]:
        if not request.internet_available or not request.external_allowed:
            return []
        unique = {
            backend
            for backend in request.remote_backends
            if is_remote_route(backend)
            and backend not in request.budget_blocked_backends
        }
        return sorted(
            unique,
            key=lambda backend: (request.backend_priorities.get(backend, 100), backend),
        )

    @staticmethod
    def _sort_by_priority(candidates: list[str], request: RouteRequest) -> list[str]:
        defaults = {ROUTE_LAN_BRAIN: 40, ROUTE_LOCAL: 50}
        return sorted(
            candidates,
            key=lambda backend: (
                request.backend_priorities.get(backend, defaults.get(backend, 100)),
                backend,
            ),
        )

    @staticmethod
    def _build_plan(
        ordered: list[str],
        request: RouteRequest,
        *,
        reason: str,
        sanitized_remote: bool,
    ) -> RoutePlan:
        ordered = list(dict.fromkeys(ordered))
        primary = ordered[0]
        remote = is_remote_route(primary)
        return RoutePlan(
            primary_backend=primary,
            fallback_backends=ordered[1:],
            reason_code=reason,
            context_budget=2048 if primary == ROUTE_LOCAL else 4096,
            request_timeout=request.backend_timeouts.get(
                primary, 15.0 if primary == ROUTE_LAN_BRAIN else 10.0
            ),
            privacy_decision=(
                "SANITIZED_REMOTE_CURRENT_TURN_ONLY"
                if remote and sanitized_remote
                else "ALLOWED"
            ),
            estimated_remote_allowance=remote,
            allow_sanitized_external=sanitized_remote,
            lan_trusted=request.lan_brain_trusted,
        )

    @staticmethod
    def _degraded(reason: str, request: RouteRequest) -> RoutePlan:
        return RoutePlan(
            primary_backend=ROUTE_DEGRADED,
            reason_code=reason,
            context_budget=0,
            request_timeout=0.0,
            privacy_decision="DEGRADED",
            lan_trusted=request.lan_brain_trusted,
        )

    @staticmethod
    def _missing_reason(request: RouteRequest, remote_privacy_allowed: bool) -> str:
        if request.remote_backends and not remote_privacy_allowed:
            return "PRIVATE_REMOTE_BLOCKED"
        if not request.internet_available and not (
            request.local_backend_available or request.lan_brain_available
        ):
            return "ALL_BACKENDS_UNAVAILABLE"
        if request.remote_backends and set(request.remote_backends).issubset(
            request.budget_blocked_backends
        ):
            return "REMOTE_BUDGET_EXCEEDED"
        return "NO_BACKEND_AVAILABLE"
