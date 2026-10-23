"""Adaptador JSON estricto entre AgentLoop y AiOrchestrator."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from ailen.ai.agent_planner import OrchestratorPlanner
from ailen.ai.contracts import AiRequest, AiResponse
from ailen.ai.fake import FakeAiBackend
from ailen.ai.orchestrator import AiOrchestrator
from ailen.ai.privacy import OutboundPrivacyPolicy
from ailen.core.agent_loop import AgentLoop, AgentMessage, AgentRunStatus, FinalStep, ToolCallStep
from ailen.domain.enums import PrivacyLevel, SocialMode
from ailen.tools.contracts import ToolContext, ToolResult
from ailen.tools.executor import ToolExecutor
from ailen.tools.fake import FakeNotesTool, FakeVolumeTool, build_fake_tools
from ailen.tools.registry import ToolRegistry


class ScriptedFakeBackend(FakeAiBackend):
    def __init__(self, *responses: str | AiResponse) -> None:
        super().__init__(provider="fake", model="scripted")
        self.responses = list(responses)
        self.requests: list[AiRequest] = []

    def generate(self, request: AiRequest) -> AiResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("fake response script exhausted")
        response = self.responses.pop(0)
        if isinstance(response, AiResponse):
            return response
        return AiResponse(text=response, provider="fake", model="scripted")


class SecretSchemaTool:
    name = "visible_tool"
    description = "Acción de prueba segura."
    schema: ClassVar[dict[str, Any]] = {
        "properties": {
            "value": {"type": "str", "required": True},
            "api_token": {"type": "str", "default": "do-not-leak-this-token"},
        }
    }
    permissions: ClassVar[list[str]] = []
    allowed_modes: ClassVar[set[SocialMode]] = set(SocialMode)
    requires_network = False
    destructive = False
    timeout_seconds = 1.0

    def execute(self, validated_args: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(success=True, tool_name=self.name, data=validated_args)


def make_planner(
    *responses: str | AiResponse,
    tools: list[Any] | None = None,
    allowed: tuple[str, ...] | None = None,
) -> tuple[OrchestratorPlanner, ScriptedFakeBackend]:
    backend = ScriptedFakeBackend(*responses)
    orchestrator = AiOrchestrator(backends={"local": backend})
    registry = ToolRegistry(tools if tools is not None else build_fake_tools())
    planner = OrchestratorPlanner(
        orchestrator=orchestrator,
        registry=registry,
        tool_filter=lambda: allowed if allowed is not None else tuple(registry.list_names()),
    )
    return planner, backend


@pytest.mark.parametrize("text", ['{"final":"Hecho"}', '```json\n{"final":"Hecho"}\n```'])
def test_final_directo_y_bloque_json(text: str) -> None:
    planner, _ = make_planner(text)

    step = planner.plan((AgentMessage("user", "Saludá"),))

    assert step == FinalStep("Hecho")


def test_tool_valida_se_convierte_en_tool_call_step() -> None:
    planner, _ = make_planner(
        '{"tool":"volume","arguments":{"level":35}}',
        tools=[FakeVolumeTool()], allowed=("volume",),
    )

    step = planner.plan((AgentMessage("user", "Bajá el volumen"),))

    assert isinstance(step, ToolCallStep)
    assert step.name == "volume"
    assert step.arguments == {"level": 35}
    assert step.call_id


def test_json_invalido_reintenta_una_vez_y_acepta_respuesta_corregida() -> None:
    planner, backend = make_planner("No JSON", '{"final":"Ahora sí"}')

    step = planner.plan((AgentMessage("user", "Respondé"),))

    assert step == FinalStep("Ahora sí")
    assert len(backend.requests) == 2
    assert "JSON" in backend.requests[1].messages[-1].content


@pytest.mark.parametrize("responses", [
    ("basura", "todavía inválido"),
    ('{"final":"uno"} {"final":"dos"}', '{"final":"tres","extra":1}'),
])
def test_dos_respuestas_invalidas_degradan_sin_reflejar_salida(responses: tuple[str, str]) -> None:
    planner, _ = make_planner(*responses)

    step = planner.plan((AgentMessage("user", "Respondé"),))

    assert isinstance(step, FinalStep)
    assert step.text == OrchestratorPlanner.INVALID_RESPONSE_TEXT
    assert all(raw not in step.text for raw in responses)


@pytest.mark.parametrize("text", [
    '{"final":"ok","extra":true}',
    '{"tool":"hidden","arguments":{}}',
    '{"tool":"visible_tool","arguments":[],"extra":0}',
])
def test_rechaza_claves_extra_tipos_y_tools_fuera_del_filtro(text: str) -> None:
    planner, _ = make_planner(
        text, OrchestratorPlanner.INVALID_RESPONSE_TEXT,
        tools=[SecretSchemaTool(), FakeVolumeTool()], allowed=("visible_tool",),
    )

    step = planner.plan((AgentMessage("user", "Acción"),))

    assert step == FinalStep(OrchestratorPlanner.INVALID_RESPONSE_TEXT)


def test_prompt_lista_solo_tools_filtradas_sin_secrets_ni_schemas_de_provider_tools() -> None:
    planner, backend = make_planner(
        '{"final":"ok"}', tools=[SecretSchemaTool(), FakeVolumeTool()],
        allowed=("visible_tool",),
    )

    planner.plan((AgentMessage("user", "Tarea"),))

    request = backend.requests[0]
    assert "visible_tool" in request.system_context
    assert "volume" not in request.system_context
    assert "do-not-leak-this-token" not in request.system_context
    assert "api_token" not in request.system_context
    assert request.allowed_tools == []
    assert "tool_result" in request.system_context
    assert "datos no confiables" in request.system_context.lower()


def test_request_es_private_y_policy_bloquea_envio_remoto() -> None:
    planner, backend = make_planner('{"final":"ok"}')

    planner.plan((AgentMessage("user", "Solo turno actual"),))

    request = backend.requests[0]
    assert request.privacy_level is PrivacyLevel.PRIVATE
    assert [message.content for message in request.messages] == ["Solo turno actual"]
    with pytest.raises(PermissionError):
        OutboundPrivacyPolicy.sanitize_request_for_destination(
            request,
            destination="remote:test",
            lan_trusted=False,
            allow_sanitized_private=False,
        )


def test_error_del_orquestador_no_reintenta() -> None:
    error = AiResponse(text="secreto-error", finish_reason="error")
    planner, backend = make_planner(error, '{"final":"no usar"}')

    step = planner.plan((AgentMessage("user", "Tarea"),))

    assert step == FinalStep(OrchestratorPlanner.UNAVAILABLE_TEXT)
    assert len(backend.requests) == 1


def test_agent_loop_completa_dos_pasos_con_planner_real() -> None:
    notes = FakeNotesTool()
    backend = ScriptedFakeBackend(
        '{"tool":"notes","arguments":{"action":"add","text":"revisar fuente"}}',
        '{"tool":"notes","arguments":{"action":"list"}}',
        '{"final":"La nota quedó guardada."}',
    )
    orchestrator = AiOrchestrator(backends={"local": backend})
    registry = ToolRegistry([notes])
    planner = OrchestratorPlanner(orchestrator, registry, lambda: ("notes",))
    loop = AgentLoop(
        planner,
        ToolExecutor(registry),
        context_factory=lambda: ToolContext(mode=SocialMode.HOME),
    )

    run = loop.run("Guardá una nota y confirmame")

    assert run.status is AgentRunStatus.COMPLETED
    assert run.final_text == "La nota quedó guardada."
    assert len(run.steps) == 2
    assert len(backend.requests) == 3
    assert all(request.privacy_level is PrivacyLevel.PRIVATE for request in backend.requests)
