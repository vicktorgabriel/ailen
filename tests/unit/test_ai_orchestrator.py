"""Unit tests for AiOrchestrator."""

from tempfile import TemporaryDirectory
from unittest.mock import Mock

from ailen.ai.contracts import (
    AiErrorKind,
    AiRequest,
    AiResponse,
    AiUsage,
    BackendCapabilities,
    BackendHealth,
    ChatMessage,
    ToolCallRequest,
)
from ailen.ai.fake import FakeAiBackend
from ailen.ai.orchestrator import AiOrchestrator
from ailen.ai.router import RoutePlan
from ailen.core.events import EventBus
from ailen.domain.enums import EventType, PrivacyLevel, ServiceStatus
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.memory.repository import MemoryRepository


def test_orchestrator_executes_primary_backend() -> None:
    fake_local = FakeAiBackend(provider="local_llm", model="test-local")
    orchestrator = AiOrchestrator(backends={"local": fake_local})

    plan = RoutePlan(primary_backend="local", fallback_backends=[])
    req = AiRequest(request_id="req-1", messages=[ChatMessage(role="user", content="Hola")])

    resp, _exec_plan = orchestrator.execute(req, plan=plan)

    assert resp.finish_reason == "stop"
    assert resp.provider == "local_llm"
    assert "Hola" in resp.text


def test_orchestrator_accepts_tool_only_local_response_as_success() -> None:
    local = Mock()
    local.capabilities.return_value = BackendCapabilities(supports_tools=True, is_local=True)
    local.health.return_value = BackendHealth(ServiceStatus.HEALTHY, "ok")
    local.generate.return_value = AiResponse(
        text="",
        tool_calls=[ToolCallRequest("clock", {"format": "time"}, "call-1")],
        finish_reason="tool_calls",
        provider="local",
        model="gpt-oss-20b",
    )
    request = AiRequest(request_id="tool-only", tool_specs=[{"type": "function"}])

    response, _ = AiOrchestrator(backends={"local": local}).execute(
        request, RoutePlan("local")
    )

    assert response.error_kind is None
    assert response.tool_calls[0].call_id == "call-1"


def test_orchestrator_blocks_native_tool_schemas_before_remote_backend() -> None:
    remote = Mock()
    remote.capabilities.return_value = BackendCapabilities(
        supports_tools=True, is_local=False, requires_internet=True,
    )
    remote.health.return_value = BackendHealth(ServiceStatus.HEALTHY, "ok")
    request = AiRequest(
        request_id="private-tools-remote",
        tool_specs=[{"type": "function", "function": {"name": "clock"}}],
        privacy_level=PrivacyLevel.PRIVATE,
    )

    response, _ = AiOrchestrator(backends={"remote:test": remote}).execute(
        request,
        RoutePlan("remote:test", allow_sanitized_external=True),
    )

    assert response.finish_reason == "degraded"
    remote.health.assert_not_called()
    remote.generate.assert_not_called()
    assert response.attempts[0].detail == "privacy_blocked"


def test_orchestrator_fallback_when_primary_fails() -> None:
    # Primary backend is unhealthy / returns error
    failing_primary = FakeAiBackend(
        provider="lan_brain",
        status=ServiceStatus.HEALTHY,
        finish_reason="error",
        canned_response="",
    )
    working_fallback = FakeAiBackend(
        provider="local_llm",
        status=ServiceStatus.HEALTHY,
        finish_reason="stop",
        canned_response="Respuesta desde fallback local",
    )

    orchestrator = AiOrchestrator(
        backends={
            "lan_brain": failing_primary,
            "local": working_fallback,
        }
    )

    plan = RoutePlan(primary_backend="lan_brain", fallback_backends=["local"])
    req = AiRequest(request_id="req-1", messages=[ChatMessage(role="user", content="Hola")])

    resp, _exec_plan = orchestrator.execute(req, plan=plan)

    assert resp.provider == "local_llm"
    assert resp.text == "Respuesta desde fallback local"
    assert resp.finish_reason == "stop"


def test_orchestrator_skips_unhealthy_primary_and_uses_fallback() -> None:
    unhealthy_primary = FakeAiBackend(
        provider="local_llm",
        status=ServiceStatus.UNHEALTHY,
        canned_response="should not run",
    )
    working_fallback = FakeAiBackend(
        provider="lan_brain",
        status=ServiceStatus.HEALTHY,
        canned_response="fallback ok",
    )
    orchestrator = AiOrchestrator(
        backends={"local": unhealthy_primary, "lan_brain": working_fallback}
    )
    req = AiRequest(
        request_id="req-health",
        messages=[ChatMessage(role="user", content="Hola")],
        privacy_level=PrivacyLevel.PUBLIC,
    )
    plan = RoutePlan(primary_backend="local", fallback_backends=["lan_brain"])

    resp, _ = orchestrator.execute(req, plan=plan)
    assert resp.provider == "lan_brain"
    assert resp.text == "fallback ok"


def test_orchestrator_degraded_when_all_fail_and_logs_telemetry() -> None:
    with TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/test_orch.db"
        db_mgr = SQLiteManager(db_path)
        MigrationRunner(db_mgr).run_migrations()
        repo = MemoryRepository(db_mgr)
        bus = EventBus()

        events = []
        bus.subscribe(EventType.INFERENCE_COMPLETED, lambda e: events.append(e))

        working_backend = FakeAiBackend(
            provider="local_llm",
            model="qwen",
            canned_response="Hola mundo",
        )

        orchestrator = AiOrchestrator(
            backends={"local": working_backend},
            repository=repo,
            event_bus=bus,
        )

        plan = RoutePlan(primary_backend="local", fallback_backends=[])
        req = AiRequest(request_id="req-1", messages=[ChatMessage(role="user", content="Hola")])

        resp, _ = orchestrator.execute(req, plan=plan, session_id="sess-1")

        assert resp.text == "Hola mundo"
        assert len(events) == 1

        # Check telemetry logged in SQLite
        in_tok, out_tok, _cost = repo.get_ai_usage_totals()
        assert in_tok > 0
        assert out_tok > 0


def test_orchestrator_does_not_fabricate_unknown_usage() -> None:
    with TemporaryDirectory() as tmpdir:
        db_mgr = SQLiteManager(f"{tmpdir}/unknown_usage.db")
        MigrationRunner(db_mgr).run_migrations()
        repo = MemoryRepository(db_mgr)

        backend = Mock()
        backend.health.return_value = BackendHealth(status=ServiceStatus.HEALTHY, detail="ok")
        backend.generate.return_value = AiResponse(
            text="Respuesta válida",
            provider="unknown-usage-provider",
            model="unknown-usage-model",
            usage=AiUsage(input_tokens=None, output_tokens=None, estimated_cost=None),
        )
        orchestrator = AiOrchestrator(backends={"local": backend}, repository=repo)
        req = AiRequest(request_id="req-unknown", messages=[ChatMessage(role="user", content="Hola")])
        plan = RoutePlan(primary_backend="local")

        resp, _ = orchestrator.execute(req, plan=plan)
        assert resp.text == "Respuesta válida"

        with db_mgr.connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM ai_usage").fetchone()
        assert row["n"] == 0


def test_rate_limit_falls_back_and_activates_provider_cooldown() -> None:
    now = [100.0]
    limited = Mock()
    limited.health.return_value = BackendHealth(ServiceStatus.HEALTHY, "ok")
    limited.generate.return_value = AiResponse(
        text="",
        finish_reason="rate_limited",
        provider="remote:limited",
        model="limited-model",
        error_kind=AiErrorKind.RATE_LIMIT,
        retry_after_seconds=30.0,
    )
    fallback = Mock()
    fallback.health.return_value = BackendHealth(ServiceStatus.HEALTHY, "ok")
    fallback.generate.return_value = AiResponse(
        text="respuesta externa de fallback",
        provider="remote:fallback",
        model="fallback-model",
    )
    orchestrator = AiOrchestrator(
        backends={"remote:limited": limited, "remote:fallback": fallback},
        monotonic_clock=lambda: now[0],
    )
    plan = RoutePlan(
        "remote:limited", ["remote:fallback"], allow_sanitized_external=True
    )
    request = AiRequest(request_id="cooldown", privacy_level=PrivacyLevel.PUBLIC)

    first, _ = orchestrator.execute(request, plan)
    second, _ = orchestrator.execute(request, plan)

    assert first.provider == "remote:fallback"
    assert second.provider == "remote:fallback"
    assert limited.generate.call_count == 1
    assert second.attempts[0].backend == "remote:limited"
    assert second.attempts[0].error_kind is AiErrorKind.RATE_LIMIT
    assert second.attempts[0].outcome == "cooldown"


def test_timeout_fallback_is_classified_and_observable() -> None:
    timed_out = Mock()
    timed_out.health.return_value = BackendHealth(ServiceStatus.HEALTHY, "ok")
    timed_out.generate.return_value = AiResponse(
        text="",
        finish_reason="timeout",
        provider="remote:primary",
        model="primary-model",
        error_kind=AiErrorKind.TIMEOUT,
    )
    fallback = Mock()
    fallback.health.return_value = BackendHealth(ServiceStatus.HEALTHY, "ok")
    fallback.generate.return_value = AiResponse(
        text="ok",
        provider="remote:fallback",
        model="external-model",
    )
    orchestrator = AiOrchestrator(
        backends={"remote:primary": timed_out, "remote:fallback": fallback}
    )

    response, _ = orchestrator.execute(
        AiRequest(request_id="timeout", privacy_level=PrivacyLevel.PUBLIC),
        RoutePlan(
            "remote:primary", ["remote:fallback"], allow_sanitized_external=True
        ),
    )

    assert response.provider == "remote:fallback"
    assert response.attempts[0].error_kind is AiErrorKind.TIMEOUT
    assert response.attempts[1].outcome == "success"


def test_remote_fallback_receives_only_sanitized_current_turn() -> None:
    private_marker = "PRIVATE_FALLBACK_MARKER_8e17"
    local = Mock()
    local.health.return_value = BackendHealth(ServiceStatus.HEALTHY, "ok")
    local.generate.return_value = AiResponse(
        text="",
        finish_reason="timeout",
        provider="local",
        model="local-model",
        error_kind=AiErrorKind.TIMEOUT,
    )
    remote = Mock()
    remote.health.return_value = BackendHealth(ServiceStatus.HEALTHY, "ok")
    remote.generate.return_value = AiResponse(
        text="respuesta externa",
        provider="remote:fallback",
        model="fallback-model",
    )
    request = AiRequest(
        request_id="privacy-fallback",
        system_context=f"persona privada {private_marker}",
        messages=[
            ChatMessage(role="user", content=f"historial {private_marker}"),
            ChatMessage(role="assistant", content=f"respuesta {private_marker}"),
            ChatMessage(role="user", content="turno actual"),
        ],
        retrieved_memory=[f"memoria {private_marker}"],
        privacy_level=PrivacyLevel.PRIVATE,
        metadata={
            "persona_description": private_marker,
            "runtime_context": {"path": f"/home/{private_marker}"},
            "voice_output": True,
        },
    )
    plan = RoutePlan(
        primary_backend="local",
        fallback_backends=["remote:fallback"],
        allow_sanitized_external=True,
    )

    response, _ = AiOrchestrator(
        backends={"local": local, "remote:fallback": remote}
    ).execute(request, plan)

    assert response.provider == "remote:fallback"
    outbound = remote.generate.call_args.args[0]
    serialized = " ".join(
        [outbound.system_context]
        + [message.content for message in outbound.messages]
        + outbound.retrieved_memory
        + [str(outbound.metadata)]
    )
    assert private_marker not in serialized
    assert [message.content for message in outbound.messages] == ["turno actual"]
    assert outbound.retrieved_memory == []
    assert request.system_context == f"persona privada {private_marker}"


def test_private_remote_fallback_is_blocked_without_sanitized_opt_in() -> None:
    local = Mock()
    local.health.return_value = BackendHealth(ServiceStatus.HEALTHY, "ok")
    local.generate.return_value = AiResponse(
        text="",
        finish_reason="timeout",
        error_kind=AiErrorKind.TIMEOUT,
    )
    remote = Mock()
    remote.health.return_value = BackendHealth(ServiceStatus.HEALTHY, "ok")
    remote.generate.return_value = AiResponse(text="should not run")
    request = AiRequest(
        request_id="privacy-block",
        messages=[ChatMessage(role="user", content="turno privado")],
        privacy_level=PrivacyLevel.PRIVATE,
    )

    response, _ = AiOrchestrator(
        backends={"local": local, "remote:fallback": remote}
    ).execute(request, RoutePlan("local", ["remote:fallback"]))

    assert response.finish_reason == "degraded"
    remote.health.assert_not_called()
    remote.generate.assert_not_called()
    assert response.attempts[-1].detail == "privacy_blocked"


def test_provider_specific_timeout_caps_generic_request_timeout() -> None:
    backend = Mock()
    backend.timeout_seconds = 3.0
    backend.health.return_value = BackendHealth(ServiceStatus.HEALTHY, "ok")
    backend.generate.return_value = AiResponse(
        text="ok",
        provider="remote:primary",
        model="primary-model",
    )
    request = AiRequest(
        request_id="provider-timeout",
        messages=[ChatMessage(role="user", content="hola")],
        timeout_seconds=60.0,
        privacy_level=PrivacyLevel.PUBLIC,
    )

    AiOrchestrator(backends={"remote:primary": backend}).execute(
        request,
        RoutePlan("remote:primary", allow_sanitized_external=True),
    )

    outbound = backend.generate.call_args.args[0]
    assert outbound.timeout_seconds == 3.0


def test_all_unhealthy_external_providers_degrade_honestly() -> None:
    unavailable = Mock()
    unavailable.health.return_value = BackendHealth(
        ServiceStatus.UNHEALTHY, "synthetic outage"
    )
    response, _ = AiOrchestrator(
        backends={"remote:primary": unavailable}
    ).execute(
        AiRequest(request_id="all-down", privacy_level=PrivacyLevel.PUBLIC),
        RoutePlan("remote:primary", allow_sanitized_external=True),
    )

    assert response.provider == "system"
    assert response.model == "degraded"
    assert response.finish_reason == "degraded"
    assert "no está disponible" in response.text
    unavailable.generate.assert_not_called()


def test_streaming_health_exception_is_observable_and_uses_fallback() -> None:
    broken = Mock(spec=["health", "capabilities", "generate"])
    broken.health.side_effect = RuntimeError("synthetic health bug")
    fallback = FakeAiBackend(
        provider="remote:fallback",
        model="fallback-model",
        canned_response="fallback visible",
    )
    deltas: list[str] = []

    response, _ = AiOrchestrator(
        backends={"remote:primary": broken, "remote:fallback": fallback}
    ).execute_stream_until(
        AiRequest(request_id="stream-health", privacy_level=PrivacyLevel.PUBLIC),
        RoutePlan(
            "remote:primary", ["remote:fallback"], allow_sanitized_external=True
        ),
        lambda text: deltas.append(text),
    )

    assert response.provider == "remote:fallback"
    assert deltas == ["fallback visible"]
    assert response.attempts[0].backend == "remote:primary"
    assert response.attempts[0].error_kind is AiErrorKind.INTERNAL_ERROR
    assert response.attempts[1].outcome == "success"


def test_streaming_never_splices_fallback_response_after_visible_partial_output() -> None:
    from ailen.ai.contracts import BackendCapabilities, BackendHealth, StreamingAiBackend

    class PartialFailure(StreamingAiBackend):
        def health(self):  # type: ignore[no-untyped-def]
            return BackendHealth(ServiceStatus.HEALTHY, "ok")

        def capabilities(self):  # type: ignore[no-untyped-def]
            return BackendCapabilities(supports_streaming=True)

        def generate_stream(self, request, on_text_delta):  # type: ignore[no-untyped-def]
            del request
            on_text_delta("respuesta parcial")
            return AiResponse(
                text="respuesta parcial",
                provider="primary",
                model="broken-stream",
                finish_reason="error",
                error_kind=AiErrorKind.NETWORK,
            )

    fallback = FakeAiBackend(canned_response="respuesta de fallback")
    fallback.generate = Mock(side_effect=fallback.generate)
    deltas: list[str] = []

    response, _ = AiOrchestrator(
        backends={"local": PartialFailure(), "cloud": fallback}
    ).execute_stream_until(
        AiRequest(request_id="partial", privacy_level=PrivacyLevel.PUBLIC),
        RoutePlan("local", ["cloud"]),
        lambda delta: deltas.append(delta),
    )

    assert deltas == ["respuesta parcial"]
    assert response.finish_reason == "partial_stream_error"
    fallback.generate.assert_not_called()
