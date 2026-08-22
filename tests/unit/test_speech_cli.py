"""Unit tests for speech and lab CLI commands."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ailen.cli import main


def test_cli_speech_list_json(capsys) -> None:
    code = main(["speech", "list", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert len(data) >= 8
    asset_ids = [d["asset_id"] for d in data]
    assert "vosk-model-small-es-0.42" in asset_ids
    assert "es_ES-davefx-medium" in asset_ids

def test_cli_speech_plan_json(capsys) -> None:
    code = main(["speech", "plan", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "stt" in data
    assert "tts" in data
    assert data["stt"]["engine"] == "vosk"
    assert data["tts"]["engine"] == "piper"


def test_cli_lab_config_init() -> None:
    with TemporaryDirectory() as tmpdir:
        out_cfg = Path(tmpdir) / "test_lab.toml"
        with patch("ailen.runtime.lab_config.init_lab_config", return_value=(out_cfg, True)) as mock_init:
            code = main(["lab", "config", "init"])
            assert code == 0
            assert mock_init.called


def test_cli_lab_audio_devices_json(capsys) -> None:
    code = main(["lab", "audio-devices", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, dict)
    assert set(data) == {"hardware_capture", "hardware_playback", "routing_endpoints"}
    assert isinstance(data["hardware_capture"], list)
    assert isinstance(data["routing_endpoints"], list)

def test_cli_lab_cameras_json(capsys) -> None:
    code = main(["lab", "cameras", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list)
