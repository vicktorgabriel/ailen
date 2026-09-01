"""Tests de SettingsService: allowlist, validación, persistencia atómica."""

import tempfile
import unittest
from pathlib import Path

from ailen.services.config_service import ConfigService
from ailen.services.settings_service import FIELD_SPECS, SettingsService

BASE_TOML = """\
schema_version = 3
[node]
node_id = "test-node"
name = "Nodo Prueba"
[identity]
display_name = "Personaje Local"
[audio]
capture_gain_db = 0.0
input_processing_mode = "auto"
auto_gain_enabled = false
auto_gain_target_rms = 0.12
max_auto_gain_db = 18.0
auto_gain_noise_gate_rms = 0.008
auto_gain_gate_hold_ms = 300.0
output_volume = 80
music_volume = 60
"""

# Formulario completo típico (como el que envía la vista /config).
FULL_FORM: dict[str, str] = {
    "identity.display_name": "Personaje Local",
    "speech.tts_voice": "es_ES-standard",
    "node.name": "Nodo Prueba",
    "node.profile": "HYBRID",
    "display.enabled": "true",
    "display.fullscreen": "true",
    "audio.capture_gain_db": "0.0",
    "audio.input_processing_mode": "auto",
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


def full_form(**overrides: str) -> dict[str, str]:
    """Formulario completo con overrides: ``identity__display_name`` -> clave real."""
    form = dict(FULL_FORM)
    form.update({k.replace("__", "."): v for k, v in overrides.items()})
    return form


class SettingsTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg_path = Path(tmp.name) / "ailen.toml"

    def _service(self, initial: str | None = None) -> SettingsService:
        if initial is not None:
            self.cfg_path.write_text(initial, encoding="utf-8")
        return SettingsService(ConfigService(self.cfg_path))


class TestSettingsGet(SettingsTestCase):
    def test_fields_come_from_allowlist(self):
        service = self._service(BASE_TOML)
        fields = service.get_fields()
        field_keys = {field.key for field in fields}
        self.assertTrue({spec.key for spec in FIELD_SPECS} <= field_keys)

    def test_no_network_fields_editable(self):
        keys = {spec.key for spec in FIELD_SPECS}
        self.assertNotIn("web.host", keys)
        self.assertNotIn("web.port", keys)

    def test_values_reflect_config(self):
        service = self._service(BASE_TOML)
        values = {f.key: f.value for f in service.get_fields()}
        self.assertEqual(values["identity.display_name"], "Personaje Local")
        self.assertEqual(values["node.name"], "Nodo Prueba")
        self.assertEqual(values["node.profile"], "HYBRID")
        self.assertEqual(values["audio.output_volume"], "80")
        self.assertEqual(values["social.default_mode"], "WORKSHOP")
        self.assertEqual(values["updates.channel"], "beta")
        self.assertEqual(values["display.enabled"], "true")

    def test_select_fields_have_options(self):
        service = self._service(BASE_TOML)
        by_key = {f.key: f for f in service.get_fields()}
        self.assertTrue(by_key["node.profile"].options)
        self.assertTrue(by_key["speech.stt_engine"].options)
        self.assertTrue(by_key["speech.tts_engine"].options)
        self.assertTrue(by_key["updates.channel"].options)

    def test_nested_ai_fields_are_read_and_updated(self):
        service = self._service(BASE_TOML)
        values = {f.key: f.value for f in service.get_fields()}
        self.assertEqual(values["ai.local.model"], "")
        result = service.update({
            "ai.local.enabled": "true",
            "ai.local.endpoint": "http://127.0.0.1:11434/v1",
            "ai.local.model": "qwen-test:q4",
        })
        self.assertTrue(result.ok, result.errors)
        text = self.cfg_path.read_text(encoding="utf-8")
        self.assertIn('[ai.local]', text)
        self.assertIn('model = "qwen-test:q4"', text)

    def test_api_secret_fields_are_not_web_editable(self):
        keys = {spec.key for spec in FIELD_SPECS}
        self.assertNotIn("ai.cloud.api_key_env", keys)
        self.assertNotIn("ai.cloud.api_key_file", keys)


class TestSettingsUpdate(SettingsTestCase):
    def test_valid_update_persists(self):
        service = self._service(BASE_TOML)
        result = service.update(full_form(
            identity__display_name="Nuevo Nombre",
            audio__output_volume="55",
            social__default_mode="SHOP",
        ))
        self.assertTrue(result.ok, result.errors)
        text = self.cfg_path.read_text(encoding="utf-8")
        self.assertIn('display_name = "Nuevo Nombre"', text)
        self.assertIn("output_volume = 55", text)
        self.assertIn('default_mode = "SHOP"', text)

    def test_partial_update_preserves_absent_booleans(self):
        service = self._service(BASE_TOML)
        result = service.update({"identity.display_name": "Nuevo"})
        self.assertTrue(result.ok, result.errors)
        text = self.cfg_path.read_text(encoding="utf-8")
        self.assertIn('display_name = "Nuevo"', text)
        self.assertIn("enabled = true", text)
        self.assertIn("auto_greeting_enabled = true", text)

    def test_invalid_volume_rejected_and_file_untouched(self):
        service = self._service(BASE_TOML)
        before = self.cfg_path.read_text(encoding="utf-8")
        result = service.update(full_form(audio__output_volume="999"))
        self.assertFalse(result.ok)
        self.assertIn("audio.output_volume", result.errors)
        self.assertEqual(self.cfg_path.read_text(encoding="utf-8"), before)

    def test_unknown_key_rejected(self):
        service = self._service(BASE_TOML)
        before = self.cfg_path.read_text(encoding="utf-8")
        result = service.update({"web.port": "9999"})
        self.assertFalse(result.ok)
        self.assertIn("web.port", result.errors)
        self.assertIn("no permitido", result.errors["web.port"])
        self.assertEqual(self.cfg_path.read_text(encoding="utf-8"), before)

    def test_empty_display_name_rejected(self):
        service = self._service(BASE_TOML)
        before = self.cfg_path.read_text(encoding="utf-8")
        result = service.update(full_form(identity__display_name="   "))
        self.assertFalse(result.ok)
        self.assertIn("identity.display_name", result.errors)
        self.assertEqual(self.cfg_path.read_text(encoding="utf-8"), before)

    def test_invalid_select_value_rejected(self):
        service = self._service(BASE_TOML)
        result = service.update(full_form(updates__channel="hacked"))
        self.assertFalse(result.ok)
        self.assertIn("updates.channel", result.errors)

    def test_non_numeric_capture_gain_rejected(self):
        service = self._service(BASE_TOML)
        result = service.update(full_form(audio__capture_gain_db="alto"))
        self.assertFalse(result.ok)
        self.assertIn("audio.capture_gain_db", result.errors)

    def test_valid_auto_gain_noise_gate_is_persisted(self):
        service = self._service(BASE_TOML)
        result = service.update(
            full_form(
                audio__auto_gain_noise_gate_rms="0.009",
                audio__auto_gain_gate_hold_ms="250",
            )
        )
        self.assertTrue(result.ok, result.errors)
        loaded = service.get_fields()
        values = {field.key: field.value for field in loaded}
        self.assertEqual(values["audio.auto_gain_noise_gate_rms"], "0.009")
        self.assertEqual(values["audio.auto_gain_gate_hold_ms"], "250.0")

    def test_negative_cooldown_rejected(self):
        service = self._service(BASE_TOML)
        result = service.update(full_form(social__greeting_cooldown_seconds="-5"))
        self.assertFalse(result.ok)
        self.assertIn("social.greeting_cooldown_seconds", result.errors)

    def test_partial_update_does_not_require_unrelated_fields(self):
        service = self._service(BASE_TOML)
        result = service.update({"audio.output_volume": "55"})
        self.assertTrue(result.ok, result.errors)
        values = {f.key: f.value for f in service.get_fields()}
        self.assertEqual(values["audio.output_volume"], "55")
        self.assertEqual(values["updates.channel"], "beta")


if __name__ == "__main__":
    unittest.main()
