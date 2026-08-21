"""Dashboard y APIs con servicios reales del Core (no fakes) + resiliencia."""

import json
import unittest

from ailen.core.health import HealthService
from ailen.domain.enums import AssistantState
from ailen.services.status_service import StatusService
from ailen.web.app import AILENWebApp, WebRequest
from ailen.web.services import FakeAuthService


def get(path: str, **kwargs) -> WebRequest:
    return WebRequest(method="GET", path=path, remote_addr="127.0.0.1", **kwargs)


class BrokenStatusService:
    """StatusService que falla: el panel no debe morir por diagnóstico."""

    def get_runtime_state(self):  # type: ignore[no-untyped-def]
        raise RuntimeError("diagnóstico roto")

    def get_health_report(self):  # type: ignore[no-untyped-def]
        raise RuntimeError("diagnóstico roto")

    def get_hardware_report(self, refresh: bool = False):  # type: ignore[no-untyped-def]
        raise RuntimeError("diagnóstico roto")

    def get_dashboard_summary(self) -> dict[str, object]:
        raise RuntimeError("diagnóstico roto")


class TestDashboardRealServices(unittest.TestCase):
    def setUp(self):
        self.auth = FakeAuthService(password="secreto-prueba")
        health = HealthService(node_id="nodo-real")
        health.set_assistant_state(AssistantState.IDLE)
        self.status = StatusService(health_service=health)
        self.app = AILENWebApp(auth=self.auth, status=self.status)

    def _login_cookie(self) -> str:
        from urllib.parse import quote

        body = f"username=admin&password={quote('secreto-prueba')}".encode()
        response = self.app.handle(
            WebRequest(method="POST", path="/login", body=body, remote_addr="127.0.0.1")
        )
        assert response.status == 303
        return response.headers["Set-Cookie"].split(";")[0]

    def test_dashboard_uses_real_status(self):
        cookie = self._login_cookie()
        response = self.app.handle(get("/", headers={"cookie": cookie}))
        self.assertEqual(response.status, 200)
        body = response.body.decode()
        self.assertIn("IDLE", body)
        self.assertIn("nodo-real", body)
        self.assertNotIn("fake-status-service", body)

    def test_api_status_real_has_hardware(self):
        cookie = self._login_cookie()
        response = self.app.handle(get("/api/status", headers={"cookie": cookie}))
        self.assertEqual(response.status, 200)
        data = json.loads(response.body)
        self.assertEqual(data["node_id"], "nodo-real")
        self.assertIn("hardware", data)
        self.assertIn("ram_mb", data["hardware"])

    def test_api_health_real(self):
        cookie = self._login_cookie()
        response = self.app.handle(get("/api/health", headers={"cookie": cookie}))
        self.assertEqual(response.status, 200)
        data = json.loads(response.body)
        self.assertEqual(data["overall"], "HEALTHY")


class TestPanelResilience(unittest.TestCase):
    def setUp(self):
        self.app = AILENWebApp(
            auth=FakeAuthService(password="secreto-prueba"),
            status=BrokenStatusService(),  # type: ignore[arg-type]
        )

    def _login_cookie(self) -> str:
        from urllib.parse import quote

        body = f"username=admin&password={quote('secreto-prueba')}".encode()
        response = self.app.handle(
            WebRequest(method="POST", path="/login", body=body, remote_addr="127.0.0.1")
        )
        assert response.status == 303
        return response.headers["Set-Cookie"].split(";")[0]

    def test_broken_status_does_not_kill_dashboard(self):
        cookie = self._login_cookie()
        response = self.app.handle(get("/", headers={"cookie": cookie}))
        self.assertEqual(response.status, 200)
        self.assertIn("UNKNOWN", response.body.decode())

    def test_broken_status_does_not_kill_skeleton_pages(self):
        cookie = self._login_cookie()
        response = self.app.handle(get("/sistema", headers={"cookie": cookie}))
        self.assertEqual(response.status, 200)
        self.assertIn("no disponible", response.body.decode())

    def test_ping_survives_broken_status(self):
        response = self.app.handle(get("/api/ping"))
        self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
