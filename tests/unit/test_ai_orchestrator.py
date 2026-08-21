"""Unit tests for AiOrchestrator."""

from tempfile import TemporaryDirectory
from unittest.mock import Mock

from ailen.ai.contracts import AiRequest, AiResponse, AiUsage, BackendHealth, ChatMessage
from ailen.ai.fake import FakeAiBackend
from ailen.ai.orchestrator import AiOrchestrator
from ailen.ai.router import RoutePlan
from ailen.core.events import EventBus
from ailen.domain.enums import EventType, ServiceStatus
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
    req = AiRequest(request_id="req-health", messages=[ChatMessage(role="user", content="Hola")])
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
