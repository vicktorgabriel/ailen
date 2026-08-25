"""Unit tests for AILEN CLI."""

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ailen.cli import main


class TestCLI(unittest.TestCase):
    """Test suite for AILEN command line interface."""

    def test_cli_help(self):
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            with self.assertRaises(SystemExit) as cm:
                main(["--help"])
            self.assertEqual(cm.exception.code, 0)
            output = sys.stdout.getvalue()
            self.assertIn("AILEN - Asistente físico", output)
            self.assertIn("diagnose", output)
            self.assertIn("config", output)
            self.assertIn("db", output)
        finally:
            sys.stdout = old_stdout

    def test_cli_diagnose_hardware(self):
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            exit_code = main(["diagnose", "hardware"])
            self.assertEqual(exit_code, 0)
            output = sys.stdout.getvalue()
            self.assertIn("AILEN HARDWARE REPORT", output)
        finally:
            sys.stdout = old_stdout

    def test_cli_diagnose_hardware_json(self):
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            exit_code = main(["diagnose", "hardware", "--json"])
            self.assertEqual(exit_code, 0)
            output = sys.stdout.getvalue()
            self.assertIn('"recommended_profile"', output)
            self.assertIn('"cpu"', output)
        finally:
            sys.stdout = old_stdout

    def test_cli_config_show_and_validate(self):
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            exit_code = main(["config", "show"])
            self.assertEqual(exit_code, 0)
            output = sys.stdout.getvalue()
            self.assertIn("schema_version", output)
            self.assertIn("[node]", output)

            exit_code_val = main(["config", "validate"])
            self.assertEqual(exit_code_val, 0)
        finally:
            sys.stdout = old_stdout

    def test_cli_db_status_and_migrate(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "cli_test.db"
            cfg_path = Path(tmp_dir) / "ailen.toml"
            cfg_path.write_text(
                f"""
schema_version = 1
[node]
node_id = "cli-test"
[memory]
sqlite_path = "{db_path}"
""",
                encoding="utf-8",
            )

            old_stdout = sys.stdout
            sys.stdout = io.StringIO()
            try:
                # Migrate
                code_mig = main(["-c", str(cfg_path), "db", "migrate"])
                self.assertEqual(code_mig, 0)
                out_mig = sys.stdout.getvalue()
                self.assertIn("Applied 4 migration(s)", out_mig)

                # Status
                code_stat = main(["-c", str(cfg_path), "db", "status"])
                self.assertEqual(code_stat, 0)
            finally:
                sys.stdout = old_stdout

    def test_cli_status(self):
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            exit_code = main(["status"])
            self.assertEqual(exit_code, 0)
            output = sys.stdout.getvalue()
            self.assertIn("AILEN Runtime Status", output)
        finally:
            sys.stdout = old_stdout

    def test_cli_serve_wires_web_panel(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "serve_test.db"
            cfg_path = Path(tmp_dir) / "ailen.toml"
            cfg_path.write_text(
                f'''\
schema_version = 1
[node]
node_id = "serve-test"
[memory]
sqlite_path = "{db_path}"
[web]
enabled = true
host = "127.0.0.1"
port = 8080
''',
                encoding="utf-8",
            )

            with (
                patch("ailen.cli.serve_web") as mocked_serve,
                patch.dict("os.environ", {"AILEN_ADMIN_PASSWORD": "test-secret"}),
            ):
                exit_code = main([
                    "-c",
                    str(cfg_path),
                    "serve",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "9099",
                ])

            self.assertEqual(exit_code, 0)
            mocked_serve.assert_called_once()
            _, kwargs = mocked_serve.call_args
            self.assertEqual(kwargs["host"], "127.0.0.1")
            self.assertEqual(kwargs["port"], 9099)


if __name__ == "__main__":
    unittest.main()
