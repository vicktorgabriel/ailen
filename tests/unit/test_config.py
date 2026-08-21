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

        toml_str = dump_config_toml(cfg)
        self.assertIn('node_id = "test-node-custom"', toml_str)
        self.assertIn('port = 9090', toml_str)

        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False, mode="w", encoding="utf-8") as tmp:
            tmp.write(toml_str)
            tmp_path = tmp.name

        try:
            loaded_cfg = load_config(tmp_path)
            self.assertEqual(loaded_cfg.node.node_id, "test-node-custom")
            self.assertEqual(loaded_cfg.node.profile, DeviceProfile.LOCAL)
            self.assertEqual(loaded_cfg.social.default_mode, SocialMode.SHOP)
            self.assertEqual(loaded_cfg.web.port, 9090)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_validation_errors(self):
        cfg = AILENConfig()
        cfg.schema_version = 0
        cfg.node.node_id = "   "
        cfg.display.width = -100
        cfg.audio.output_volume = 150
        cfg.vision.fps = 0
        cfg.vision.presence_debounce_seconds = -1.0
        cfg.vision.min_confidence = 2.0
        cfg.logging.level = "INVALID_LEVEL"

        errors = validate_config(cfg)
        self.assertTrue(any("schema_version" in e for e in errors))
        self.assertTrue(any("node.node_id" in e for e in errors))
        self.assertTrue(any("display width" in e for e in errors))
        self.assertTrue(any("audio.output_volume" in e for e in errors))
        self.assertTrue(any("vision.fps" in e for e in errors))
        self.assertTrue(any("presence_debounce" in e for e in errors))
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
