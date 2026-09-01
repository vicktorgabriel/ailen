"""Web regression tests for the named AI Provider Manager."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import quote

from ailen.ai.providers import ModelCatalogSource, ProviderModelCatalog, ProviderTestResult
from ailen.ai.runtime_manager import ExternalRuntimeManager
from ailen.audio.calibration import NoiseCalibrationResult
from ailen.services.config_service import ConfigService
from ailen.services.settings_service import SettingsService
from ailen.web.app import AILENWebApp, WebRequest, _ai_hardware_tier_copy
from ailen.web.services import FakeAuthService, FakeStatusService

PASSWORD = "secreto-prueba"


def get(path: str, **kwargs: object) -> WebRequest:
    return WebRequest(method="GET", path=path, remote_addr="127.0.0.1", **kwargs)


def post(path: str, form: dict[str, str], **kwargs: object) -> WebRequest:
    body = "&".join(f"{quote(k)}={quote(v)}" for k, v in form.items()).encode()
    headers = {"content-type": "application/x-www-form-urlencoded"}
    headers.update(kwargs.pop("headers", {}))
    return WebRequest(
        method="POST",
        path=path,
        body=body,
        remote_addr="127.0.0.1",
        headers=headers,
        **kwargs,
    )


class TestAiAdmin(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.cfg_path = Path(self.tmp.name) / "ailen.toml"
        self.cfg_path.write_text("schema_version = 2\n", encoding="utf-8")
        self.auth = FakeAuthService(password=PASSWORD)
        self.cfg_svc = ConfigService(self.cfg_path)
        self.settings = SettingsService(config_service=self.cfg_svc)
        self._refresh_app()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _refresh_app(self) -> None:
        cfg = self.cfg_svc.reload()
        self.app = AILENWebApp(
            auth=self.auth,
            status=FakeStatusService(),
            settings=self.settings,
            runtime_manager=ExternalRuntimeManager.create_default(cfg),
        )

    def _login(self) -> tuple[str, str]:
        response = self.app.handle(
            post("/login", {"username": "admin", "password": PASSWORD})
        )
        cookie = response.headers["Set-Cookie"].split(";")[0]
        token = cookie.split("=")[1]
        csrf = self.auth.validate_session(token)
        assert csrf is not None
        return cookie, csrf

    def _enable_remote(
        self,
        provider_id: str = "deepseek",
        *,
        catalog_mode: str = "manual",
    ) -> None:
        cfg = self.cfg_svc.current_config
        cfg.ai.allow_remote = True
        cfg.ai.remote.enabled = True
        provider = cfg.ai.remote.providers[provider_id]
        provider.enabled = True
        provider.model = "provider-published-model"
        provider.catalog_mode = catalog_mode
        self.cfg_svc.save_config(cfg)
        self._refresh_app()

    def test_ai_page_is_named_provider_manager_without_retired_clients(self) -> None:
        cookie, _ = self._login()
        response = self.app.handle(get("/ia", headers={"cookie": cookie}))
        body = response.body.decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("Provider Manager", body)
        self.assertIn("openai_responses", body)
        self.assertIn("anthropic_messages", body)
        self.assertIn("deepseek", body)
        self.assertIn("kimi", body)
        self.assertIn("minimax", body)
        self.assertNotIn("Antigravity", body)
        self.assertNotIn("OpenCode", body)
        self.assertIn("requieren reiniciar AILEN", body)

    def test_hardware_tier_copy_is_explicitly_not_certification(self) -> None:
        badge_4gb, recommendation_4gb = _ai_hardware_tier_copy(4096)
        badge_8gb, recommendation_8gb = _ai_hardware_tier_copy(8192)
        self.assertIn("4 GB", badge_4gb)
        self.assertIn("candidato", recommendation_4gb)
        self.assertIn("sin certificar", recommendation_4gb)
        self.assertIn("8 GB", badge_8gb)
        self.assertIn("calificado", recommendation_8gb)

    def test_remote_manual_catalog_does_not_claim_live_data(self) -> None:
        self._enable_remote(catalog_mode="manual")
        cookie, csrf = self._login()
        response = self.app.handle(
            post(
                "/api/ai/models",
                {"provider": "remote:deepseek", "_csrf": csrf},
                headers={"cookie": cookie},
            )
        )
        data = json.loads(response.body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["models"], ["provider-published-model"])
        self.assertEqual(data["catalog_source"], "configured")

    def test_remote_live_catalog_uses_runtime_and_reports_provenance(self) -> None:
        self._enable_remote(catalog_mode="live")
        cookie, csrf = self._login()
        with patch(
            "ailen.ai.runtime_manager.RemoteApiRuntime.model_catalog",
            return_value=ProviderModelCatalog(
                models=["live-a", "live-b"],
                source=ModelCatalogSource.LIVE,
                detail="provider response",
            ),
        ):
            response = self.app.handle(
                post(
                    "/api/ai/models",
                    {"provider": "remote:deepseek", "_csrf": csrf},
                    headers={"cookie": cookie},
                )
            )
        data = json.loads(response.body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["models"], ["live-a", "live-b"])
        self.assertEqual(data["catalog_source"], "live")

    def test_test_provider_records_real_runtime_result_contract(self) -> None:
        self._enable_remote()
        cookie, csrf = self._login()
        with patch.object(
            self.app._runtime_manager,
            "test_connection",
            return_value=ProviderTestResult(
                ok=True,
                latency_ms=312.5,
                first_token_ms=101.0,
                response_text="OK",
                model="provider-published-model",
            ),
        ) as probe:
            response = self.app.handle(
                post(
                    "/api/ai/test-provider",
                    {"provider": "remote:deepseek", "_csrf": csrf},
                    headers={"cookie": cookie},
                )
            )
        data = json.loads(response.body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["first_text_ms"], 101.0)
        probe.assert_called_once_with(
            "remote:deepseek", prompt="Respondé solamente: OK"
        )

    def test_disabled_local_is_never_probed(self) -> None:
        cookie, csrf = self._login()
        with patch.object(self.app._runtime_manager, "test_connection") as probe:
            response = self.app.handle(
                post(
                    "/api/ai/test-provider",
                    {"provider": "local", "_csrf": csrf},
                    headers={"cookie": cookie},
                )
            )
        self.assertEqual(response.status, 409)
        probe.assert_not_called()
        self.assertIsNone(self.app._runtime_manager.get_runtime("local"))

    def test_secret_slot_comes_from_provider_config(self) -> None:
        self._enable_remote()
        cookie, csrf = self._login()
        with patch("ailen.ai.secrets.SecretResolver.save_secret") as save:
            response = self.app.handle(
                post(
                    "/api/ai/set-secret",
                    {
                        "provider": "deepseek",
                        "secret_value": "not-a-real-secret",
                        "_csrf": csrf,
                    },
                    headers={"cookie": cookie},
                )
            )
        self.assertEqual(response.status, 200)
        save.assert_called_once_with("remote_deepseek_key", "not-a-real-secret")

    def test_arbitrary_secret_slot_is_rejected(self) -> None:
        cookie, csrf = self._login()
        with patch("ailen.ai.secrets.SecretResolver.save_secret") as save:
            response = self.app.handle(
                post(
                    "/api/ai/set-secret",
                    {
                        "provider": "../../forbidden",
                        "secret_value": "value",
                        "_csrf": csrf,
                    },
                    headers={"cookie": cookie},
                )
            )
        self.assertEqual(response.status, 400)
        save.assert_not_called()

    def test_runtime_status_is_dynamic_and_requires_restart_after_save(self) -> None:
        self._enable_remote()
        cookie, csrf = self._login()
        response = self.app.handle(
            post(
                "/api/ai/runtime/status",
                {"provider": "remote:deepseek", "_csrf": csrf},
                headers={"cookie": cookie},
            )
        )
        data = json.loads(response.body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["provider_id"], "remote:deepseek")
        self.assertTrue(data["restart_required_after_save"])
        self.assertNotIn("can_login", data)

    def test_retired_cli_lifecycle_endpoints_do_not_exist(self) -> None:
        cookie, csrf = self._login()
        for path in (
            "/api/ai/runtime/login",
            "/api/ai/runtime/update",
            "/api/ai/runtime/install",
        ):
            response = self.app.handle(
                post(
                    path,
                    {"provider": "remote:openai", "_csrf": csrf},
                    headers={"cookie": cookie},
                )
            )
            self.assertIn(response.status, {404, 405})

    def test_ai_save_preserves_unrelated_boolean_settings(self) -> None:
        cookie, csrf = self._login()
        cfg = self.cfg_svc.current_config
        cfg.display.enabled = True
        cfg.vision.enabled = True
        self.cfg_svc.save_config(cfg)
        response = self.app.handle(
            post(
                "/config",
                {
                    "_csrf": csrf,
                    "section": "ai",
                    "ai.provider": "auto",
                    "ai.allow_remote": "true",
                    "ai.remote.enabled": "true",
                },
                headers={"cookie": cookie},
            )
        )
        self.assertEqual(response.status, 303)
        saved = self.cfg_svc.reload()
        self.assertTrue(saved.display.enabled)
        self.assertTrue(saved.vision.enabled)
        self.assertTrue(saved.ai.allow_remote)

    def test_personality_preview_does_not_send_private_state_remotely(self) -> None:
        cookie, csrf = self._login()
        response = self.app.handle(
            post(
                "/api/personality/simulate",
                {"prompt": "hola", "_csrf": csrf},
                headers={"cookie": cookie},
            )
        )
        data = json.loads(response.body)
        self.assertEqual(response.status, 501)
        self.assertFalse(data["ok"])
        self.assertEqual(data["status"], "not_supported")

    def test_ai_endpoints_require_csrf(self) -> None:
        cookie, _ = self._login()
        for endpoint in (
            "/api/ai/models",
            "/api/ai/test-provider",
            "/api/ai/set-secret",
            "/api/ai/runtime/status",
        ):
            response = self.app.handle(
                post(
                    endpoint,
                    {"provider": "remote:deepseek", "_csrf": "bad"},
                    headers={"cookie": cookie},
                )
            )
            self.assertEqual(response.status, 403)

    def test_audio_noise_calibration_without_capture_is_honest(self) -> None:
        cookie, csrf = self._login()
        response = self.app.handle(
            post(
                "/api/audio/calibrate-noise",
                {"_csrf": csrf},
                headers={"cookie": cookie},
            )
        )
        data = json.loads(response.body)
        self.assertEqual(response.status, 501)
        self.assertEqual(data["status"], "not_supported")
        self.assertNotIn("measured_rms", data)

    def test_audio_noise_calibration_returns_measured_agc_gate_recommendation(self) -> None:
        class Calibrator:
            def measure(self) -> NoiseCalibrationResult:
                return NoiseCalibrationResult(
                    ok=True,
                    status="measured",
                    noise_floor_rms=0.004,
                    peak_noise_rms=0.006,
                    recommended_threshold=0.009,
                    recommended_auto_gain_gate_rms=0.008,
                    frames_measured=100,
                    duration_ms=2000.0,
                )

        self.app._noise_calibrator = Calibrator()
        cookie, csrf = self._login()
        response = self.app.handle(
            post(
                "/api/audio/calibrate-noise",
                {"_csrf": csrf},
                headers={"cookie": cookie},
            )
        )
        data = json.loads(response.body)

        self.assertEqual(response.status, 200)
        self.assertEqual(data["recommended_auto_gain_gate_rms"], 0.008)
