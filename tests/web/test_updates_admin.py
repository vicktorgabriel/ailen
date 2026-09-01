"""Authenticated, redacted update administration routes."""

from __future__ import annotations

import json
from dataclasses import replace
from urllib.parse import quote

import pytest

from ailen.updates.contracts import (
    OperationStatus,
    UpdateAdminSnapshot,
    UpdateChannel,
    UpdateCommandResult,
    UpdateErrorKind,
    UpdateFailure,
    UpdatePhase,
)
from ailen.web.app import AILENWebApp, WebRequest
from ailen.web.services import FakeAuthService, FakeStatusService

PASSWORD = "secreto-prueba"


def _get(path: str, *, cookie: str = "", query: str = "") -> WebRequest:
    return WebRequest(
        method="GET",
        path=path,
        query=query,
        headers={"cookie": cookie} if cookie else {},
        remote_addr="127.0.0.1",
    )


def _post(path: str, form: dict[str, str], *, cookie: str = "") -> WebRequest:
    body = "&".join(f"{quote(key)}={quote(value)}" for key, value in form.items()).encode()
    return WebRequest(
        method="POST",
        path=path,
        body=body,
        headers={"cookie": cookie} if cookie else {},
        remote_addr="127.0.0.1",
    )


def _operation(phase: UpdatePhase = UpdatePhase.PREPARED) -> OperationStatus:
    return OperationStatus(
        operation_id="operation-1",
        phase=phase,
        release_id="ailen-0.4.1-beta.1",
        downloaded_bytes=1024,
        total_bytes=2048,
        error_kind=None,
        error_message="",
        started_at="2026-08-31T12:00:00+00:00",
        updated_at="2026-08-31T12:01:00+00:00",
    )


class _Updates:
    def __init__(self, *, phase: UpdatePhase = UpdatePhase.PREPARED) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.operation = _operation(phase)
        self.admin = UpdateAdminSnapshot(
            availability="AVAILABLE",
            mode="LAB_SIMULATION",
            channel=UpdateChannel.BETA,
            installed_version="0.4.0-dev.0",
            effective_version="0.4.0-dev.0",
            candidate_version="0.4.1-beta.1",
            release_notes="Mejora <script>alert(1)</script> sin secretos.",
            operation=self.operation,
            rollback_available=phase is UpdatePhase.ACTIVE,
            detail="verified update is available",
            candidate_release_id="ailen-0.4.1-beta.1",
        )

    def snapshot(self) -> UpdateAdminSnapshot:
        self.calls.append(("snapshot", ()))
        return self.admin

    def check(self) -> UpdateCommandResult:
        self.calls.append(("check", ()))
        return UpdateCommandResult(True, "UPDATE_AVAILABLE", "verified update is available")

    def plan(self, release_id: str) -> UpdateCommandResult:
        self.calls.append(("plan", (release_id,)))
        return UpdateCommandResult(
            True,
            "APPROVAL_REQUIRED",
            "download plan awaits approval",
            operation_id="operation-1",
            approval_token="synthetic-approval-token",
        )

    def start_download(
        self,
        release_id: str,
        approval_token: str,
    ) -> UpdateCommandResult:
        self.calls.append(("download", (release_id, approval_token)))
        return UpdateCommandResult(
            True,
            "DOWNLOAD_STARTED",
            "artifact download started",
            operation_id="operation-1",
        )

    def cancel(self, operation_id: str) -> UpdateCommandResult:
        self.calls.append(("cancel", (operation_id,)))
        return UpdateCommandResult(
            True,
            "CANCEL_REQUESTED",
            "operation cancellation requested",
            operation_id=operation_id,
        )

    def activate(self, operation_id: str) -> UpdateCommandResult:
        self.calls.append(("activate", (operation_id,)))
        return UpdateCommandResult(
            True,
            "ACTIVATED",
            "release activated",
            operation_id=operation_id,
        )

    def rollback(self) -> UpdateCommandResult:
        self.calls.append(("rollback", ()))
        return UpdateCommandResult(True, "ROLLED_BACK", "release rolled back")

    def status(self, operation_id: str) -> OperationStatus:
        self.calls.append(("status", (operation_id,)))
        if operation_id != self.operation.operation_id:
            raise UpdateFailure(UpdateErrorKind.INTEGRITY, "private /var/lib/path")
        return self.operation


@pytest.fixture
def web_app() -> tuple[AILENWebApp, FakeAuthService, _Updates]:
    auth = FakeAuthService(password=PASSWORD)
    updates = _Updates()
    app = AILENWebApp(auth=auth, status=FakeStatusService(), updates=updates)
    return app, auth, updates


def _login(app: AILENWebApp, auth: FakeAuthService) -> tuple[str, str]:
    response = app.handle(
        _post("/login", {"username": "admin", "password": PASSWORD})
    )
    cookie = response.headers["Set-Cookie"].split(";", 1)[0]
    token = cookie.split("=", 1)[1]
    csrf = auth.validate_session(token)
    assert csrf is not None
    return cookie, csrf


def test_updates_page_requires_authentication(web_app: tuple[AILENWebApp, FakeAuthService, _Updates]) -> None:
    app, _, _ = web_app

    response = app.handle(_get("/actualizaciones"))

    assert response.status == 303
    assert response.headers["Location"] == "/login"


@pytest.mark.parametrize(
    "path",
    [
        "/api/updates/check",
        "/api/updates/plan",
        "/api/updates/download",
        "/api/updates/cancel",
        "/api/updates/activate",
        "/api/updates/rollback",
    ],
)
def test_update_mutations_require_auth_and_csrf(
    web_app: tuple[AILENWebApp, FakeAuthService, _Updates],
    path: str,
) -> None:
    app, auth, updates = web_app
    assert app.handle(_post(path, {})).status == 303
    cookie, _ = _login(app, auth)

    response = app.handle(_post(path, {"_csrf": "wrong"}, cookie=cookie))

    assert response.status == 403
    assert updates.calls == []


def test_updates_page_is_redacted_escaped_and_labels_lab_simulation(
    web_app: tuple[AILENWebApp, FakeAuthService, _Updates],
) -> None:
    app, auth, _ = web_app
    cookie, _ = _login(app, auth)

    response = app.handle(_get("/actualizaciones", cookie=cookie))
    body = response.body.decode("utf-8")

    assert response.status == 200
    assert "LAB_SIMULATION" in body
    assert "READY_FOR_APPLIANCE" not in body
    assert "0.4.0-dev.0" in body
    assert "0.4.1-beta.1" in body
    assert "PREPARED" in body
    assert "1024 / 2048" in body
    assert "50%" in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "<script>alert(1)</script>" not in body
    assert "manifest_url" not in body
    assert "trust_public_key_path" not in body
    assert "/var/lib" not in body
    assert "data-operation-id=\"operation-1\"" in body
    assert "data-release-id=\"ailen-0.4.1-beta.1\"" in body


def test_default_missing_update_service_is_honestly_unavailable() -> None:
    auth = FakeAuthService(password=PASSWORD)
    app = AILENWebApp(auth=auth, status=FakeStatusService())
    cookie, _ = _login(app, auth)

    response = app.handle(_get("/actualizaciones", cookie=cookie))
    body = response.body.decode("utf-8")

    assert response.status == 200
    assert "UNAVAILABLE" in body
    assert "data-update-action=\"activate\"" not in body
    assert "data-update-action=\"rollback\"" not in body


def test_update_api_delegates_exact_fields_once(
    web_app: tuple[AILENWebApp, FakeAuthService, _Updates],
) -> None:
    app, auth, updates = web_app
    cookie, csrf = _login(app, auth)

    plan = app.handle(
        _post(
            "/api/updates/plan",
            {"_csrf": csrf, "release_id": "ailen-0.4.1-beta.1"},
            cookie=cookie,
        )
    )
    plan_data = json.loads(plan.body)
    download = app.handle(
        _post(
            "/api/updates/download",
            {
                "_csrf": csrf,
                "release_id": "ailen-0.4.1-beta.1",
                "approval_token": plan_data["approval_token"],
            },
            cookie=cookie,
        )
    )
    activated = app.handle(
        _post(
            "/api/updates/activate",
            {"_csrf": csrf, "operation_id": "operation-1"},
            cookie=cookie,
        )
    )

    assert plan.status == 200
    assert download.status == 202
    assert activated.status == 200
    assert updates.calls == [
        ("plan", ("ailen-0.4.1-beta.1",)),
        ("download", ("ailen-0.4.1-beta.1", "synthetic-approval-token")),
        ("activate", ("operation-1",)),
    ]


def test_unknown_and_invalid_operation_ids_are_typed_and_redacted(
    web_app: tuple[AILENWebApp, FakeAuthService, _Updates],
) -> None:
    app, auth, _ = web_app
    cookie, _ = _login(app, auth)

    invalid = app.handle(
        _get(
            "/api/updates/status",
            cookie=cookie,
            query="operation_id=../../private",
        )
    )
    unknown = app.handle(
        _get(
            "/api/updates/status",
            cookie=cookie,
            query="operation_id=operation-999",
        )
    )

    assert invalid.status == 400
    assert unknown.status == 404
    serialized = invalid.body + unknown.body
    assert b"/var/lib" not in serialized
    assert b"Traceback" not in serialized
    assert b"../../private" not in serialized


def test_status_api_serializes_only_public_operation_fields(
    web_app: tuple[AILENWebApp, FakeAuthService, _Updates],
) -> None:
    app, auth, _ = web_app
    cookie, _ = _login(app, auth)

    response = app.handle(
        _get(
            "/api/updates/status",
            cookie=cookie,
            query="operation_id=operation-1",
        )
    )
    data = json.loads(response.body)

    assert response.status == 200
    assert data == {
        "ok": True,
        "operation": {
            "operation_id": "operation-1",
            "phase": "prepared",
            "release_id": "ailen-0.4.1-beta.1",
            "downloaded_bytes": 1024,
            "total_bytes": 2048,
            "error_kind": None,
            "error_message": "",
            "started_at": "2026-08-31T12:00:00+00:00",
            "updated_at": "2026-08-31T12:01:00+00:00",
        },
    }


def test_extra_form_fields_are_rejected_without_delegation(
    web_app: tuple[AILENWebApp, FakeAuthService, _Updates],
) -> None:
    app, auth, updates = web_app
    cookie, csrf = _login(app, auth)

    response = app.handle(
        _post(
            "/api/updates/cancel",
            {
                "_csrf": csrf,
                "operation_id": "operation-1",
                "artifact_path": "/private/path",
            },
            cookie=cookie,
        )
    )

    assert response.status == 400
    assert updates.calls == []


def test_page_polling_is_bounded_to_one_second_and_stops_on_terminal_phase(
    web_app: tuple[AILENWebApp, FakeAuthService, _Updates],
) -> None:
    app, auth, updates = web_app
    updates.operation = replace(updates.operation, phase=UpdatePhase.DOWNLOADING)
    updates.admin = replace(updates.admin, operation=updates.operation)
    cookie, _ = _login(app, auth)

    body = app.handle(_get("/actualizaciones", cookie=cookie)).body.decode("utf-8")

    assert "setTimeout(pollUpdateStatus, 1000)" in body
    assert "terminalPhases" in body
    assert "beforeunload" in body
