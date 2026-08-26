"""Unit tests for configuration loading, serialization, and validation."""

import os
import tempfile
import unittest
from pathlib import Path

from ailen.core.config import (
    AILENConfig,
    dump_config_toml,
    load_config,
    save_config,
    validate_config,
)
from ailen.domain.enums import DeviceProfile, SocialMode


class TestConfig(unittest.TestCase):
    """Test suite for AILEN configuration."""

    def test_default_config(self):
        cfg = AILENConfig()
        self.assertEqual(cfg.schema_version, 1)
        self.assertEqual(cfg.node.profile, DeviceProfile.HYBRID)
        self.assertEqual(cfg.social.default_mode, SocialMode.WORKSHOP)
        self.assertTrue(cfg.display.enabled)
        errors = validate_config(cfg)
        self.assertEqual(errors, [])

    def test_dump_and_load_toml(self):
        cfg = AILENConfig()
        cfg.node.node_id = "test-node-custom"
        cfg.node.profile = DeviceProfile.LOCAL
        cfg.social.default_mode = SocialMode.SHOP
        cfg.web.port = 9090
        cfg.network.outbound_web_enabled = True

        toml_str = dump_config_toml(cfg)
        self.assertIn('node_id = "test-node-custom"', toml_str)
        self.assertIn('port = 9090', toml_str)
        self.assertIn('[network]', toml_str)
        self.assertIn('outbound_web_enabled = true', toml_str)

        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False, mode="w", encoding="utf-8") as tmp:
            tmp.write(toml_str)
            tmp_path = tmp.name

        try:
            loaded_cfg = load_config(tmp_path)
            self.assertEqual(loaded_cfg.node.node_id, "test-node-custom")
            self.assertEqual(loaded_cfg.node.profile, DeviceProfile.LOCAL)
            self.assertEqual(loaded_cfg.social.default_mode, SocialMode.SHOP)
            self.assertEqual(loaded_cfg.web.port, 9090)
            self.assertTrue(loaded_cfg.network.outbound_web_enabled)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_nested_ai_config_round_trip(self):
        cfg = AILENConfig()
        cfg.ai.local.enabled = True
        cfg.ai.local.endpoint = "http://127.0.0.1:11434/v1"
        cfg.ai.local.model = "test-local"
        cfg.ai.local.intent_model = "test-intent"
        cfg.ai.local.intent_timeout_seconds = 4.5
        cfg.ai.lan.enabled = True
        cfg.ai.lan.endpoint = "http://192.168.1.50:8080/v1"
        cfg.ai.lan.model = "test-lan"
        cfg.ai.cloud.enabled = True
        cfg.ai.cloud.endpoint = "https://example.invalid/v1"
        cfg.ai.cloud.model = "test-cloud"
        cfg.ai.cloud.input_cost_per_million = 0.123

        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "ailen.toml"
            save_config(cfg, target)
            text = target.read_text(encoding="utf-8")
            self.assertIn("[ai.local]", text)
            self.assertIn("[ai.lan]", text)
            self.assertIn("[ai.cloud]", text)
            loaded = load_config(target)

        self.assertTrue(loaded.ai.local.enabled)
        self.assertEqual(loaded.ai.local.model, "test-local")
        self.assertEqual(loaded.ai.local.intent_model, "test-intent")
        self.assertEqual(loaded.ai.local.intent_timeout_seconds, 4.5)
        self.assertEqual(loaded.ai.lan.endpoint, "http://192.168.1.50:8080/v1")
        self.assertEqual(loaded.ai.cloud.model, "test-cloud")
        self.assertEqual(loaded.ai.cloud.input_cost_per_million, 0.123)

    def test_network_camera_config_round_trip(self):
        cfg = AILENConfig()
        cfg.vision.camera_source = "rtsp"
        cfg.vision.network_camera_enabled = True
        cfg.vision.network_camera_host = "camera.local"
        cfg.vision.network_camera_port = 554
        cfg.vision.network_camera_path = "/h264_hd.sdp"
        cfg.vision.network_camera_username = "admin"
        cfg.vision.network_camera_password_env = "AILEN_CAMERA_PASSWORD"
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "ailen.toml"
            save_config(cfg, target)
            loaded = load_config(target)
        self.assertEqual(loaded.vision.camera_source, "rtsp")
        self.assertTrue(loaded.vision.network_camera_enabled)
        self.assertEqual(loaded.vision.network_camera_host, "camera.local")
        self.assertEqual(loaded.vision.network_camera_path, "/h264_hd.sdp")
        self.assertEqual(loaded.vision.network_camera_password_env, "AILEN_CAMERA_PASSWORD")
        self.assertEqual(validate_config(loaded), [])

    def test_display_face_style_and_personality_ranges(self):
        cfg = AILENConfig()
        cfg.display.face_style = "pixel"
        self.assertEqual(validate_config(cfg), [])

        cfg.display.face_style = "hologram"
        errors = validate_config(cfg)
        self.assertTrue(any("display.face_style" in e for e in errors))

        cfg.display.face_style = "vector"
        cfg.personality.base_verbosity = 1.5
        errors = validate_config(cfg)
        self.assertTrue(any("personality.base_verbosity" in e for e in errors))

    def test_camera_source_validation(self):
        cfg = AILENConfig()
        cfg.vision.camera_source = "firewire"
        errors = validate_config(cfg)
        self.assertTrue(any("vision.camera_source" in e for e in errors))

        cfg.vision.camera_source = "rtsp"
        errors = validate_config(cfg)
        self.assertTrue(any("network_camera_enabled" in e for e in errors))

    def test_canonical_rtsp_and_interruption_config_loads(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "canonical.toml"
            target.write_text(
                '[vision]\ncamera_source = "rtsp"\nnetwork_camera_enabled = true\n'
                'network_camera_host = "camera.local"\nrtsp_transport = "tcp"\n'
                'rtsp_reconnect_after_failures = 7\n'
                '[speech]\ninterruption_enabled = true\n'
                'interruption_threshold_rms = 0.09\ninterruption_min_ms = 200\n',
                encoding="utf-8",
            )
            loaded = load_config(target)
        self.assertEqual(loaded.vision.camera_source, "rtsp")
        self.assertEqual(loaded.vision.rtsp_transport, "tcp")
        self.assertEqual(loaded.vision.rtsp_reconnect_after_failures, 7)
        self.assertTrue(loaded.speech.interruption_enabled)
        self.assertEqual(loaded.speech.interruption_min_ms, 200)

    def test_web_search_provider_validation(self):
        cfg = AILENConfig()
        cfg.network.web_search_provider = "unknown"
        cfg.network.web_search_region = ""
        errors = validate_config(cfg)
        self.assertTrue(any("network.web_search_provider" in e for e in errors))
        self.assertTrue(any("network.web_search_region" in e for e in errors))

    def test_rtsp_and_interruption_validation(self):
        cfg = AILENConfig()
        cfg.vision.rtsp_transport = "magic"
        cfg.vision.rtsp_reconnect_after_failures = 0
        cfg.speech.interruption_threshold_rms = 0.0
        cfg.speech.interruption_min_ms = 20
        errors = validate_config(cfg)
        self.assertTrue(any("vision.rtsp_transport" in e for e in errors))
        self.assertTrue(any("vision.rtsp_reconnect_after_failures" in e for e in errors))
        self.assertTrue(any("speech.interruption_threshold_rms" in e for e in errors))
        self.assertTrue(any("speech.interruption_min_ms" in e for e in errors))

    def test_enabled_ai_backend_requires_valid_endpoint_and_model(self):
        cfg = AILENConfig()
        cfg.ai.cloud.enabled = True
        cfg.ai.cloud.endpoint = "not-a-url"
        cfg.ai.cloud.model = ""
        errors = validate_config(cfg)
        self.assertTrue(any("ai.cloud.endpoint" in e for e in errors))
        self.assertTrue(any("ai.cloud.model" in e for e in errors))

    def test_validation_errors(self):
        cfg = AILENConfig()
        cfg.schema_version = 0
        cfg.node.node_id = "   "
        cfg.display.width = -100
        cfg.audio.output_volume = 150
        cfg.audio.sample_rate = 12345
        cfg.audio.channels = 5
        cfg.speech.vad_threshold = -0.5
        cfg.speech.silence_timeout_ms = -10
        cfg.vision.fps = 0
        cfg.vision.presence_confirm_seconds = -1.0
        cfg.vision.min_confidence = 2.0
        cfg.logging.level = "INVALID_LEVEL"

        errors = validate_config(cfg)
        self.assertTrue(any("schema_version" in e for e in errors))
        self.assertTrue(any("node.node_id" in e for e in errors))
        self.assertTrue(any("display width" in e for e in errors))
        self.assertTrue(any("audio.output_volume" in e for e in errors))
        self.assertTrue(any("audio.sample_rate" in e for e in errors))
        self.assertTrue(any("audio.channels" in e for e in errors))
        self.assertTrue(any("speech.vad_threshold" in e for e in errors))
        self.assertTrue(any("speech.silence_timeout_ms" in e for e in errors))
        self.assertTrue(any("vision.fps" in e for e in errors))
        self.assertTrue(any("vision.presence_confirm_seconds" in e for e in errors))
        self.assertTrue(any("min_confidence" in e for e in errors))
        self.assertTrue(any("Invalid logging level" in e for e in errors))

    def test_explicit_missing_config_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            missing = Path(tmp_dir) / "missing.toml"
            with self.assertRaises(FileNotFoundError):
                load_config(missing)

    def test_missing_env_config_fails(self):
        old_value = os.environ.get("AILEN_CONFIG")
        try:
            os.environ["AILEN_CONFIG"] = "/definitely/missing/ailen.toml"
            with self.assertRaises(FileNotFoundError):
                load_config()
        finally:
            if old_value is None:
                os.environ.pop("AILEN_CONFIG", None)
            else:
                os.environ["AILEN_CONFIG"] = old_value

    def test_save_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "sub" / "ailen.toml"
            cfg = AILENConfig()
            cfg.node.node_id = "saved-node"
            save_config(cfg, target)
            self.assertTrue(target.is_file())
            loaded = load_config(target)
            self.assertEqual(loaded.node.node_id, "saved-node")


if __name__ == "__main__":
    unittest.main()
