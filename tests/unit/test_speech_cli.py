"""Unit tests for speech and lab CLI commands."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ailen.audio.contracts import AudioDevice
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
            code = main([
                "lab", "config", "init",
                "--profile", "recycled-8gb-hybrid",
            ])
            assert code == 0
            assert mock_init.called
            assert mock_init.call_args.kwargs["profile_id"] == "recycled-8gb-hybrid"


def test_cli_lab_audio_devices_json(capsys) -> None:
    code = main(["lab", "audio-devices", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, dict)
    assert set(data) == {
        "configured_capture",
        "effective_default_capture",
        "hardware_capture",
        "hardware_playback",
        "routing_endpoints",
    }
    assert isinstance(data["hardware_capture"], list)
    assert isinstance(data["routing_endpoints"], list)

def test_cli_lab_cameras_json(capsys) -> None:
    code = main(["lab", "cameras", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list)


def test_cli_models_qualification_template_never_downloads_weights(capsys) -> None:
    with TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "candidate.json"
        code = main([
            "models",
            "qualification-template",
            "qwen3.5-0.8b-q4_0",
            "--output",
            str(output),
        ])

        assert code == 0
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["status"] == "candidate"
        assert payload["evidence"] == []
        assert "weights" not in payload
        assert "No se descargaron pesos" in capsys.readouterr().out


def test_cli_models_qualification_validate_fails_closed_for_candidate(capsys) -> None:
    with TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "candidate.json"
        assert main([
            "models",
            "qualification-template",
            "qwen3.5-0.8b-q4_0",
            "--output",
            str(output),
        ]) == 0

        code = main(["models", "qualification-validate", str(output)])

        assert code == 2
        assert "NO CALIFICADO" in capsys.readouterr().out


def test_cli_calibrate_voice_lists_real_matrix_without_opening_microphone(capsys) -> None:
    code = main(["lab", "calibrate-voice", "--list-cases", "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["vad_modes"] == [2, 3]
    assert payload["silence_timeouts_ms"] == [380, 500, 600]
    assert 10 <= len(payload["cases"]) <= 15
    assert payload["captures_audio"] is False


def test_cli_calibrate_voice_autodiscovers_bounded_unique_sources_without_device(
    capsys,
) -> None:
    sources = [
        AudioDevice(
            id="pipewire:alsa_input.usb-default",
            name="Mic principal",
            backend="pipewire",
            is_default=True,
            state="RUNNING",
            volume_percent=88.0,
            volume_db=-3.2,
        ),
        AudioDevice(
            id="pipewire:alsa_input.usb-default",
            name="Mic principal duplicado",
            backend="pipewire",
        ),
        AudioDevice(
            id="pipewire:alsa_input.usb-secondary",
            name="Mic USB secundario",
            backend="pipewire",
            state="SUSPENDED",
            volume_percent=100.0,
            volume_db=0.0,
        ),
        AudioDevice(
            id="pipewire:easyeffects_source",
            name="Fuente DSP de laboratorio",
            backend="pipewire",
            state="IDLE",
            volume_percent=42.0,
            volume_db=-22.87,
        ),
        AudioDevice(
            id="pipewire:alsa_output.monitor",
            name="Monitor de salida",
            backend="pipewire",
            is_monitor=True,
        ),
        AudioDevice(
            id="pipewire:virtual_meeting",
            name="Fuente virtual no seleccionada",
            backend="pipewire",
        ),
    ]

    class Enumerator:
        def list_pipewire_devices(self, *, is_input: bool):  # type: ignore[no-untyped-def]
            assert is_input is True
            return list(sources)

    with patch("ailen.audio.alsa_backend.AlsaDeviceEnumerator", Enumerator):
        code = main(
            ["lab", "calibrate-voice", "--list-cases", "--json", "--limit", "1"]
        )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["devices"] == [
        "default",
        "pipewire:alsa_input.usb-secondary",
        "pipewire:easyeffects_source",
    ]
    assert len(payload["devices"]) == len(set(payload["devices"]))
    assert "pipewire:alsa_output.monitor" not in payload["devices"]
    assert "pipewire:virtual_meeting" not in payload["devices"]
    observed = {
        source["id"]: source for source in payload["available_pipewire_sources"]
    }
    assert observed["pipewire:alsa_input.usb-default"] == {
        "id": "pipewire:alsa_input.usb-default",
        "name": "Mic principal",
        "default": True,
        "state": "RUNNING",
        "volume_percent": 88.0,
        "volume_db": -3.2,
        "attenuation_warning": False,
    }
    assert observed["pipewire:easyeffects_source"]["attenuation_warning"] is True


def test_cli_calibrate_voice_device_is_an_exact_manual_override(capsys) -> None:
    class Enumerator:
        def list_pipewire_devices(self, *, is_input: bool):  # type: ignore[no-untyped-def]
            assert is_input is True
            return [
                AudioDevice(
                    id="pipewire:alsa_input.auto",
                    name="Autodescubierta",
                    backend="pipewire",
                )
            ]

    with patch("ailen.audio.alsa_backend.AlsaDeviceEnumerator", Enumerator):
        code = main(
            [
                "lab",
                "calibrate-voice",
                "--device",
                "pipewire:manual",
                "--list-cases",
                "--json",
                "--limit",
                "1",
            ]
        )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["devices"] == ["pipewire:manual"]


def test_cli_calibrate_voice_lists_barge_in_phases_without_opening_audio(capsys) -> None:
    code = main(
        ["lab", "calibrate-voice", "--barge-in-only", "--list-cases", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["mode"] == "barge_in"
    assert payload["captures_audio"] is False
    assert [trial["phase"] for trial in payload["trials"]] == [
        "early",
        "middle",
        "late",
    ]
    assert payload["aec_available"] is False
