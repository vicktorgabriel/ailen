"""Tests for the web panel. Sin sockets ni Internet: se ejerce `handle()`."""

import json
import unittest
from urllib.parse import quote

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
        self.app = AILENWebApp(auth=self.auth, status=FakeStatusService())

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
        self.assertIn(b"Panel", response.body)

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

    def test_skeleton_pages(self):
        cookie = self._login_cookie()
        for path in ("/comercio", "/personalidad", "/ia", "/audio-camara", "/sistema"):
            response = self.app.handle(get(path, headers={"cookie": cookie}))
            self.assertEqual(response.status, 200, path)
            self.assertIn(b"Skeleton", response.body)

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

    def test_static_traversal_blocked(self):
        for evil in ("/static/../app.py", "/static/css/../../app.py", "/static/%2e%2e/app.py"):
            response = self.app.handle(get(evil))
            self.assertEqual(response.status, 404, evil)

    def test_static_unknown_extension(self):
        response = self.app.handle(get("/static/css/main.exe"))
        self.assertEqual(response.status, 404)


if __name__ == "__main__":
    unittest.main()
