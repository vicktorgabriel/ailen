"""Panel acotado de administración del agente ADR-014."""

from dataclasses import replace

import pytest

from ailen.core.config import AILENConfig
from ailen.core.confirmation import ConfirmationRequest, ConfirmationService, ConfirmationState
from ailen.domain.models import ToolEvent
from ailen.services.agent_admin_service import AgentAdminError, AgentAdminService
from ailen.web.agent_view import agent_content


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class ListableConfirmations(ConfirmationService):
    """Real resolver plus the optional admin listing adapter contract."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._admin_ids: list[str] = []

    def request(self, tool_name, arguments, *, summary=None):
        request = super().request(tool_name, arguments, summary=summary)
        self._admin_ids.append(request.id)
        return request

    def pending_requests(self) -> tuple[ConfirmationRequest, ...]:
        requests = (self.status(request_id) for request_id in self._admin_ids)
        return tuple(request for request in requests if request and request.state is ConfirmationState.PENDING)


class FakeEvents:
    def __init__(self, events: tuple[ToolEvent, ...] = ()) -> None:
        self.events = events
        self.requested_limit: int | None = None

    def recent_tool_events(self, limit: int) -> tuple[ToolEvent, ...]:
        self.requested_limit = limit
        return self.events[:limit]


class ConfigProvider:
    def __init__(self, cfg: AILENConfig) -> None:
        self.cfg = cfg

    def __call__(self) -> AILENConfig:
        return self.cfg


def _event(tool_name: str, arguments: str, result_summary: str = "safe") -> ToolEvent:
    return ToolEvent(
        event_id="tool-test", session_id=None, tool_name=tool_name,
        arguments_redacted=arguments, result_summary=result_summary,
        success=True, latency_ms=12.0, created_at="2026-10-23T12:00:00+00:00",
    )


def test_approve_y_deny_usan_confirmation_service_real() -> None:
    confirmations = ListableConfirmations()
    approved = confirmations.request("write_file", {"path": "safe.txt"}, summary="Crear safe.txt")
    denied = confirmations.request("delete_file", {"path": "old.txt"}, summary="Borrar old.txt")
    service = AgentAdminService(ConfigProvider(AILENConfig()), confirmations, FakeEvents())

    service.approve(approved.id)
    service.deny(denied.id)

    assert confirmations.status(approved.id).state is ConfirmationState.APPROVED
    assert confirmations.status(denied.id).state is ConfirmationState.DENIED


@pytest.mark.parametrize("action", ["approve", "deny"])
def test_id_inexistente_da_error_controlado(action: str) -> None:
    service = AgentAdminService(ConfigProvider(AILENConfig()), ConfirmationService(), FakeEvents())

    with pytest.raises(AgentAdminError, match="no existe, venció o ya fue resuelta"):
        getattr(service, action)("unknown-id")


def test_id_vencido_da_error_controlado() -> None:
    clock = Clock()
    confirmations = ConfirmationService(ttl_seconds=1, clock=clock)
    request = confirmations.request("write_file", {})
    clock.now = 1
    service = AgentAdminService(ConfigProvider(AILENConfig()), confirmations, FakeEvents())

    with pytest.raises(AgentAdminError, match="no existe, venció o ya fue resuelta"):
        service.approve(request.id)


def test_vista_escapa_resumen_y_nombre_de_tool() -> None:
    confirmations = ListableConfirmations()
    confirmation = confirmations.request(
        "write_file", {"path": "x"},
        summary="<img src=x onerror=alert(1)>",
    )
    confirmations.pending_requests = lambda: (replace(
        confirmation, tool_name="<script>alert(1)</script>"
    ),)
    events = FakeEvents((_event("<svg/onload=alert(1)>", "{}"),))
    service = AgentAdminService(ConfigProvider(AILENConfig()), confirmations, events)

    body = agent_content(service.snapshot(), csrf="csrf", flash="<b>flash</b>")

    assert "<script>alert(1)</script>" not in body
    assert "<img src=x onerror=alert(1)>" not in body
    assert "<svg/onload=alert(1)>" not in body
    assert "&lt;script&gt;" in body
    assert "&lt;img" in body
    assert "&lt;svg" in body
    assert "&lt;b&gt;flash&lt;/b&gt;" in body


def test_snapshot_y_vista_sin_confirmation_service_son_honestos() -> None:
    service = AgentAdminService(ConfigProvider(AILENConfig()), None, FakeEvents())

    body = agent_content(service.snapshot(), csrf="csrf", flash="")

    assert "No disponible" in body
    assert "Sin eventos" in body


def test_snapshot_muestra_vacios_reales_y_cap_autonomy_y_roots_read_only() -> None:
    cfg = AILENConfig()
    cfg.agent.max_autonomy_level = 3
    cfg.agent.file_roots = ["/srv/ailen/docs"]
    service = AgentAdminService(ConfigProvider(cfg), ListableConfirmations(), FakeEvents())

    body = agent_content(service.snapshot(), csrf="token", flash="")

    assert "Autonomía máxima: N3" in body
    assert "/srv/ailen/docs" in body
    assert "solo lectura" in body.lower()
    assert "se editan en /config" in body
    assert "requieren reinicio" in body
    assert "Sin confirmaciones pendientes" in body
    assert "Sin eventos" in body


def test_snapshot_no_expone_contenido_de_archivos() -> None:
    cfg = AILENConfig()
    cfg.agent.file_roots = ["/srv/ailen/private"]
    secret_content = "FILE-CONTENT-MUST-NOT-APPEAR"
    events = FakeEvents((
        _event("files", '{"path":"note.txt","content":"[REDACTED]"}', secret_content),
    ))
    service = AgentAdminService(ConfigProvider(cfg), None, events)

    snapshot = service.snapshot()
    body = agent_content(snapshot, csrf="csrf", flash="")

    assert events.requested_limit == 50
    assert "arguments_redacted" in body or "path" in body
    assert secret_content not in body
    assert "content" not in snapshot.events[0].arguments_redacted


def test_expiracion_se_refleja_como_vencida_en_aprobacion() -> None:
    clock = Clock()
    confirmations = ConfirmationService(ttl_seconds=1, clock=clock)
    request = confirmations.request("write_file", {})
    clock.now = 1
    assert confirmations.status(request.id).state is ConfirmationState.EXPIRED


def test_panel_muestra_las_pendientes_reales() -> None:
    confirmations = ConfirmationService()
    req1 = confirmations.request("write_file", {"path": "safe.txt"}, summary="Crear archivo safe.txt")
    req2 = confirmations.request("delete_file", {"path": "tmp.txt"}, summary="Borrar archivo tmp.txt")
    service = AgentAdminService(ConfigProvider(AILENConfig()), confirmations, FakeEvents())

    snapshot = service.snapshot()
    assert snapshot.confirmations_available is True
    assert len(snapshot.confirmations) == 2
    assert snapshot.confirmations[0].id == req1.id
    assert snapshot.confirmations[0].tool_name == "write_file"
    assert snapshot.confirmations[0].summary == "Crear archivo safe.txt"
    assert snapshot.confirmations[0].seconds_remaining > 0
    assert snapshot.confirmations[1].id == req2.id
    assert snapshot.confirmations[1].tool_name == "delete_file"
    assert snapshot.confirmations[1].summary == "Borrar archivo tmp.txt"

    body = agent_content(snapshot, csrf="csrf-token", flash="")
    assert "No disponible" not in body
    assert "Crear archivo safe.txt" in body
    assert "Borrar archivo tmp.txt" in body
    assert "write_file" in body
    assert "delete_file" in body

