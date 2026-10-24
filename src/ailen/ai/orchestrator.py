"""AI Execution Orchestrator for AILEN.

Coordinates sequential execution of RoutePlan backends with fallback recovery,
telemetry logging, and budget/health verification.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from ailen.ai.contracts import (
    AiAttempt,
    AiBackend,
    AiErrorKind,
    AiRequest,
    AiResponse,
    StreamingAiBackend,
)
from ailen.ai.privacy import OutboundPrivacyPolicy
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
        monotonic_clock: Callable[[], float] | None = None,
        rate_limit_cooldown_seconds: float = 60.0,
    ) -> None:
        self.backends: dict[str, AiBackend] = backends or {}
        self.router = router or RuleBasedRouter()
        self.repository = repository
        self.event_bus = event_bus
        self._monotonic = monotonic_clock or time.monotonic
        self._rate_limit_cooldown_seconds = max(1.0, rate_limit_cooldown_seconds)
        self._cooldown_until: dict[str, float] = {}

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
        attempts: list[AiAttempt] = []

        for candidate_name in candidates:
            cooldown_until = self._cooldown_until.get(candidate_name, 0.0)
            if cooldown_until > self._monotonic():
                attempts.append(
                    AiAttempt(
                        backend=candidate_name,
                        outcome="cooldown",
                        error_kind=AiErrorKind.RATE_LIMIT,
                        detail=f"retry_in_seconds={cooldown_until - self._monotonic():.1f}",
                    )
                )
                continue
            backend = self.backends.get(candidate_name)
            if not backend:
                attempts.append(
                    AiAttempt(
                        backend=candidate_name,
                        outcome="failed",
                        error_kind=AiErrorKind.UNAVAILABLE,
                        detail="not_registered",
                    )
                )
                continue

            try:
                candidate_request = OutboundPrivacyPolicy.sanitize_request_for_destination(
                    request,
                    destination=candidate_name,
                    lan_trusted=plan.lan_trusted,
                    allow_sanitized_private=plan.allow_sanitized_external,
                )
                candidate_request = self._with_backend_timeout(candidate_request, backend)
            except PermissionError:
                attempts.append(
                    AiAttempt(
                        backend=candidate_name,
                        outcome="blocked",
                        error_kind=AiErrorKind.UNAVAILABLE,
                        detail="privacy_blocked",
                    )
                )
                continue

            if request.tool_specs:
                try:
                    capabilities = backend.capabilities()
                except Exception as exc:  # noqa: BLE001
                    attempts.append(AiAttempt(
                        backend=candidate_name,
                        outcome="failed",
                        error_kind=AiErrorKind.INTERNAL_ERROR,
                        detail=f"capabilities_{type(exc).__name__}",
                    ))
                    continue
                if not capabilities.is_local or not capabilities.supports_tools:
                    attempts.append(AiAttempt(
                        backend=candidate_name,
                        outcome="blocked",
                        error_kind=AiErrorKind.UNAVAILABLE,
                        detail="native_tools_not_supported_locally",
                    ))
                    continue

            # Check health. Only HEALTHY/DEGRADED backends are eligible for inference.
            try:
                health = backend.health()
            except Exception as exc:
                logger.exception("Backend %s health check raised", candidate_name)
                attempts.append(
                    AiAttempt(
                        backend=candidate_name,
                        outcome="failed",
                        error_kind=AiErrorKind.INTERNAL_ERROR,
                        detail=type(exc).__name__,
                    )
                )
                continue
            if health.status not in {ServiceStatus.HEALTHY, ServiceStatus.DEGRADED}:
                attempts.append(
                    AiAttempt(
                        backend=candidate_name,
                        outcome="failed",
                        error_kind=AiErrorKind.UNAVAILABLE,
                        detail=f"health_{health.status.value.lower()}",
                    )
                )
                continue

            # Attempt inference
            try:
                response = backend.generate(candidate_request)
            except Exception as e:
                logger.exception("Backend %s raised unexpected error", candidate_name)
                attempts.append(
                    AiAttempt(
                        backend=candidate_name,
                        outcome="failed",
                        error_kind=AiErrorKind.INTERNAL_ERROR,
                        detail=type(e).__name__,
                    )
                )
                continue

            # Check response success
            success = self._is_success(response)
            attempts.append(
                AiAttempt(
                    backend=candidate_name,
                    outcome="success" if success else "failed",
                    provider=response.provider,
                    model=response.model,
                    latency_ms=response.latency_ms,
                    error_kind=response.error_kind,
                    detail=response.finish_reason,
                )
            )
            if success:
                response.attempts = list(attempts)
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

            if (
                response.error_kind is AiErrorKind.RATE_LIMIT
                or response.finish_reason == "rate_limited"
            ):
                requested = response.retry_after_seconds
                cooldown = self._rate_limit_cooldown_seconds if requested is None else requested
                # A hostile or malformed Retry-After must not disable a provider forever.
                cooldown = min(300.0, max(1.0, cooldown))
                self._cooldown_until[candidate_name] = self._monotonic() + cooldown

        # 4. All backends failed -> return clean degraded response
        attempt_payload = [self._attempt_payload(item) for item in attempts]
        logger.info("All AI backends failed in RoutePlan: %s", attempt_payload)
        self._publish_event(
            EventType.ERROR,
            {"attempts": attempt_payload, "reason": plan.reason_code},
        )
        return self._build_degraded_response(
            f"ALL_FAILED: {attempt_payload}", attempts=attempts
        ), plan

    def execute_stream_until(
        self,
        request: AiRequest,
        plan: RoutePlan,
        on_text_delta: Callable[[str], bool | None],
        session_id: str | None = None,
    ) -> tuple[AiResponse, RoutePlan]:
        """Execute a route incrementally when the selected backend supports streaming."""
        def tracking_callback(parts: list[str]) -> Callable[[str], bool | None]:
            def track(delta: str) -> bool | None:
                parts.append(delta)
                return on_text_delta(delta)

            return track

        candidates = [plan.primary_backend] + list(plan.fallback_backends)
        attempts: list[AiAttempt] = []
        for candidate_name in candidates:
            cooldown_until = self._cooldown_until.get(candidate_name, 0.0)
            if cooldown_until > self._monotonic():
                attempts.append(
                    AiAttempt(
                        backend=candidate_name,
                        outcome="cooldown",
                        error_kind=AiErrorKind.RATE_LIMIT,
                    )
                )
                continue
            backend = self.backends.get(candidate_name)
            if backend is None:
                attempts.append(
                    AiAttempt(
                        backend=candidate_name,
                        outcome="failed",
                        error_kind=AiErrorKind.UNAVAILABLE,
                        detail="not_registered",
                    )
                )
                continue
            try:
                candidate_request = OutboundPrivacyPolicy.sanitize_request_for_destination(
                    request,
                    destination=candidate_name,
                    lan_trusted=plan.lan_trusted,
                    allow_sanitized_private=plan.allow_sanitized_external,
                )
                candidate_request = self._with_backend_timeout(candidate_request, backend)
            except PermissionError:
                attempts.append(
                    AiAttempt(
                        backend=candidate_name,
                        outcome="blocked",
                        error_kind=AiErrorKind.UNAVAILABLE,
                        detail="privacy_blocked",
                    )
                )
                continue
            if request.tool_specs:
                try:
                    capabilities = backend.capabilities()
                except Exception as exc:  # noqa: BLE001
                    attempts.append(AiAttempt(
                        backend=candidate_name,
                        outcome="failed",
                        error_kind=AiErrorKind.INTERNAL_ERROR,
                        detail=f"capabilities_{type(exc).__name__}",
                    ))
                    continue
                if not capabilities.is_local or not capabilities.supports_tools:
                    attempts.append(AiAttempt(
                        backend=candidate_name,
                        outcome="blocked",
                        error_kind=AiErrorKind.UNAVAILABLE,
                        detail="native_tools_not_supported_locally",
                    ))
                    continue
            try:
                health = backend.health()
            except Exception as exc:
                logger.exception("Streaming backend %s health check raised", candidate_name)
                attempts.append(
                    AiAttempt(
                        backend=candidate_name,
                        outcome="failed",
                        error_kind=AiErrorKind.INTERNAL_ERROR,
                        detail=type(exc).__name__,
                    )
                )
                continue
            if health.status not in {ServiceStatus.HEALTHY, ServiceStatus.DEGRADED}:
                attempts.append(
                    AiAttempt(
                        backend=candidate_name,
                        outcome="failed",
                        error_kind=AiErrorKind.UNAVAILABLE,
                        detail=f"health_{health.status.value.lower()}",
                    )
                )
                continue
            emitted_parts: list[str] = []
            track_delta = tracking_callback(emitted_parts)

            try:
                if (
                    isinstance(backend, StreamingAiBackend)
                    and backend.capabilities().supports_streaming
                ):
                    response = backend.generate_stream(candidate_request, track_delta)
                else:
                    response = backend.generate(candidate_request)
                    if response.text:
                        track_delta(response.text)
            except Exception as exc:
                logger.exception("Streaming backend %s failed", candidate_name)
                attempts.append(
                    AiAttempt(
                        backend=candidate_name,
                        outcome="failed",
                        error_kind=AiErrorKind.INTERNAL_ERROR,
                        detail=type(exc).__name__,
                    )
                )
                if emitted_parts:
                    return AiResponse(
                        text="".join(emitted_parts).strip(),
                        provider=candidate_name,
                        model=str(getattr(backend, "model", "unknown")),
                        finish_reason="partial_stream_error",
                        error_kind=AiErrorKind.INTERNAL_ERROR,
                        attempts=list(attempts),
                    ), plan
                continue
            success = self._is_success(response)
            attempts.append(
                AiAttempt(
                    backend=candidate_name,
                    outcome="success" if success else "failed",
                    provider=response.provider,
                    model=response.model,
                    latency_ms=response.latency_ms,
                    error_kind=response.error_kind,
                    detail=response.finish_reason,
                )
            )
            if success:
                response.attempts = list(attempts)
                self._publish_event(
                    EventType.INFERENCE_COMPLETED,
                    {
                        "provider": response.provider,
                        "model": response.model,
                        "latency_ms": response.latency_ms,
                        "finish_reason": response.finish_reason,
                        "streaming": True,
                    },
                )
                return response, plan
            if emitted_parts:
                # Once text may already be audible, trying another provider
                # would splice two independent answers into one voice turn.
                response.finish_reason = "partial_stream_error"
                response.attempts = list(attempts)
                return response, plan
            if response.error_kind is AiErrorKind.RATE_LIMIT:
                cooldown = response.retry_after_seconds or self._rate_limit_cooldown_seconds
                self._cooldown_until[candidate_name] = self._monotonic() + min(
                    300.0, max(1.0, cooldown)
                )
        return self._build_degraded_response(
            "STREAM_ALL_FAILED", attempts=attempts
        ), plan

    @staticmethod
    def _is_success(response: AiResponse) -> bool:
        return bool(response.text or response.tool_calls) and response.error_kind is None and response.finish_reason not in {
            "empty_response",
            "error",
            "malformed_response",
            "rate_limited",
            "timeout",
            "unreachable",
        }

    @staticmethod
    def _with_backend_timeout(request: AiRequest, backend: AiBackend) -> AiRequest:
        """Bound a request by the adapter's configured timeout when available."""
        configured = getattr(backend, "timeout_seconds", None)
        if not isinstance(configured, (int, float)) or configured <= 0:
            return request
        request_timeout = request.timeout_seconds
        effective = configured if request_timeout <= 0 else min(request_timeout, configured)
        return replace(request, timeout_seconds=float(effective))

    @staticmethod
    def _attempt_payload(attempt: AiAttempt) -> dict[str, Any]:
        return {
            "backend": attempt.backend,
            "outcome": attempt.outcome,
            "provider": attempt.provider,
            "model": attempt.model,
            "latency_ms": attempt.latency_ms,
            "error_kind": attempt.error_kind.value if attempt.error_kind else None,
            "detail": attempt.detail,
        }

    def _build_degraded_response(
        self,
        detail: str,
        attempts: list[AiAttempt] | None = None,
    ) -> AiResponse:
        """Create a safe, user-friendly degraded response."""
        return AiResponse(
            text="La inteligencia conversacional no está disponible en este momento.",
            finish_reason="degraded",
            provider="system",
            model="degraded",
            error_kind=AiErrorKind.UNAVAILABLE,
            attempts=list(attempts or []),
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
