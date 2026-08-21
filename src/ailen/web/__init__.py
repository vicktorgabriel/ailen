"""Web package: panel de administración responsive sin SPA."""

import os

from ailen.web.app import AILENWebApp, WebRequest, WebResponse
from ailen.web.server import create_server, serve
from ailen.web.services import AuthService, FakeAuthService, FakeStatusService, StatusService

__all__ = [
    "AILENWebApp",
    "AuthService",
    "FakeAuthService",
    "FakeStatusService",
    "StatusService",
    "WebRequest",
    "WebResponse",
    "build_dev_app",
    "create_server",
    "serve",
]


def build_dev_app() -> AILENWebApp:
    """Panel con servicios fake para desarrollo.

    Contraseña vía env ``AILEN_ADMIN_PASSWORD``. Sin ella, el login queda
    deshabilitado (nunca hay contraseña default hardcodeada).
    """
    auth = FakeAuthService(password=os.environ.get("AILEN_ADMIN_PASSWORD"))
    status = FakeStatusService()
    return AILENWebApp(auth=auth, status=status)
