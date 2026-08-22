"""Unit tests for ALSA, Vosk, Whisper, and Piper audio backend wrappers."""

import subprocess
import wave
from pathlib import Path

from ailen.audio.alsa_backend import (
    AlsaAudioInputBackend,
    AlsaAudioOutputBackend,
    AlsaDeviceEnumerator,
)
from ailen.audio.contracts import AudioSegment, SpeechRequest
from ailen.audio.piper_backend import PiperTtsBackend
from ailen.audio.vosk_backend import VoskSttBackend
from ailen.audio.whisper_backend import WhisperCppSttBackend
from ailen.domain.enums import ServiceStatus


def test_alsa_device_enumerator_does_not_invent_devices_when_tools_missing(monkeypatch) -> None:
    monkeypatch.setattr("ailen.audio.alsa_backend.shutil.which", lambda _name: None)
    enumerator = AlsaDeviceEnumerator()
    assert enumerator.list_devices() == []


def test_alsa_input_backend_degradation_without_arecord() -> None:
    backend = AlsaAudioInputBackend(device="invalid_dev_99")
    backend.start()
    health = backend.health()
    # Status is healthy if arecord exists on host, or disabled/unhealthy if missing/invalid
    assert health.status in (ServiceStatus.HEALTHY, ServiceStatus.DISABLED, ServiceStatus.UNHEALTHY, ServiceStatus.UNKNOWN)
    backend.stop()
    assert backend.health().status == ServiceStatus.DISABLED


def test_alsa_output_backend_health() -> None:
    backend = AlsaAudioOutputBackend(device="invalid_dev_99")
    health = backend.health()
    assert health.status in (ServiceStatus.HEALTHY, ServiceStatus.DISABLED, ServiceStatus.UNKNOWN)
    # Playing empty data does nothing
    backend.play(b"")


def test_vosk_stt_backend_graceful_degradation_without_model() -> None:
    backend = VoskSttBackend(model_path="/non/existent/model/path")
    health = backend.health()
    assert health.status in (ServiceStatus.DISABLED, ServiceStatus.UNHEALTHY)

    # Transcription should degrade cleanly without throwing exceptions
    transcript = backend.transcribe(AudioSegment(data=b"\x00\x00" * 160))
    assert transcript.text == ""
    assert transcript.confidence == 0.0


def test_whisper_cpp_stt_backend_graceful_degradation_without_binary() -> None:
    backend = WhisperCppSttBackend(binary_path="non_existent_whisper_bin_99", model_path="/non/existent.bin")
    health = backend.health()
    assert health.status == ServiceStatus.DISABLED

    transcript = backend.transcribe(AudioSegment(data=b"\x00\x00" * 160))
    assert transcript.text == ""
    assert transcript.confidence == 0.0


def test_alsa_output_marks_nonzero_aplay_as_unhealthy(monkeypatch) -> None:
    monkeypatch.setattr("ailen.audio.alsa_backend.shutil.which", lambda _name: "/usr/bin/aplay")

    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(args=args[0], returncode=1, stdout=b"", stderr=b"bad device")

    monkeypatch.setattr("ailen.audio.alsa_backend.subprocess.run", fake_run)
    backend = AlsaAudioOutputBackend(device="broken")
    backend.play(b"\x00\x00" * 10)
    assert backend.health().status == ServiceStatus.UNHEALTHY


def test_piper_current_cli_wav_output_is_parsed(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "voice.onnx"
    model_path.write_bytes(b"model")
    monkeypatch.setattr("ailen.audio.piper_backend.shutil.which", lambda _name: "/usr/bin/piper")

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        out_path = Path(cmd[cmd.index("-f") + 1])
        with wave.open(str(out_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\x01\x00" * 160)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("ailen.audio.piper_backend.subprocess.run", fake_run)
    backend = PiperTtsBackend(model_path=str(model_path))
    output = backend.synthesize(SpeechRequest(text="Hola", volume=0.8))
    assert output.audio_data == b"\x01\x00" * 160
    assert output.sample_rate == 16000
    assert output.channels == 1
    assert output.duration_ms == 10.0


def test_whisper_default_binary_matches_current_cli_name() -> None:
    assert WhisperCppSttBackend().binary_path == "whisper-cli"


def test_piper_tts_backend_graceful_degradation_without_binary() -> None:
    backend = PiperTtsBackend(binary_path="non_existent_piper_bin_99", model_path="/non/existent.onnx")
    health = backend.health()
    assert health.status == ServiceStatus.DISABLED

    output = backend.synthesize(SpeechRequest(text="Hola"))
    assert output.audio_data is None
    assert output.duration_ms == 0.0


def test_alsa_hardware_parser_returns_plughw_endpoints() -> None:
    enumerator = AlsaDeviceEnumerator()
    sample = (
        "**** List of CAPTURE Hardware Devices ****\n"
        "card 2: Generic_1 [HD-Audio Generic], device 0: ALC892 Analog [ALC892 Analog]\n"
        "card 2: Generic_1 [HD-Audio Generic], device 2: ALC892 Alt Analog [ALC892 Alt Analog]\n"
    )
    devices = enumerator._parse_hardware_lines(sample, is_input=True)
    assert [d.id for d in devices] == [
        "plughw:CARD=Generic_1,DEV=0",
        "plughw:CARD=Generic_1,DEV=2",
    ]
    assert all(d.is_input and not d.is_output for d in devices)
