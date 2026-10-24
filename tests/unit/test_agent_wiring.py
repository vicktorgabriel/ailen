"""Integration checks for the explicit Core-agent voice hook and Lab wiring."""

import threading
import time
from unittest.mock import MagicMock

from ailen.ai.context import AiContextBuilder
from ailen.ai.fake import FakeAiBackend
from ailen.ai.orchestrator import AiOrchestrator
from ailen.ai.router import RuleBasedRouter
from ailen.audio.contracts import Transcript
from ailen.core.agent_service import AgentTaskHandle, AgentTaskStatus, AgentTaskView
from ailen.core.config import AILENConfig
from ailen.core.confirmation import ConfirmationService, ConfirmationState
from ailen.core.conversation import ConversationCoordinator
from ailen.domain.enums import DeviceProfile, SocialMode
from ailen.runtime.runner import LabRunner


class _AgentServiceStub:
    def __init__(self, confirmations: ConfirmationService) -> None:
        self.confirmations = confirmations
        self.submitted: list[tuple[str, SocialMode]] = []
        self.cancelled: list[str] = []
        self.views: tuple[AgentTaskView, ...] = ()

    def submit(self, task: str, *, mode: SocialMode) -> AgentTaskHandle:
        self.submitted.append((task, mode))
        return AgentTaskHandle("task-1", AgentTaskStatus.RUNNING)

    def recent(self) -> tuple[AgentTaskView, ...]:
        return self.views

    def cancel(self, task_id: str) -> bool:
        self.cancelled.append(task_id)
        return True


def _runner_for_handler() -> tuple[LabRunner, _AgentServiceStub, ConfirmationService]:
    config = AILENConfig()
    confirmations = ConfirmationService()
    service = _AgentServiceStub(confirmations)
    runner = LabRunner(config=config, dry_run=True, no_ai=True)
    runner.confirmation_service = confirmations
    runner.agent_service = service
    return runner, service, confirmations


def _conversation(handler=None):
    backend = FakeAiBackend(canned_response="Respuesta normal.")
    backend.generate = MagicMock(side_effect=backend.generate)
    audio = MagicMock()
    router = RuleBasedRouter()
    coordinator = ConversationCoordinator(
        context_builder=AiContextBuilder(),
        router=router,
        orchestrator=AiOrchestrator(backends={"local": backend}, router=router),
        audio_coordinator=audio,
        profile=DeviceProfile.LOCAL,
        mode=SocialMode.WORKSHOP,
        agent_command_handler=handler,
    )
    return coordinator, backend, audio


def test_agent_disabled_by_default_and_enabled_by_level_or_roots(tmp_path) -> None:
    default = LabRunner(
        config=AILENConfig(), dry_run=True, simulate=True, no_camera=True, no_audio=True
    )
    default.inspect_and_plan()
    default.init_components()
    assert default.agent_service is None

    enabled_config = AILENConfig()
    enabled_config.agent.max_autonomy_level = 2
    enabled_config.agent.file_roots = [str(tmp_path)]
    enabled = LabRunner(
        config=enabled_config, dry_run=True, simulate=True, no_camera=True, no_audio=True
    )
    enabled.inspect_and_plan()
    enabled.init_components()
    assert enabled.agent_service is not None
    assert enabled.confirmation_service is not None
    assert enabled.tool_executor is not None
    assert enabled.agent_service is not None
    loop = enabled.agent_service._loop_factory(threading.Event())
    enabled.interaction_coordinator.set_mode(SocialMode.HOME)
    assert loop.context_factory().mode is SocialMode.HOME
    assert int(loop.context_factory().max_autonomy) == 2
    assert "files" in enabled._agent_tool_filter()

    n2_only_config = AILENConfig()
    n2_only_config.agent.max_autonomy_level = 2
    n2_only = LabRunner(
        config=n2_only_config, dry_run=True, simulate=True, no_camera=True, no_audio=True
    )
    n2_only.inspect_and_plan()
    n2_only.init_components()
    assert n2_only.agent_service is not None

    roots_only_config = AILENConfig()
    roots_only_config.agent.file_roots = [str(tmp_path)]
    roots_only = LabRunner(
        config=roots_only_config, dry_run=True, simulate=True, no_camera=True, no_audio=True
    )
    roots_only.inspect_and_plan()
    roots_only.init_components()
    assert roots_only.agent_service is not None
    assert "files" not in roots_only._agent_tool_filter()


def test_voice_agent_submit_and_cancel_use_live_social_mode() -> None:
    runner, service, _confirmations = _runner_for_handler()
    transcript = Transcript(text="Agente, ordená la carpeta", confidence=0.94)

    assert runner._handle_agent_command(transcript, transcript.text) == "Entendido, trabajando en eso."
    assert service.submitted == [("ordená la carpeta", SocialMode.WORKSHOP)]

    service.views = (
        AgentTaskView("task-1", "ordená", AgentTaskStatus.RUNNING, 0, None, "Tarea en curso."),
    )
    assert runner._handle_agent_command(Transcript(text="cancelá la tarea"), "cancelá la tarea") == "Tarea cancelada."
    assert service.cancelled == ["task-1"]


def test_low_confidence_or_truncated_agent_submit_is_not_started() -> None:
    for confidence, truncated in ((0.4, False), (0.95, True), (None, False)):
        runner, service, _confirmations = _runner_for_handler()
        transcript = Transcript(
            text="Agente, borrá el informe", confidence=confidence, truncated=truncated
        )

        response = runner._handle_agent_command(transcript, transcript.text)

        assert response is not None and "repetirla" in response
        assert service.submitted == []


def test_voice_confirmation_uses_actual_confidence_and_truncation() -> None:
    for confidence, truncated, expected in (
        (0.91, False, True),
        (0.5, False, False),
        (0.95, True, False),
        (None, False, False),
    ):
        runner, service, confirmations = _runner_for_handler()
        request = confirmations.request("files", {"action": "delete"}, summary="Borrar informe.txt")
        service.views = (
            AgentTaskView(
                "task-1", "borrar", AgentTaskStatus.AWAITING_CONFIRMATION,
                1, request.id, "Esperando confirmación humana.",
            ),
        )
        runner._announced_agent_confirmations[request.id] = time.monotonic()
        transcript = Transcript(text="confirmo", confidence=confidence, truncated=truncated)
        spoken = runner._handle_agent_command(transcript, transcript.text)
        state = confirmations.status(request.id).state

        assert (state is ConfirmationState.APPROVED) is expected
        if expected:
            assert spoken == "Confirmación recibida; sigo con la tarea."
        else:
            assert "Repetí" in spoken or "panel" in spoken


def test_explicit_agent_command_without_handler_keeps_normal_llm_flow() -> None:
    coordinator, backend, _audio = _conversation()

    response, _plan = coordinator.handle_transcript(
        Transcript(text="Agente, ordená la carpeta", confidence=0.95)
    )

    assert response.text == "Respuesta normal."
    backend.generate.assert_called_once()


def test_explicit_agent_command_with_handler_preempts_llm_and_speaks() -> None:
    handler = MagicMock(return_value="Entendido, trabajando en eso.")
    coordinator, backend, audio = _conversation(handler)
    transcript = Transcript(text="Agente, ordená la carpeta", confidence=0.95)

    response, plan = coordinator.handle_transcript(transcript)

    assert response.text == "Entendido, trabajando en eso."
    assert response.finish_reason == "agent_command"
    assert plan.reason_code == "AGENT_COMMAND"
    backend.generate.assert_not_called()
    handler.assert_called_once_with(transcript, transcript.text)
    audio.speak.assert_called_once()
    assert audio.speak.call_args.args == ("Entendido, trabajando en eso.",)
    assert audio.speak.call_args.kwargs["emotion"] == "neutral"
    assert audio.speak.call_args.kwargs["voice_id"] == "es_ES-standard"


def test_voice_denial_resolves_confirmation_without_approving() -> None:
    runner, service, confirmations = _runner_for_handler()
    request = confirmations.request("files", {"action": "delete"}, summary="Borrar informe.txt")
    service.views = (
        AgentTaskView(
            "task-1", "borrar", AgentTaskStatus.AWAITING_CONFIRMATION,
            1, request.id, "Esperando confirmación humana.",
        ),
    )
    runner._announced_agent_confirmations[request.id] = time.monotonic()

    spoken = runner._handle_agent_command(
        Transcript(text="denegá", confidence=0.9), "denegá"
    )

    assert spoken == "Tarea cancelada."
    assert confirmations.status(request.id).state is ConfirmationState.DENIED


def test_pending_confirmation_is_announced_from_safe_summary_when_audio_is_free() -> None:
    runner, service, confirmations = _runner_for_handler()
    request = confirmations.request("files", {"action": "overwrite"}, summary="Sobrescribir notas.txt")
    view = AgentTaskView(
        "task-1", "editar", AgentTaskStatus.AWAITING_CONFIRMATION,
        1, request.id, "Esperando confirmación humana.",
    )
    service.views = (view,)
    runner.audio_coordinator = MagicMock()
    runner.audio_coordinator.last_speech_interrupted = False

    runner._on_agent_task_event("TASK_AWAITING_CONFIRMATION", view)
    queued_id, queued_summary = runner._pending_agent_confirmation_announcements.get_nowait()
    runner._announce_agent_confirmation(queued_id, queued_summary)

    spoken = runner.audio_coordinator.speak.call_args.args[0]
    assert "Necesito tu confirmación para Sobrescribir notas.txt" in spoken
    assert "usá el panel" in spoken
    assert runner._queued_agent_confirmation_ids == set()
    assert request.id in runner._announced_agent_confirmations


def test_runner_shutdown_cancels_agent_service_with_bounded_join(tmp_path) -> None:
    runner = LabRunner(config=AILENConfig(), dry_run=True, log_dir=tmp_path)
    service = MagicMock()
    service.shutdown.return_value = True
    runner.agent_service = service
    runner.config.ai.timeout_seconds = 5.0
    runner._is_running = True
    announcement_thread = MagicMock()
    runner._agent_announcement_thread = announcement_thread

    runner.stop()

    service.shutdown.assert_called_once_with(timeout=6.0)
    announcement_thread.join.assert_called_once_with(timeout=6.0)
    assert runner.agent_service is None


def test_agent_shutdown_wait_is_capped_at_fifteen_seconds(tmp_path) -> None:
    runner = LabRunner(config=AILENConfig(), dry_run=True, log_dir=tmp_path)
    service = MagicMock()
    service.shutdown.return_value = True
    runner.agent_service = service
    runner.config.ai.timeout_seconds = 90.0
    runner._is_running = True

    runner.stop()

    service.shutdown.assert_called_once_with(timeout=15.0)


def test_runner_does_not_finalize_repository_if_agent_worker_did_not_join(tmp_path) -> None:
    runner = LabRunner(config=AILENConfig(), dry_run=True, log_dir=tmp_path)
    service = MagicMock()
    service.shutdown.return_value = False
    runner.agent_service = service
    repository = MagicMock()
    runner.memory_repo = repository
    runner._conversation_session_id = "session-1"
    runner._is_running = True

    runner.stop()

    service.shutdown.assert_called_once_with(timeout=11.0)
    repository.end_session.assert_not_called()


def test_unannounced_or_expired_confirmation_cannot_be_resolved_by_voice() -> None:
    runner, service, confirmations = _runner_for_handler()
    request = confirmations.request("files", {"action": "delete"}, summary="Borrar informe.txt")
    service.views = (
        AgentTaskView(
            "task-1", "borrar", AgentTaskStatus.AWAITING_CONFIRMATION,
            1, request.id, "Esperando confirmación humana.",
        ),
    )
    transcript = Transcript(text="confirmo", confidence=0.99)

    assert "nada pendiente" in runner._handle_agent_command(transcript, transcript.text).lower()
    assert confirmations.status(request.id).state is ConfirmationState.PENDING

    runner._announced_agent_confirmations[request.id] = time.monotonic() - 61.0
    assert "nada pendiente" in runner._handle_agent_command(transcript, transcript.text).lower()
    assert confirmations.status(request.id).state is ConfirmationState.PENDING


def test_voice_confirmation_uses_only_announced_awaiting_tasks_and_asks_panel_if_ambiguous() -> None:
    runner, service, confirmations = _runner_for_handler()
    first = confirmations.request("files", {"action": "delete", "path": "a"}, summary="Borrar a")
    second = confirmations.request("files", {"action": "delete", "path": "b"}, summary="Borrar b")
    service.views = (
        AgentTaskView("running", "otra", AgentTaskStatus.RUNNING, 0, None, "En curso"),
        AgentTaskView("task-1", "borrar a", AgentTaskStatus.AWAITING_CONFIRMATION, 1, first.id, "Esperando"),
        AgentTaskView("task-2", "borrar b", AgentTaskStatus.AWAITING_CONFIRMATION, 1, second.id, "Esperando"),
    )
    now = time.monotonic()
    runner._announced_agent_confirmations[first.id] = now
    runner._announced_agent_confirmations[second.id] = now

    spoken = runner._handle_agent_command(
        Transcript(text="confirmo", confidence=0.99), "confirmo"
    )

    assert "panel" in spoken.lower()
    assert confirmations.status(first.id).state is ConfirmationState.PENDING
    assert confirmations.status(second.id).state is ConfirmationState.PENDING


def test_agent_voice_commands_are_blocked_in_shop_and_public_and_autonomy_is_n1() -> None:
    for mode in (SocialMode.SHOP, SocialMode.PUBLIC):
        runner, service, confirmations = _runner_for_handler()
        runner.interaction_coordinator = MagicMock(mode=mode)
        request = confirmations.request("files", {"action": "delete"}, summary="Borrar informe")
        service.views = (
            AgentTaskView(
                "task-1", "borrar", AgentTaskStatus.AWAITING_CONFIRMATION,
                1, request.id, "Esperando",
            ),
        )
        runner._announced_agent_confirmations[request.id] = time.monotonic()

        assert int(runner._agent_autonomy()) == 1
        submit = runner._handle_agent_command(
            Transcript(text="agente, revisá estos archivos", confidence=0.99),
            "agente, revisá estos archivos",
        )
        confirm = runner._handle_agent_command(
            Transcript(text="agente, confirmo", confidence=0.99), "agente, confirmo"
        )
        deny = runner._handle_agent_command(
            Transcript(text="agente, denegá", confidence=0.99), "agente, denegá"
        )

        assert "panel" in submit.lower()
        assert "panel" in confirm.lower()
        assert "panel" in deny.lower()
        assert service.submitted == []
        assert confirmations.status(request.id).state is ConfirmationState.PENDING


def test_announcement_failure_releases_interaction_and_turn_gate() -> None:
    runner, service, confirmations = _runner_for_handler()
    request = confirmations.request("files", {"action": "delete"}, summary="Borrar informe")
    view = AgentTaskView(
        "task-1", "borrar", AgentTaskStatus.AWAITING_CONFIRMATION,
        1, request.id, "Esperando",
    )
    service.views = (view,)
    audio = MagicMock()
    audio.turn_gate.start_processing.side_effect = RuntimeError("gate failed")
    runner.audio_coordinator = audio
    runner._on_agent_task_event("TASK_AWAITING_CONFIRMATION", view)

    runner._try_start_pending_agent_confirmation_announcement()

    assert runner._is_processing_interaction is False
    audio.turn_gate.stop_processing.assert_called_once()
    assert runner._pending_agent_confirmation_announcements.get_nowait()[0] == request.id


def test_shop_announcement_is_generic_and_interrupted_announcement_requeues() -> None:
    runner, _service, confirmations = _runner_for_handler()
    request = confirmations.request("files", {"action": "delete"}, summary="Borrar secreto.txt")
    audio = MagicMock()
    audio.last_speech_interrupted = False
    runner.audio_coordinator = audio
    runner.interaction_coordinator = MagicMock(mode=SocialMode.SHOP)

    runner._announce_agent_confirmation(request.id, request.summary)
    assert audio.speak.call_args.args[0] == "Hay una acción pendiente en el panel."
    assert request.summary not in audio.speak.call_args.args[0]

    audio.reset_mock()
    audio.last_speech_interrupted = True
    runner._announce_agent_confirmation(request.id, request.summary)
    assert request.id not in runner._announced_agent_confirmations
    assert runner._pending_agent_confirmation_announcements.get_nowait() == (
        request.id, request.summary
    )
