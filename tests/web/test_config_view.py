"""Tests de la vista Configuración: GET, POST con CSRF, errores, persistencia."""

import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from ailen.services.config_service import ConfigService
from ailen.services.settings_service import SettingsService
from ailen.web.app import AILENWebApp, WebRequest
from ailen.web.services import FakeAuthService, FakeStatusService

PASSWORD = "secreto-prueba"

BASE_TOML = """\
schema_version = 1
[node]
node_id = "view-node"
name = "Nodo Vista"
[identity]
display_name = "Personaje Vista"
"""


def get(path: str, **kwargs) -> WebRequest:
    return WebRequest(method="GET", path=path, remote_addr="127.0.0.1", **kwargs)


def post(path: str, form: dict[str, str], **kwargs) -> WebRequest:
    body = "&".join(f"{k}={quote(v)}" for k, v in form.items()).encode()
    return WebRequest(method="POST", path=path, body=body, remote_addr="127.0.0.1", **kwargs)


class ConfigViewTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg_path = Path(tmp.name) / "ailen.toml"
        self.cfg_path.write_text(BASE_TOML, encoding="utf-8")
        self.auth = FakeAuthService(password=PASSWORD)
        self.app = AILENWebApp(
            auth=self.auth,
            status=FakeStatusService(),
            settings=SettingsService(ConfigService(self.cfg_path)),
        )

    def _login_cookie(self) -> str:
        response = self.app.handle(post("/login", {"username": "admin", "password": PASSWORD}))
        assert response.status == 303
        return response.headers["Set-Cookie"].split(";")[0]

    def _csrf(self, cookie: str) -> str:
        html = self.app.handle(get("/", headers={"cookie": cookie})).body.decode()
        marker = 'name="_csrf" value="'
        return html.split(marker)[1].split('"')[0]


class TestConfigView(ConfigViewTestCase):
    def test_config_redirects_when_anonymous(self):
        response = self.app.handle(get("/config"))
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/login")

    def test_get_renders_fields_and_csrf(self):
        cookie = self._login_cookie()
        response = self.app.handle(get("/config", headers={"cookie": cookie}))
        self.assertEqual(response.status, 200)
        body = response.body.decode()
        self.assertIn('action="/config"', body)
        self.assertIn('name="_csrf"', body)
        self.assertIn("Personaje Vista", body)  # valor efectivo actual
        self.assertIn("Nombre visible del personaje", body)
        self.assertIn("Volumen de salida", body)
        self.assertIn("Canal de actualización", body)

    def test_nav_includes_config_link(self):
        cookie = self._login_cookie()
        response = self.app.handle(get("/", headers={"cookie": cookie}))
        self.assertIn('href="/config"', response.body.decode())

    def test_no_secrets_rendered(self):
        cookie = self._login_cookie()
        response = self.app.handle(get("/config", headers={"cookie": cookie}))
        body = response.body.decode()
        self.assertNotIn('type="password"', body)
        for needle in ("api_key", "apikey", "API_KEY", "password_hash", "AILEN_ADMIN_PASSWORD"):
            self.assertNotIn(needle, body)

    def test_post_without_csrf_rejected(self):
        cookie = self._login_cookie()
        response = self.app.handle(
            post("/config", {"identity.display_name": "X"}, headers={"cookie": cookie})
        )
        self.assertEqual(response.status, 403)
        self.assertIn("Personaje Vista", self.cfg_path.read_text(encoding="utf-8"))

    def test_post_with_bad_csrf_rejected(self):
        cookie = self._login_cookie()
        csrf = self._csrf(cookie)
        response = self.app.handle(
            post(
                "/config",
                {"_csrf": csrf + "x", "identity.display_name": "X"},
                headers={"cookie": cookie},
            )
        )
        self.assertEqual(response.status, 403)

    def test_post_valid_saves_and_redirects(self):
        cookie = self._login_cookie()
        csrf = self._csrf(cookie)
        form = {
            "_csrf": csrf,
            "identity.display_name": "Renamed",
            "speech.tts_voice": "es_MX-claude",
            "node.name": "Nodo Vista",
            "node.profile": "LOCAL",
            "display.enabled": "true",
            "audio.input_volume": "70",
            "audio.output_volume": "65",
            "audio.music_volume": "40",
            "vision.enabled": "true",
            "vision.camera_device": "/dev/video1",
            "speech.stt_engine": "vosk",
            "speech.tts_engine": "piper",
            "social.default_mode": "SHOP",
            "social.auto_greeting_enabled": "true",
            "social.greeting_cooldown_seconds": "120",
            "updates.channel": "stable",
        }
        response = self.app.handle(post("/config", form, headers={"cookie": cookie}))
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/config?saved=1")
        text = self.cfg_path.read_text(encoding="utf-8")
        self.assertIn('display_name = "Renamed"', text)
        self.assertIn('profile = "LOCAL"', text)
        self.assertIn("output_volume = 65", text)
        self.assertIn('camera_device = "/dev/video1"', text)
        self.assertIn('default_mode = "SHOP"', text)
        self.assertIn("greeting_cooldown_seconds = 120.0", text)
        self.assertIn('channel = "stable"', text)
        self.assertIn("fullscreen = false", text)

    def test_post_invalid_shows_errors_and_keeps_file(self):
        cookie = self._login_cookie()
        csrf = self._csrf(cookie)
        before = self.cfg_path.read_text(encoding="utf-8")
        form = {"_csrf": csrf, "identity.display_name": "Ok", "audio.output_volume": "1000"}
        response = self.app.handle(post("/config", form, headers={"cookie": cookie}))
        self.assertEqual(response.status, 200)
        body = response.body.decode()
        self.assertIn("No se guardó nada", body)
        self.assertIn("Máximo 100", body)
        self.assertEqual(self.cfg_path.read_text(encoding="utf-8"), before)

    def test_post_unknown_field_shows_error(self):
        cookie = self._login_cookie()
        csrf = self._csrf(cookie)
        before = self.cfg_path.read_text(encoding="utf-8")
        form = {"_csrf": csrf, "web.port": "1234"}
        response = self.app.handle(post("/config", form, headers={"cookie": cookie}))
        self.assertEqual(response.status, 200)
        self.assertIn("Campo no permitido", response.body.decode())
        self.assertEqual(self.cfg_path.read_text(encoding="utf-8"), before)

    def test_post_preserves_submitted_values_on_error(self):
        cookie = self._login_cookie()
        csrf = self._csrf(cookie)
        form = {"_csrf": csrf, "identity.display_name": "Valor Enviado", "audio.output_volume": "-1"}
        response = self.app.handle(post("/config", form, headers={"cookie": cookie}))
        self.assertIn("Valor Enviado", response.body.decode())

    def test_post_requires_login(self):
        response = self.app.handle(post("/config", {}))
        self.assertEqual(response.status, 303)

    def test_config_method_put_not_allowed(self):
        cookie = self._login_cookie()
        request = WebRequest(
            method="PUT", path="/config", remote_addr="127.0.0.1", headers={"cookie": cookie}
        )
        self.assertEqual(self.app.handle(request).status, 405)


if __name__ == "__main__":
    unittest.main()
