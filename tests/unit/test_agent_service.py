"""Servicio concurrente y cancelable de tareas ADR-014."""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ailen.core.agent_loop import (
    AgentLoop,
    AgentMessage,
    AgentRun,
    AgentRunStatus,
    FinalStep,
    ToolCallStep,
)
from ailen.core.agent_service import AgentService, AgentTaskStatus, _TaskRecord
from ailen.core.confirmation import ConfirmationService
from ailen.domain.enums import SocialMode
from ailen.tools.contracts import ToolContext, ToolResult
from ailen.tools.executor import ToolExecutor
from ailen.tools.fake import FakeVolumeTool
from ailen.tools.registry import ToolRegistry


class ScriptedPlanner:
    def __init__(self, *steps: object) -> None:
        self.steps = list(steps)

    def plan(self, messages: Sequence[AgentMessage]) -> object:
        del messages
        if not self.steps:
            raise AssertionError("scripted planner exhausted")
        return self.steps.pop(0)


class ConfirmableTool(FakeVolumeTool):
    name = "confirmable_volume"
    destructive = False

    def requires_confirmation(self, arguments: dict[str, Any]) -> bool:
        return True


class BlockingTool(FakeVolumeTool):
    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        super().__init__()
        self.started, self.release = started, release

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        self.started.set()
        self.release.wait(1.0)
        return super().execute(validated_args, context)


def _service(
    planner_factory,
    tools: list[Any] | None = None,
    *,
    confirmations: ConfirmationService | None = None,
    **kwargs: Any,
) -> AgentService:
    registry = ToolRegistry(tools or [FakeVolumeTool()])
    executor = ToolExecutor(registry, confirmation_service=confirmations)
    return AgentService(
        lambda cancel: AgentLoop(
            planner_factory(), executor,
            context_factory=lambda: ToolContext(mode=SocialMode.HOME),
            cancel_event=cancel,
        ),
        confirmations or ConfirmationService(),
        confirmation_poll_interval=0.01,
        **kwargs,
    )


def _wait_for(service: AgentService, task_id: str, status: AgentTaskStatus, timeout: float = 1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = service.status(task_id)
        if view is not None and view.status is status:
            return view
        threading.Event().wait(0.005)
    raise AssertionError(f"task {task_id} did not reach {status}")


def test_submit_completa_tarea() -> None:
    service = _service(lambda: ScriptedPlanner(FinalStep("Hecho")))

    handle = service.submit("Saludá", mode=SocialMode.HOME)
    view = _wait_for(service, handle.id, AgentTaskStatus.COMPLETED)

    assert handle.status is AgentTaskStatus.RUNNING
    assert view.summary == "Tarea completada."
    service.shutdown(0.2)


def test_segunda_tarea_se_rechaza_mientras_hay_una_activa() -> None:
    started, release = threading.Event(), threading.Event()

    class WaitingPlanner(ScriptedPlanner):
        def plan(self, messages: Sequence[AgentMessage]) -> object:
            started.set()
            release.wait(1.0)
            return FinalStep("ok")

    service = _service(lambda: WaitingPlanner())
    first = service.submit("Primera", mode=SocialMode.HOME)
    assert started.wait(0.5)
    second = service.submit("Segunda", mode=SocialMode.HOME)

    assert second.status is AgentTaskStatus.REJECTED
    assert second.reason == "Ya hay una tarea del agente en curso."
    release.set()
    _wait_for(service, first.id, AgentTaskStatus.COMPLETED)
    service.shutdown(0.2)


@pytest.mark.parametrize("mode", [SocialMode.SHOP, SocialMode.PUBLIC])
def test_shop_y_public_se_rechazan(mode: SocialMode) -> None:
    service = _service(lambda: ScriptedPlanner(FinalStep("no debe correr")))

    handle = service.submit("Tarea", mode=mode)

    assert handle.status is AgentTaskStatus.REJECTED
    assert handle.reason == "El agente no está disponible en modo SHOP o PUBLIC."
    service.shutdown(0.1)


@pytest.mark.parametrize("task", ["", "   ", "x" * 501])
def test_texto_vacio_o_mayor_a_500_se_rechaza(task: str) -> None:
    service = _service(lambda: ScriptedPlanner(FinalStep("no debe correr")))

    handle = service.submit(task, mode=SocialMode.HOME)

    assert handle.status is AgentTaskStatus.REJECTED
    assert handle.reason == "La tarea debe tener entre 1 y 500 caracteres."
    service.shutdown(0.1)


def test_cancelacion_en_medio_del_tool_detiene_siguientes_pasos() -> None:
    started, release = threading.Event(), threading.Event()
    blocking = BlockingTool(started, release)
    planner = lambda: ScriptedPlanner(
        ToolCallStep("volume", {"level": 20}, "1"), FinalStep("no siguiente")
    )
    service = _service(planner, [blocking])

    handle = service.submit("Ajustá", mode=SocialMode.HOME)
    assert started.wait(0.5)
    assert service.cancel(handle.id)
    assert service.cancel(handle.id)  # idempotente
    release.set()
    view = _wait_for(service, handle.id, AgentTaskStatus.CANCELLED)

    assert view.steps == 1
    service.shutdown(0.2)


def test_confirmacion_aprobada_reanuda_y_completa() -> None:
    confirmations = ConfirmationService(ttl_seconds=1)
    tool = ConfirmableTool()
    service = _service(
        lambda: ScriptedPlanner(
            ToolCallStep("confirmable_volume", {"level": 40}, "1"), FinalStep("ok")
        ),
        [tool], confirmations=confirmations,
    )
    handle = service.submit("Cambiar volumen", mode=SocialMode.HOME)
    pending = _wait_for(service, handle.id, AgentTaskStatus.AWAITING_CONFIRMATION)
    assert pending.confirmation_id
    assert confirmations.resolve(pending.confirmation_id, True, "panel")

    completed = _wait_for(service, handle.id, AgentTaskStatus.COMPLETED)

    assert completed.steps == 2
    assert tool.level == 40
    service.shutdown(0.2)


def test_confirmacion_denegada_termina_sin_ejecutar() -> None:
    confirmations = ConfirmationService(ttl_seconds=1)
    tool = ConfirmableTool()
    service = _service(
        lambda: ScriptedPlanner(ToolCallStep("confirmable_volume", {"level": 10}, "1")),
        [tool], confirmations=confirmations,
    )
    handle = service.submit("Cambiar volumen", mode=SocialMode.HOME)
    pending = _wait_for(service, handle.id, AgentTaskStatus.AWAITING_CONFIRMATION)
    assert pending.confirmation_id
    assert confirmations.resolve(pending.confirmation_id, False, "panel")

    failed = _wait_for(service, handle.id, AgentTaskStatus.FAILED)

    assert failed.summary == "La acción fue denegada por la persona."
    assert tool.level == 80
    service.shutdown(0.2)


def test_confirmacion_vencida_termina_sin_ejecutar() -> None:
    confirmations = ConfirmationService(ttl_seconds=0.06)
    tool = ConfirmableTool()
    service = _service(
        lambda: ScriptedPlanner(ToolCallStep("confirmable_volume", {"level": 10}, "1")),
        [tool], confirmations=confirmations,
    )
    handle = service.submit("Cambiar volumen", mode=SocialMode.HOME)

    failed = _wait_for(service, handle.id, AgentTaskStatus.FAILED)

    assert failed.summary == "La confirmación venció antes de ejecutar la acción."
    assert tool.level == 80
    service.shutdown(0.2)


def test_shutdown_cancela_y_no_deja_hilo_colgado() -> None:
    started = threading.Event()

    class CancelAwarePlanner(ScriptedPlanner):
        def __init__(self, cancel_event: threading.Event) -> None:
            super().__init__()
            self.cancel_event = cancel_event

        def plan(self, messages: Sequence[AgentMessage]) -> object:
            started.set()
            self.cancel_event.wait(1.0)
            return FinalStep("cancelado")

    tool_registry = ToolRegistry([FakeVolumeTool()])
    service = AgentService(
        lambda cancel: AgentLoop(
            CancelAwarePlanner(cancel), ToolExecutor(tool_registry), cancel_event=cancel,
        ),
        ConfirmationService(), confirmation_poll_interval=0.01,
    )
    handle = service.submit("Esperá", mode=SocialMode.HOME)
    assert started.wait(0.5)

    assert service.shutdown(0.3)
    assert service.status(handle.id).status is AgentTaskStatus.CANCELLED


def test_recent_respeta_limite_y_no_expone_argumentos_de_tools() -> None:
    class SecretTool(FakeVolumeTool):
        def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
            return ToolResult(success=True, tool_name=self.name, message="PRIVATE-TOOL-CONTENT")

    tool = SecretTool()
    service = _service(
        lambda: ScriptedPlanner(ToolCallStep("volume", {"level": 33}, "1"), FinalStep("PRIVATE-TOOL-CONTENT")),
        [tool], history_limit=2,
    )

    handles = []
    for index in range(3):
        handle = service.submit(f"Tarea {index}", mode=SocialMode.HOME)
        handles.append(handle)
        _wait_for(service, handle.id, AgentTaskStatus.COMPLETED)

    recent = service.recent()

    assert len(recent) == 2
    assert all("33" not in (view.task + view.summary) for view in recent)
    assert all("PRIVATE-TOOL-CONTENT" not in repr(view) for view in recent)
    service.shutdown(0.2)


def test_run_status_mapea_running_y_vistas_no_lo_tratan_como_terminal() -> None:
    # 1. _RUN_STATUS mapea RUNNING -> AgentTaskStatus.RUNNING
    assert AgentService._RUN_STATUS[AgentRunStatus.RUNNING] is AgentTaskStatus.RUNNING
    assert AgentTaskStatus.RUNNING in AgentService._ACTIVE

    # 2. Estados finales preservados
    final_statuses = {
        AgentRunStatus.COMPLETED: AgentTaskStatus.COMPLETED,
        AgentRunStatus.CANCELLED: AgentTaskStatus.CANCELLED,
        AgentRunStatus.BUDGET_EXCEEDED: AgentTaskStatus.BUDGET_EXCEEDED,
        AgentRunStatus.FAILED: AgentTaskStatus.FAILED,
        AgentRunStatus.AWAITING_CONFIRMATION: AgentTaskStatus.AWAITING_CONFIRMATION,
    }
    for run_st, task_st in final_statuses.items():
        assert AgentService._RUN_STATUS[run_st] is task_st

    # 3. Vista no trata RUNNING como terminal
    record = _TaskRecord(
        id="t-running",
        task="Tarea en progreso",
        status=AgentTaskStatus.RUNNING,
        cancel_event=threading.Event(),
    )
    view = AgentService._view(record)
    assert view.status is AgentTaskStatus.RUNNING
    assert view.summary == "Tarea en curso."


@pytest.mark.parametrize("live_mode", [SocialMode.SHOP, SocialMode.PUBLIC])
def test_modo_context_vivo_shop_o_public_cancela_y_no_ejecuta_herramienta(live_mode: SocialMode) -> None:
    class TrackingTool(FakeVolumeTool):
        def __init__(self) -> None:
            super().__init__()
            self.executed_calls: list[dict[str, Any]] = []

        def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
            self.executed_calls.append(dict(validated_args))
            return super().execute(validated_args, context)

    tool = TrackingTool()
    registry = ToolRegistry([tool])
    executor = ToolExecutor(registry)
    loops: list[AgentLoop] = []

    def make_loop(cancel: threading.Event) -> AgentLoop:
        loop = AgentLoop(
            ScriptedPlanner(ToolCallStep("volume", {"level": 50}, "1"), FinalStep("fin")),
            executor,
            context_factory=lambda: ToolContext(mode=live_mode),
            cancel_event=cancel,
        )
        loops.append(loop)
        return loop

    service = AgentService(make_loop, ConfirmationService(), confirmation_poll_interval=0.01)
    record = _TaskRecord(
        id="t-live-restricted",
        task="Ajustá volumen",
        status=AgentTaskStatus.RUNNING,
        cancel_event=threading.Event(),
    )
    service._tasks[record.id] = record
    service._worker(record, "Ajustá volumen", SocialMode.HOME)

    assert record.status is AgentTaskStatus.CANCELLED
    assert record.cancel_event.is_set()
    assert tool.executed_calls == []
    assert len(loops) == 1
    effective_context = loops[0].context_factory()
    assert effective_context.mode is live_mode


@pytest.mark.parametrize("submitted_mode", [SocialMode.SHOP, SocialMode.PUBLIC])
def test_modo_context_enviado_shop_o_public_cancela_y_no_ejecuta_herramienta(submitted_mode: SocialMode) -> None:
    class TrackingTool(FakeVolumeTool):
        def __init__(self) -> None:
            super().__init__()
            self.executed_calls: list[dict[str, Any]] = []

        def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
            self.executed_calls.append(dict(validated_args))
            return super().execute(validated_args, context)

    tool = TrackingTool()
    registry = ToolRegistry([tool])
    executor = ToolExecutor(registry)
    loops: list[AgentLoop] = []

    def make_loop(cancel: threading.Event) -> AgentLoop:
        loop = AgentLoop(
            ScriptedPlanner(ToolCallStep("volume", {"level": 50}, "1"), FinalStep("fin")),
            executor,
            context_factory=lambda: ToolContext(mode=SocialMode.HOME),
            cancel_event=cancel,
        )
        loops.append(loop)
        return loop

    service = AgentService(make_loop, ConfirmationService(), confirmation_poll_interval=0.01)
    record = _TaskRecord(
        id="t-submitted-restricted",
        task="Ajustá volumen",
        status=AgentTaskStatus.RUNNING,
        cancel_event=threading.Event(),
    )
    service._tasks[record.id] = record
    service._worker(record, "Ajustá volumen", submitted_mode)

    assert record.status is AgentTaskStatus.CANCELLED
    assert record.cancel_event.is_set()
    assert tool.executed_calls == []
    assert len(loops) == 1
    effective_context = loops[0].context_factory()
    assert effective_context.mode is submitted_mode


def test_modo_context_vivo_no_restringido_no_es_pisado_por_enviado() -> None:
    captured_contexts: list[ToolContext] = []

    class ContextInspectingTool(FakeVolumeTool):
        def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
            captured_contexts.append(context)
            return super().execute(validated_args, context)

    tool = ContextInspectingTool()
    registry = ToolRegistry([tool])
    executor = ToolExecutor(registry)
    loops: list[AgentLoop] = []

    def make_loop(cancel: threading.Event) -> AgentLoop:
        loop = AgentLoop(
            ScriptedPlanner(ToolCallStep("volume", {"level": 30}, "1"), FinalStep("fin")),
            executor,
            context_factory=lambda: ToolContext(mode=SocialMode.WORKSHOP),
            cancel_event=cancel,
        )
        loops.append(loop)
        return loop

    service = AgentService(make_loop, ConfirmationService(), confirmation_poll_interval=0.01)
    handle = service.submit("Ajustá volumen", mode=SocialMode.HOME)
    view = _wait_for(service, handle.id, AgentTaskStatus.COMPLETED)

    assert view.status is AgentTaskStatus.COMPLETED
    assert len(captured_contexts) == 1
    assert captured_contexts[0].mode is SocialMode.WORKSHOP
    assert len(loops) == 1
    effective_context = loops[0].context_factory()
    assert effective_context.mode is SocialMode.WORKSHOP
    service.shutdown(0.2)


def test_confirmacion_vencida_con_lock_retenido_no_muta_run() -> None:
    confirmations = ConfirmationService(ttl_seconds=60.0)
    req = confirmations.request("confirmable_volume", {"level": 25})
    # Simula expiración en el snapshot conservando el estado PENDING en la autoridad
    confirmations._requests[req.id] = replace(
        confirmations._requests[req.id],
        expires_at=datetime.now(UTC) - timedelta(seconds=5),
    )

    pending_call = ToolCallStep("confirmable_volume", {"level": 25}, "c1")
    run = AgentRun(
        task="tarea sensible",
        status=AgentRunStatus.AWAITING_CONFIRMATION,
        messages=[],
        started_at=0.0,
        confirmation_id=req.id,
        _pending_call=pending_call,
    )
    service = _service(lambda: ScriptedPlanner(FinalStep("fin")), confirmations=confirmations)
    loop = AgentLoop(ScriptedPlanner(FinalStep("fin")), ToolExecutor(ToolRegistry([])))

    # Otro hilo sostiene el lock: el servicio no muta el run
    assert run._lock.acquire(blocking=False)
    try:
        returned_run = service._wait_for_confirmation(loop, run, req.id, threading.Event())
        assert returned_run is run
        assert run.status is AgentRunStatus.AWAITING_CONFIRMATION
        assert run.confirmation_id == req.id
        assert run._pending_call is pending_call
        assert run.error is None
    finally:
        run._lock.release()

    service.shutdown(0.2)


def test_confirmacion_vencida_sin_lock_termina_failed_y_limpia_pending_call() -> None:
    confirmations = ConfirmationService(ttl_seconds=60.0)
    req = confirmations.request("confirmable_volume", {"level": 25})
    # Simula expiración en el snapshot conservando el estado PENDING en la autoridad
    confirmations._requests[req.id] = replace(
        confirmations._requests[req.id],
        expires_at=datetime.now(UTC) - timedelta(seconds=5),
    )

    pending_call = ToolCallStep("confirmable_volume", {"level": 25}, "c1")
    run = AgentRun(
        task="tarea sensible",
        status=AgentRunStatus.AWAITING_CONFIRMATION,
        messages=[],
        started_at=0.0,
        confirmation_id=req.id,
        _pending_call=pending_call,
    )
    service = _service(lambda: ScriptedPlanner(FinalStep("fin")), confirmations=confirmations)
    loop = AgentLoop(ScriptedPlanner(FinalStep("fin")), ToolExecutor(ToolRegistry([])))

    # Lock libre: el servicio toma el lock, pasa a FAILED y elimina _pending_call
    returned_run = service._wait_for_confirmation(loop, run, req.id, threading.Event())

    assert returned_run is run
    assert run.status is AgentRunStatus.FAILED
    assert run.error == "La confirmación venció antes de ejecutar la acción."
    assert run.confirmation_id is None
    assert run._pending_call is None
    assert not run._lock.locked()
    service.shutdown(0.2)
