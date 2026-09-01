"""Unit tests for AILEN CLI."""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def test_voice_calibration_lists_distance_and_processing_matrix_without_audio(self):
        with patch("sys.stdout", new=io.StringIO()) as output:
            code = main(
                [
                    "lab",
                    "calibrate-voice",
                    "--list-cases",
                    "--json",
                    "--device",
                    "pipewire:test",
                    "--distances-cm",
                    "30,75,100",
                    "--processing-profiles",
                    "raw,noise_only,full",
                    "--vad-modes",
                    "2",
                    "--silence-timeouts",
                    "500",
                    "--limit",
                    "1",
                ]
            )

        self.assertEqual(code, 0)
        matrix = json.loads(output.getvalue())
        self.assertEqual(matrix["distances_cm"], [30, 75, 100])
        self.assertEqual(
            matrix["processing_profiles"], ["raw", "noise_only", "full"]
        )
        self.assertFalse(matrix["captures_audio"])

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
schema_version = 2
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

    def test_demo_ai_does_not_invent_local_backend_when_all_ai_is_disabled(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "demo_ai.db"
            cfg_path = Path(tmp_dir) / "ailen.toml"
            cfg_path.write_text(
                f'''\
schema_version = 2
[node]
node_id = "demo-ai-disabled"
[memory]
sqlite_path = "{db_path}"
[ai]
provider = "auto"
[ai.local]
enabled = false
[ai.lan]
enabled = false
[ai.remote]
enabled = false
''',
                encoding="utf-8",
            )

            old_stdout = sys.stdout
            sys.stdout = io.StringIO()
            try:
                exit_code = main(["-c", str(cfg_path), "demo", "ai", "Hola"])
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

        self.assertEqual(exit_code, 2)
        self.assertIn("No hay backend configurado", output)
        self.assertNotIn("Respuesta simulada local", output)

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

            update_service = MagicMock()
            with (
                patch("ailen.cli.serve_web") as mocked_serve,
                patch(
                    "ailen.cli.build_update_service",
                    return_value=update_service,
                ) as mocked_build_updates,
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
            app = mocked_serve.call_args.args[0]
            self.assertIs(app._updates, update_service)
            mocked_build_updates.assert_called_once()
            _, build_kwargs = mocked_build_updates.call_args
            self.assertEqual(build_kwargs["mode"], "lab")
            self.assertTrue(build_kwargs["paths"].install_root.is_absolute())
            self.assertTrue(build_kwargs["paths"].state_root.is_absolute())
            update_service.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
