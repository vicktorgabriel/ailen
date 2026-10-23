"""Real SQLite admin operations, privacy defaults and HTTP guards."""
from pathlib import Path
from urllib.parse import urlencode

import pytest

from ailen.domain.enums import PrivacyLevel
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.memory.repository import MemoryRepository
from ailen.services.memory_admin_service import MemoryAdminService
from ailen.web.app import AILENWebApp, WebRequest
from ailen.web.services import FakeAuthService, FakeStatusService


@pytest.fixture
def setup(tmp_path: Path):
    manager = SQLiteManager(tmp_path / "test.db")
    MigrationRunner(manager).run_migrations()
    repo = MemoryRepository(manager)
    service = MemoryAdminService(repo)
    auth = FakeAuthService(password="test-only")
    token, csrf = auth.create_session()
    app = AILENWebApp(auth, FakeStatusService(), memory=service)

    def request(path="/memoria", method="GET", data=None, query="", authenticated=True):
        return app.handle(WebRequest(
            method, path, query=query,
            headers={"cookie": f"ailen_session={token}"} if authenticated else {},
            body=urlencode(data or {}).encode(),
        ))

    return repo, service, request, csrf


def test_public_default_private_opt_in_and_real_search(setup):
    repo, _, request, _ = setup
    repo.add_memory("private-test-content")
    repo.add_memory("public-test-content", scope=PrivacyLevel.PUBLIC)
    body = request().body.decode()
    assert "public-test-content" in body
    assert "private-test-content" not in body
    assert "Todos (142)" not in body
    assert "private-test-content" in request(query="include_private=1").body.decode()
    assert "public-test-content" not in request(query="q=absent").body.decode()
    assert "Sin recuerdos" in request(query="q=absent").body.decode()


def test_crud_confirmations_and_persistence(setup):
    repo, service, request, csrf = setup
    data = {"_csrf": csrf, "content": "first", "category": "general", "scope": "PRIVATE", "confirm": "yes"}
    assert request("/memoria/create", "POST", data).status == 303
    item = repo.get_recent_memories()[0]
    assert item.scope == PrivacyLevel.PRIVATE
    data.update(memory_id=item.memory_id, content="updated", confirm="yes")
    assert request("/memoria/update", "POST", data).status == 303
    assert service.get(item.memory_id, include_private=True).content == "updated"
    assert request("/memoria/delete", "POST", {"_csrf": csrf, "memory_id": item.memory_id}).status == 400
    assert repo.get_recent_memories()
    assert request("/memoria/delete", "POST", data).status == 303
    assert repo.get_recent_memories() == []


def test_auth_csrf_method_validation_and_missing_item(setup):
    repo, _, request, csrf = setup
    assert request(authenticated=False).status == 303
    assert request("/memoria/create", "POST", {"content": "bad"}).status == 403
    assert request("/memoria/create").status == 405
    assert request("/memoria/create", "POST", {"_csrf": csrf, "content": "x", "scope": "INVALID"}).status == 400
    assert request("/memoria/update", "POST", {
        "_csrf": csrf, "memory_id": "mem-missing", "content": "x", "confirm": "yes",
    }).status == 404
    assert repo.get_recent_memories() == []


def test_export_requires_post_confirmation_and_filters_private(setup):
    repo, _, request, csrf = setup
    repo.add_memory("private-export")
    repo.add_memory("public-export", scope=PrivacyLevel.PUBLIC)
    assert request("/memoria/export").status == 405
    assert request("/memoria/export", "POST", {"_csrf": csrf}).status == 400
    data = {"_csrf": csrf, "confirm": "yes"}
    response = request("/memoria/export", "POST", data)
    assert response.status == 200
    assert "attachment" in response.headers["Content-Disposition"]
    assert response.headers["Cache-Control"] == "no-store"
    assert b"public-export" in response.body and b"private-export" not in response.body
    data["include_private"] = "1"
    assert b"private-export" in request("/memoria/export", "POST", data).body


def test_escape_pagination_literal_search_and_private_edit_guard(setup):
    repo, service, request, _ = setup
    private = repo.add_memory("never-spontaneously")
    assert request(query=f"edit={private.memory_id}").status == 404
    for i in range(52):
        repo.add_memory(f"public-row-{i}", scope=PrivacyLevel.PUBLIC)
    repo.add_memory('<script>alert("bad")</script> 100%', scope=PrivacyLevel.PUBLIC)
    page = service.list_memories(query="%")
    assert page.total == 1
    body = request(query="q=%25").body.decode()
    assert '<script>alert("bad")</script>' not in body
    assert "&lt;script&gt;" in body
    page1 = service.list_memories()
    page2 = service.list_memories(page=2)
    assert page1.total == 53 and len(page1.items) == 50 and len(page2.items) == 3
    assert not {m.memory_id for m in page1.items} & {m.memory_id for m in page2.items}
    assert request(query="page=-1").status == 400


def test_unconfigured_page_is_honest():
    auth = FakeAuthService("test")
    token, _ = auth.create_session()
    app = AILENWebApp(auth, FakeStatusService())
    response = app.handle(WebRequest("GET", "/memoria", headers={"cookie": f"ailen_session={token}"}))
    assert response.status == 503
    assert "no disponible" in response.body.decode()
    assert b"REGN" not in response.body


def test_mutations_require_confirmation_and_preserve_other_data(setup):
    repo, _, request, csrf = setup
    note = repo.create_note("separate-note")
    reminder = repo.create_reminder("separate-reminder", "2099-01-01T00:00:00+00:00")
    item = repo.add_memory("old", importance=4, expires_at="2099-01-01T00:00:00+00:00")
    assert request("/memoria/create", "POST", {"_csrf": csrf, "content": "new"}).status == 400
    payload = {"_csrf": csrf, "content": "edited", "memory_id": item.memory_id, "confirm": "yes"}
    assert request("/memoria/update", "POST", payload).status == 303
    saved = repo.get_memory(item.memory_id)
    assert saved.importance == 4 and saved.expires_at == item.expires_at
    assert request("/memoria/delete", "POST", payload).status == 303
    assert repo.list_notes()[0].note_id == note.note_id
    assert repo.list_reminders()[0].reminder_id == reminder.reminder_id


def test_export_limit_fails_without_truncating(setup, monkeypatch):
    repo, service, request, csrf = setup
    monkeypatch.setattr(service, "EXPORT_LIMIT", 1)
    repo.add_memory("one", scope=PrivacyLevel.PUBLIC)
    repo.add_memory("two", scope=PrivacyLevel.PUBLIC)
    response = request("/memoria/export", "POST", {"_csrf": csrf, "confirm": "yes"})
    assert response.status == 400 and "Content-Disposition" not in response.headers


def test_backend_error_redacted(setup, monkeypatch):
    _, service, request, _ = setup
    def fail(*args, **kwargs):
        raise RuntimeError("private-content credential=secret")
    monkeypatch.setattr(service, "list_memories", fail)
    response = request()
    assert response.status == 503
    assert b"private-content" not in response.body and b"credential=secret" not in response.body


def test_http_access_log_omits_private_search_query(caplog):
    import logging

    from ailen.web.server import _Handler

    handler = _Handler.__new__(_Handler)
    handler.command = "GET"
    handler.path = "/memoria?q=private-search-content&include_private=1"
    with caplog.at_level(logging.DEBUG, logger="ailen.web.server"):
        handler.log_request(200)
    assert "HTTP GET /memoria 200" in caplog.text
    assert "private-search-content" not in caplog.text
