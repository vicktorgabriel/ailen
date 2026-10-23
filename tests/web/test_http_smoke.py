"""Smoke HTTP acotado: server real en loopback, sin Internet.

Valida el puente http.server -> app: headers de seguridad, límite de body,
métodos no permitidos y flujo login básico sobre TCP real.
"""

import threading
import unittest
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from unittest.mock import MagicMock
from urllib.parse import quote

from ailen.services.config_service import ConfigService
from ailen.services.settings_service import SettingsService
from ailen.web.app import AILENWebApp, WebResponse
from ailen.web.server import MAX_BODY_BYTES, _Handler, create_server
from ailen.web.services import FakeAuthService, FakeStatusService

PASSWORD = "secreto-prueba"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Opener que no sigue redirects: permite asertar el 303 y leer cookies."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class TestHTTPSmoke(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg_path = Path(tmp.name) / "ailen.toml"
        cfg_path.write_text("schema_version = 1\n", encoding="utf-8")
        self.app = AILENWebApp(
            auth=FakeAuthService(password=PASSWORD),
            status=FakeStatusService(),
            settings=SettingsService(ConfigService(cfg_path)),
        )
        from ailen.infrastructure.sqlite.connection import SQLiteManager
        from ailen.infrastructure.sqlite.migrations import MigrationRunner
        from ailen.memory.repository import MemoryRepository
        from ailen.services.diagnostics_admin_service import DiagnosticsAdminService
        from ailen.services.memory_admin_service import MemoryAdminService

        manager = SQLiteManager(Path(tmp.name) / "test.db")
        MigrationRunner(manager).run_migrations()
        self.app._memory = MemoryAdminService(MemoryRepository(manager))
        self.app._diagnostics = DiagnosticsAdminService(
            self.app._status, self.app._settings.get_config, Path(tmp.name),
        )
        self.server = create_server(self.app, "127.0.0.1", 0)
        port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{port}"
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.opener = urllib.request.build_opener(_NoRedirect)

    def _request(
        self,
        path: str,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        request = urllib.request.Request(self.base + path, data=data, method=method)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with self.opener.open(request, timeout=5) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def _login(self) -> str:
        body = f"username=admin&password={quote(PASSWORD)}".encode()
        status, headers, _ = self._request(
            "/login",
            method="POST",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert status == 303, status
        cookie = SimpleCookie(headers["Set-Cookie"])
        return f"ailen_session={cookie['ailen_session'].value}"

    def test_client_disconnect_during_send_is_ignored(self) -> None:
        handler = _Handler.__new__(_Handler)
        handler.command = "GET"
        handler.path = "/ia"
        handler.send_response = MagicMock()  # type: ignore[method-assign]
        handler.send_header = MagicMock()  # type: ignore[method-assign]
        handler.end_headers = MagicMock()  # type: ignore[method-assign]
        handler.wfile = MagicMock()
        handler.wfile.write.side_effect = BrokenPipeError(32, "Broken pipe")

        handler._send(WebResponse(status=200, body=b"panel"))
        handler.wfile.write.assert_called_once_with(b"panel")

    def test_login_page_has_security_headers(self):
        status, headers, _ = self._request("/login")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(headers["Content-Security-Policy"], "default-src 'self'")
        self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")

    def test_login_flow_over_tcp(self):
        cookie = self._login()
        status, _, body = self._request("/", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("Panel", body.decode())

    def test_memory_and_diagnostics_over_tcp(self):
        from urllib.parse import urlencode

        cookie = self._login()
        status, headers, page = self._request("/memoria", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        csrf = page.decode().split('name="_csrf" value="')[1].split('"')[0]
        status, _, _ = self._request(
            "/memoria/create", method="POST",
            data=urlencode({"_csrf": csrf, "content": "tcp-memory", "confirm": "yes"}).encode(),
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 303)
        status, _, page = self._request("/memoria?include_private=1", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn(b"tcp-memory", page)
        status, headers, body = self._request(
            "/memoria/export", method="POST",
            data=urlencode({"_csrf": csrf, "confirm": "yes", "include_private": "1"}).encode(),
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn(b"tcp-memory", body)
        status, _, body = self._request("/diagnostico", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("Sin medición", body.decode())

    def test_oversized_body_rejected_with_413(self):
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(MAX_BODY_BYTES + 1),
        }
        status, _, _ = self._request("/login", method="POST", data=b"", headers=headers)
        self.assertEqual(status, 413)

    def test_put_method_rejected_with_405(self):
        status, _, _ = self._request("/api/status", method="PUT", data=b"")
        self.assertEqual(status, 405)

    def test_post_json_content_type_rejected_with_415(self):
        status, _, _ = self._request(
            "/login", method="POST", data=b"{}", headers={"Content-Type": "application/json"}
        )
        self.assertEqual(status, 415)

    def test_config_post_over_tcp_persists(self):
        cookie = self._login()
        status, _, page = self._request("/config", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        html = page.decode()
        csrf = html.split('name="_csrf" value="')[1].split('"')[0]

        # Formulario completo con un cambio válido.
        fields = {
            "identity.display_name": "Personaje TCP",
            "speech.tts_voice": "es_ES-standard",
            "node.name": "Nodo",
            "node.profile": "HYBRID",
            "display.enabled": "true",
            "display.fullscreen": "true",
            "audio.capture_gain_db": "0.0",
            "audio.auto_gain_enabled": "false",
            "audio.auto_gain_target_rms": "0.12",
            "audio.max_auto_gain_db": "18.0",
            "audio.auto_gain_noise_gate_rms": "0.008",
            "audio.auto_gain_gate_hold_ms": "300.0",
            "audio.output_volume": "80",
            "audio.music_volume": "60",
            "vision.enabled": "true",
            "vision.camera_device": "/dev/video0",
            "speech.stt_engine": "mock",
            "speech.tts_engine": "mock",
            "social.default_mode": "WORKSHOP",
            "social.auto_greeting_enabled": "true",
            "social.greeting_cooldown_seconds": "300",
            "updates.channel": "beta",
        }
        from urllib.parse import urlencode

        fields["_csrf"] = csrf
        status, headers, _ = self._request(
            "/config",
            method="POST",
            data=urlencode(fields).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": cookie,
            },
        )
        self.assertEqual(status, 303)
        self.assertIn("/config?saved=1", headers.get("Location", ""))

    def test_api_status_requires_auth_over_tcp(self):
        status, _, _ = self._request("/api/status")
        self.assertEqual(status, 303)

    def test_update_status_query_reaches_app_over_tcp(self):
        cookie = self._login()

        status, _, body = self._request(
            "/api/updates/status?operation_id=operation-1",
            headers={"Cookie": cookie},
        )

        self.assertEqual(status, 404)
        self.assertIn(b'"code": "NOT_FOUND"', body)


if __name__ == "__main__":
    unittest.main()
