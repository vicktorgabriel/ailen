"""Regression tests for the external-only, redacted validation harness."""

from ailen.ai.contracts import (
    AiResponse,
    BackendCapabilities,
    BackendHealth,
)
from ailen.domain.enums import ServiceStatus
from scripts.validate_external_ai import (
    PRIVATE_MARKER,
    _probe_provider,
    _safe_request,
    simulated_fallback_checks,
    synthetic_cases,
)


def test_validation_requests_strip_private_context_before_provider_call() -> None:
    request, passed = _safe_request(
        synthetic_cases()[0],
        timeout_seconds=5.0,
        max_tokens=64,
    )

    serialized = " ".join(
        [request.system_context]
        + [message.content for message in request.messages]
        + request.retrieved_memory
        + [str(request.metadata)]
    )
    assert passed is True
    assert PRIVATE_MARKER not in serialized
    assert len(request.messages) == 1
    assert request.allowed_tools == []


def test_validation_simulates_429_timeout_fallback_and_cooldown() -> None:
    checks = simulated_fallback_checks()

    assert checks == {
        "rate_limit_fallback_passed": True,
        "cooldown_passed": True,
        "timeout_fallback_passed": True,
        "classified_rate_limit": "rate_limit",
        "classified_timeout": "timeout",
    }


def test_validation_separates_ailen_request_from_provider_agent_overhead() -> None:
    class DiagnosticProvider:
        model = "synthetic-model"

        @staticmethod
        def health() -> BackendHealth:
            return BackendHealth(ServiceStatus.HEALTHY, "synthetic")

        @staticmethod
        def capabilities() -> BackendCapabilities:
            return BackendCapabilities(supports_streaming=True)

        @staticmethod
        def generate_stream(request, on_text_delta):  # type: ignore[no-untyped-def]
            on_text_delta("ok")
            return AiResponse(
                text="ok",
                provider="synthetic",
                model="synthetic-model",
                latency_ms=42.0,
                provider_setup_ms=0.4,
                provider_ready_ms=11.0,
                first_text_ms=21.0,
                request_chars=sum(len(message.content) for message in request.messages),
                provider_tool_count=17,
            )

    _summary, records = _probe_provider(
        "remote:diagnostic",
        DiagnosticProvider(),
        synthetic_cases()[:1],
        timeout_seconds=5.0,
        max_tokens=64,
    )

    assert len(records) == 1
    record = records[0]
    assert record.provider_setup_ms == 0.4
    assert record.provider_ready_ms == 11.0
    assert record.request_chars is not None and record.request_chars > 0
    assert record.provider_tool_count == 17


def test_explicit_validation_can_probe_manual_catalog_with_unknown_preflight() -> None:
    class ManualProvider:
        model = "operator-model"

        @staticmethod
        def health() -> BackendHealth:
            return BackendHealth(
                ServiceStatus.UNKNOWN,
                "manual catalog requires explicit inference probe",
            )

        @staticmethod
        def capabilities() -> BackendCapabilities:
            return BackendCapabilities(supports_streaming=True)

        @staticmethod
        def generate_stream(request, on_text_delta):  # type: ignore[no-untyped-def]
            del request
            on_text_delta("ok")
            return AiResponse(
                text="ok",
                provider="remote:manual",
                model="operator-model",
                latency_ms=20.0,
                first_text_ms=10.0,
            )

    summary, records = _probe_provider(
        "remote:manual",
        ManualProvider(),
        synthetic_cases()[:1],
        timeout_seconds=5.0,
        max_tokens=64,
    )

    assert summary["health"] == "UNKNOWN"
    assert len(records) == 1
    assert records[0].streaming_observed is True
