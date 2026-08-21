"""AI Execution Orchestrator for AILEN.

Coordinates sequential execution of RoutePlan backends with fallback recovery,
telemetry logging, and budget/health verification.
"""

import logging
from typing import Any

from ailen.ai.contracts import AiBackend, AiRequest, AiResponse
from ailen.ai.router import ROUTE_DEGRADED, ROUTE_RULE_ONLY, RoutePlan, RuleBasedRouter
from ailen.core.events import EventBus
from ailen.domain.enums import EventType, ServiceStatus
from ailen.memory.repository import MemoryRepository

logger = logging.getLogger("ailen.ai.orchestrator")


class AiOrchestrator:
    """Orchestrates AI inference attempts across registered backends."""

    def __init__(
        self,
        backends: dict[str, AiBackend] | None = None,
        router: RuleBasedRouter | None = None,
        repository: MemoryRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.backends: dict[str, AiBackend] = backends or {}
        self.router = router or RuleBasedRouter()
        self.repository = repository
        self.event_bus = event_bus

    def register_backend(self, name: str, backend: AiBackend) -> None:
        """Register an inference backend by route name."""
        self.backends[name.lower().strip()] = backend

    def execute(
        self,
        request: AiRequest,
        plan: RoutePlan,
        session_id: str | None = None,
    ) -> tuple[AiResponse, RoutePlan]:
        """Execute inference following RoutePlan sequence with automatic fallback."""
        # 1. Rule-only path
        if plan.primary_backend == ROUTE_RULE_ONLY:
            rule_resp = AiResponse(
                text="",
                finish_reason="rule_executed",
                provider="rule_engine",
                model="deterministic",
            )
            self._publish_event(
                EventType.INTENT_RESOLVED,
                {"action": "rule_intent_routed", "reason": plan.reason_code},
            )
            return rule_resp, plan

        # 2. Degraded plan (no backends available)
        if plan.primary_backend == ROUTE_DEGRADED:
            return self._build_degraded_response(plan.reason_code), plan

        # 3. Build candidate backend sequence: primary -> fallbacks
        candidates = [plan.primary_backend] + list(plan.fallback_backends)
        attempt_errors: list[dict[str, Any]] = []

        for candidate_name in candidates:
            backend = self.backends.get(candidate_name)
            if not backend:
                attempt_errors.append({"backend": candidate_name, "error": "not_registered"})
                continue

            # Check health. Only HEALTHY/DEGRADED backends are eligible for inference.
            health = backend.health()
            if health.status not in {ServiceStatus.HEALTHY, ServiceStatus.DEGRADED}:
                attempt_errors.append(
                    {
                        "backend": candidate_name,
                        "error": f"health_{health.status.value.lower()}",
                    }
                )
                continue

            # Attempt inference
            try:
                response = backend.generate(request)
            except Exception as e:  # noqa: BLE001
                logger.warning("Backend %s raised unexpected error: %s", candidate_name, e)
                attempt_errors.append({"backend": candidate_name, "error": str(e)})
                continue

            # Check response success
            if response.finish_reason not in ("error", "unreachable", "timeout", "malformed_response") and response.text:
                # Persist usage only when the provider actually reported enough data.
                # Unknown token/cost fields must remain unknown rather than being fabricated as zero.
                usage = response.usage
                if (
                    self.repository
                    and usage.input_tokens is not None
                    and usage.output_tokens is not None
                    and usage.estimated_cost is not None
                ):
                    try:
                        self.repository.log_ai_usage(
                            provider=response.provider,
                            model=response.model,
                            input_tokens=usage.input_tokens,
                            output_tokens=usage.output_tokens,
                            estimated_cost=usage.estimated_cost,
                            latency_ms=response.latency_ms,
                            session_id=session_id,
                        )
                    except Exception as e:  # noqa: BLE001
                        logger.debug("Failed to log AI usage to database: %s", e)

                # Publish success event
                self._publish_event(
                    EventType.INFERENCE_COMPLETED,
                    {
                        "provider": response.provider,
                        "model": response.model,
                        "latency_ms": response.latency_ms,
                        "finish_reason": response.finish_reason,
                    },
                )
                return response, plan

            attempt_errors.append({"backend": candidate_name, "error": response.finish_reason})

        # 4. All backends failed -> return clean degraded response
        logger.info("All AI backends failed in RoutePlan: %s", attempt_errors)
        self._publish_event(
            EventType.ERROR,
            {"attempts": attempt_errors, "reason": plan.reason_code},
        )
        return self._build_degraded_response(f"ALL_FAILED: {attempt_errors}"), plan

    def _build_degraded_response(self, detail: str) -> AiResponse:
        """Create a safe, user-friendly degraded response."""
        return AiResponse(
            text="La inteligencia conversacional no está disponible en este momento.",
            finish_reason="degraded",
            provider="system",
            model="degraded",
        )

    def _publish_event(self, event_type: EventType, payload: dict[str, Any]) -> None:
        """Publish lightweight domain event if EventBus is attached."""
        if self.event_bus:
            try:
                self.event_bus.create_and_publish(
                    event_type=event_type,
                    source="ai_orchestrator",
                    payload=payload,
                )
            except Exception as e:  # noqa: BLE001
                logger.debug("Failed to publish event %s: %s", event_type, e)
