"""HTTP guards and real confirmation flow of the /agente panel."""
from pathlib import Path
from urllib.parse import urlencode

import pytest

from ailen.core.config import AILENConfig
from ailen.core.confirmation import ConfirmationService, ConfirmationState
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.memory.repository import MemoryRepository
from ailen.services.agent_admin_service import AgentAdminService
from ailen.web.app import AILENWebApp, WebRequest
from ailen.web.services import FakeAuthService, FakeStatusService


@pytest.fixture
def setup(tmp_path: Path):
    manager = SQLiteManager(tmp_path / "agent.db")
    MigrationRunner(manager).run_migrations()
    repo = MemoryRepository(manager)
    confirmations = ConfirmationService()
    service = AgentAdminService(AILENConfig, confirmations, repo)
    auth = FakeAuthService(password="test-only")
    token, csrf = auth.create_session()
    app = AILENWebApp(auth, FakeStatusService(), agent=service)

    def request(path="/agente", method="GET", data=None, authenticated=True):
        return app.handle(WebRequest(
            method, path,
            headers={"cookie": f"ailen_session={token}"} if authenticated else {},
            body=urlencode(data or {}).encode(),
        ))

    return confirmations, repo, request, csrf


def test_page_shows_real_pending_and_audit_rows(setup):
    confirmations, repo, request, _ = setup
    pending = confirmations.request("files", {"action": "overwrite"}, summary="Sobrescribir notas.txt")
    repo.log_tool_event("clock", "{}", "ok", True, 1.0)
    body = request().body.decode()
    assert "Sobrescribir notas.txt" in body and "clock" in body and pending.id in body


def test_actions_need_post_csrf_and_auth(setup):
    confirmations, _, request, csrf = setup
    pending = confirmations.request("files", {"action": "overwrite"})
    data = {"confirmation_id": pending.id}
    assert request("/agente/approve").status == 405
    assert request("/agente/approve", "POST", data).status == 403
    assert request("/agente/approve", "POST", {**data, "_csrf": "bad"}).status == 403
    assert request("/agente/approve", "POST", {**data, "_csrf": csrf}, authenticated=False).status in (302, 303, 401, 403)
    assert confirmations.status(pending.id).state is ConfirmationState.PENDING


def test_approve_deny_and_invalid_id(setup):
    confirmations, _, request, csrf = setup
    first = confirmations.request("files", {"a": 1})
    second = confirmations.request("files", {"a": 2})
    assert request("/agente/approve", "POST", {"_csrf": csrf, "confirmation_id": first.id}).status == 303
    assert request("/agente/deny", "POST", {"_csrf": csrf, "confirmation_id": second.id}).status == 303
    assert confirmations.status(first.id).state is ConfirmationState.APPROVED
    assert confirmations.status(second.id).state is ConfirmationState.DENIED
    assert request("/agente/approve", "POST", {"_csrf": csrf, "confirmation_id": "nope"}).status == 400


def test_unconfigured_agent_is_honest():
    auth = FakeAuthService(password="test-only")
    token, _ = auth.create_session()
    app = AILENWebApp(auth, FakeStatusService())
    response = app.handle(WebRequest("GET", "/agente", headers={"cookie": f"ailen_session={token}"}))
    assert response.status == 503
