"""Tests for the web panel. Sin sockets ni Internet: se ejerce `handle()`."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import quote

from ailen.audio.contracts import AudioDevice
from ailen.core.config import AILENConfig
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.memory.repository import MemoryRepository
from ailen.services.diagnostics_admin_service import DiagnosticsAdminService
from ailen.services.memory_admin_service import MemoryAdminService
from ailen.web.app import AILENWebApp, WebRequest
from ailen.web.services import FakeAuthService, FakeStatusService

PASSWORD = "secreto-prueba"


def get(path: str, **kwargs) -> WebRequest:
    return WebRequest(method="GET", path=path, remote_addr="127.0.0.1", **kwargs)


def post(path: str, form: dict[str, str], **kwargs) -> WebRequest:
    body = "&".join(f"{k}={quote(v)}" for k, v in form.items()).encode()
    return WebRequest(
        method="POST",
        path=path,
        body=body,
        remote_addr="127.0.0.1",
        **kwargs,
    )


class TestWebApp(unittest.TestCase):
    def setUp(self):
        self.auth = FakeAuthService(password=PASSWORD)
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        manager = SQLiteManager(Path(directory.name) / "test.db")
        MigrationRunner(manager).run_migrations()
        status = FakeStatusService()
        self.app = AILENWebApp(
            auth=self.auth, status=status,
            memory=MemoryAdminService(MemoryRepository(manager)),
            diagnostics=DiagnosticsAdminService(status, lambda: AILENConfig()),
        )

    def _login_cookie(self) -> str:
        response = self.app.handle(post("/login", {"username": "admin", "password": PASSWORD}))
        self.assertEqual(response.status, 303)
        cookie = response.headers["Set-Cookie"]
        return cookie.split(";")[0]

    # -- acceso público -------------------------------------------------

    def test_ping_no_auth(self):
        response = self.app.handle(get("/api/ping"))
        self.assertEqual(response.status, 200)
        self.assertTrue(json.loads(response.body)["ok"])

    def test_dashboard_redirects_when_anonymous(self):
        response = self.app.handle(get("/"))
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/login")

    def test_api_status_redirects_when_anonymous(self):
        self.assertEqual(self.app.handle(get("/api/status")).status, 303)

    def test_login_page_renders(self):
        response = self.app.handle(get("/login"))
        self.assertEqual(response.status, 200)
        self.assertIn(b"password", response.body)

    def test_login_page_warns_when_auth_not_configured(self):
        app = AILENWebApp(auth=FakeAuthService(password=None), status=FakeStatusService())
        response = app.handle(post("/login", {"username": "admin", "password": "x"}))
        self.assertEqual(response.status, 200)
        self.assertIn(b"ailen admin set-password", response.body)

    # -- flujo autenticado ----------------------------------------------

    def test_login_logout_flow(self):
        cookie = self._login_cookie()

        response = self.app.handle(get("/", headers={"cookie": cookie}))
        self.assertEqual(response.status, 200)
        self.assertIn(b"AIL", response.body)

        # CSRF requerido para logout
        response = self.app.handle(post("/logout", {}, headers={"cookie": cookie}))
        self.assertEqual(response.status, 403)

        # extraer csrf del HTML del dashboard
        html = self.app.handle(get("/", headers={"cookie": cookie})).body.decode()
        marker = 'name="_csrf" value="'
        csrf = html.split(marker)[1].split('"')[0]

        response = self.app.handle(
            post("/logout", {"_csrf": csrf}, headers={"cookie": cookie})
        )
        self.assertEqual(response.status, 303)
        # sesión revocada
        self.assertEqual(
            self.app.handle(get("/", headers={"cookie": cookie})).status, 303
        )

    def test_login_wrong_password(self):
        response = self.app.handle(post("/login", {"username": "admin", "password": "mala"}))
        self.assertEqual(response.status, 200)
        self.assertIn(b"incorrectos", response.body)

    def test_dashboard_content(self):
        cookie = self._login_cookie()
        response = self.app.handle(get("/", headers={"cookie": cookie}))
        body = response.body.decode()
        self.assertIn("IDLE", body)
        self.assertIn("HYBRID", body)

    def test_api_status_json(self):
        cookie = self._login_cookie()
        response = self.app.handle(get("/api/status", headers={"cookie": cookie}))
        self.assertEqual(response.status, 200)
        data = json.loads(response.body)
        self.assertEqual(data["assistant_state"], "IDLE")
        self.assertIn("health", data)
        self.assertIn("services", data)

    def test_api_health_json(self):
        cookie = self._login_cookie()
        response = self.app.handle(get("/api/health", headers={"cookie": cookie}))
        data = json.loads(response.body)
        self.assertIn("overall", data)
        self.assertIn("components", data)

    def test_all_admin_pages_render(self):
        cookie = self._login_cookie()
        pages = (
            "/",
            "/personalidad",
            "/audio",
            "/ia",
            "/memoria",
            "/herramientas",
            "/vision",
            "/rostro",
            "/sistema",
            "/diagnostico",
            "/setup",
            "/comercio",
            "/audio-camara",
        )
        for path in pages:
            response = self.app.handle(get(path, headers={"cookie": cookie}))
            self.assertEqual(response.status, 200, f"Ruta falló: {path}")
            self.assertIn(b"AIL", response.body, f"Branding ausente en: {path}")

    def test_audio_page_exposes_agc_noise_gate_without_changing_device_default(self):
        cookie = self._login_cookie()

        response = self.app.handle(get("/audio", headers={"cookie": cookie}))
        body = response.body.decode("utf-8")

        self.assertIn('name="audio.auto_gain_noise_gate_rms"', body)
        self.assertIn('name="audio.auto_gain_gate_hold_ms"', body)
        self.assertIn('name="audio.input_processing_mode"', body)

    def test_audio_page_is_honest_dynamic_and_has_no_global_alsa_control(self):
        cfg = AILENConfig()
        cfg.speech.vad_threshold = 0.031

        class Settings:
            @staticmethod
            def get_config() -> AILENConfig:
                return cfg

        class Enumerator:
            @staticmethod
            def get_default_route(*, is_input: bool) -> str:
                assert is_input is True
                return "test.source"

            @staticmethod
            def list_pipewire_devices(*, is_input: bool) -> list[AudioDevice]:
                assert is_input is True
                return [
                    AudioDevice(
                        id="pipewire:test.source",
                        name="Micrófono inyectado",
                        backend="pipewire",
                        is_default=True,
                        state="RUNNING",
                    )
                ]

            @staticmethod
            def list_hardware_devices(*, is_input: bool) -> list[AudioDevice]:
                assert is_input is True
                return []

        self.app._settings = Settings()  # type: ignore[assignment]
        cookie = self._login_cookie()
        with patch("ailen.audio.alsa_backend.AlsaDeviceEnumerator", Enumerator):
            response = self.app.handle(get("/audio", headers={"cookie": cookie}))
        body = response.body.decode("utf-8")

        self.assertIn("Micrófono inyectado", body)
        self.assertIn('name="section" value="audio"', body)
        self.assertIn("Umbral VAD (0.031)", body)
        self.assertIn("medición acotada", body.lower())
        for forbidden in (
            "getUserMedia",
            "cancelación de eco",
            "~110ms",
            "Nivelar Ganancias ALSA",
            "/api/audio/reset-alsa",
            "0.022",
            "G600",
            "USB Composite",
        ):
            self.assertNotIn(forbidden, body)

    def test_removed_global_alsa_gain_endpoint_is_not_routable(self):
        cookie = self._login_cookie()
        html = self.app.handle(get("/", headers={"cookie": cookie})).body.decode()
        csrf = html.split('name="_csrf" value="')[1].split('"')[0]

        with patch("subprocess.run") as run:
            response = self.app.handle(
                post(
                    "/api/audio/reset-alsa",
                    {"_csrf": csrf},
                    headers={"cookie": cookie},
                )
            )

        self.assertEqual(response.status, 405)
        run.assert_not_called()

    def test_diagnostics_does_not_claim_a_fixed_piper_latency(self):
        cookie = self._login_cookie()

        response = self.app.handle(get("/diagnostico", headers={"cookie": cookie}))
        diagnostics = response.body.decode("utf-8")
        overview = self.app.handle(get("/", headers={"cookie": cookie})).body.decode(
            "utf-8"
        )

        self.assertIn("Sin medición", diagnostics)
        for body in (diagnostics, overview):
            for fixed_latency in ("110 ms", "180 ms", "95ms", "120ms"):
                self.assertNotIn(fixed_latency, body)

    def test_setup_does_not_claim_detected_hardware_is_certified(self):
        cookie = self._login_cookie()

        response = self.app.handle(get("/setup", headers={"cookie": cookie}))
        body = response.body.decode()

        self.assertIn("ProvisioningPlan", body)
        self.assertIn("no una certificación", body)
        self.assertNotIn("hardware es óptimo", body)
        self.assertNotIn("respuesta instantánea", body)

    def test_404(self):
        cookie = self._login_cookie()
        response = self.app.handle(get("/no-existe", headers={"cookie": cookie}))
        self.assertEqual(response.status, 404)

    def test_method_not_allowed(self):
        cookie = self._login_cookie()
        response = self.app.handle(post("/api/status", {}, headers={"cookie": cookie}))
        self.assertEqual(response.status, 405)

    # -- estáticos --------------------------------------------------------

    def test_static_css(self):
        response = self.app.handle(get("/static/css/main.css"))
        self.assertEqual(response.status, 200)
        self.assertTrue(response.content_type.startswith("text/css"))
        self.assertIn(b"--bg-app", response.body)

    def test_static_js(self):
        response = self.app.handle(get("/static/js/main.js"))
        self.assertEqual(response.status, 200)
        self.assertTrue(response.content_type.startswith("application/javascript"))

    def test_static_traversal_blocked(self):
        for evil in ("/static/../app.py", "/static/css/../../app.py", "/static/%2e%2e/app.py"):
            response = self.app.handle(get(evil))
            self.assertEqual(response.status, 404, evil)

    def test_static_unknown_extension(self):
        response = self.app.handle(get("/static/css/main.exe"))
        self.assertEqual(response.status, 404)


if __name__ == "__main__":
    unittest.main()
