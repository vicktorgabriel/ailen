"""Servicio concurrente y cancelable de tareas ADR-014."""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from typing import Any

import pytest

from ailen.core.agent_loop import AgentLoop, AgentMessage, FinalStep, ToolCallStep
from ailen.core.agent_service import AgentService, AgentTaskStatus
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
    assert all("33" not in repr(view) for view in recent)
    assert all("PRIVATE-TOOL-CONTENT" not in repr(view) for view in recent)
    service.shutdown(0.2)
