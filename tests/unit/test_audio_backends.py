"""Unit tests for ALSA, Vosk, Whisper, and Piper audio backend wrappers."""

import threading
from pathlib import Path
from typing import ClassVar

from ailen.audio.alsa_backend import (
    AlsaAudioInputBackend,
    AlsaAudioOutputBackend,
    AlsaDeviceEnumerator,
    AutoAlsaAudioInputBackend,
    AutoAlsaAudioOutputBackend,
)
from ailen.audio.contracts import AudioBackendHealth, AudioDevice, AudioSegment, SpeechRequest
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

    class FailedProcess:
        returncode = 1

        def communicate(self, input=None, timeout=None):  # type: ignore[no-untyped-def]
            del input, timeout
            return b"", b"bad device"

        def poll(self):  # type: ignore[no-untyped-def]
            return self.returncode

    monkeypatch.setattr(
        "ailen.audio.alsa_backend.subprocess.Popen",
        lambda *args, **kwargs: FailedProcess(),
    )
    backend = AlsaAudioOutputBackend(device="broken")
    backend.play(b"\x00\x00" * 10)
    assert backend.health().status == ServiceStatus.UNHEALTHY


def test_piper_python_chunks_are_canonical_synthesis_path(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "voice.onnx"
    model_path.write_bytes(b"model")

    class Chunk:
        sample_width = 2
        sample_rate = 16000
        sample_channels = 1
        audio_int16_bytes = b"\x01\x00" * 160

    class Voice:
        def synthesize(self, text, syn_config=None):  # type: ignore[no-untyped-def]
            del text, syn_config
            yield Chunk()

    backend = PiperTtsBackend(model_path=str(model_path))
    backend._voice = Voice()
    monkeypatch.setattr(backend, "_make_synthesis_config", lambda _request: object())

    output = backend.synthesize(SpeechRequest(text="Hola", volume=0.8))

    assert output.audio_data == b"\x01\x00" * 160
    assert output.sample_rate == 16000
    assert output.channels == 1
    assert output.duration_ms == 10.0


def test_whisper_default_binary_matches_current_cli_name() -> None:
    assert WhisperCppSttBackend().binary_path == "whisper-cli"


def test_piper_tts_backend_is_unavailable_without_model() -> None:
    backend = PiperTtsBackend(model_path="/non/existent.onnx")
    health = backend.health()
    assert health.status == ServiceStatus.DISABLED

    output = backend.synthesize(SpeechRequest(text="Hola"))
    assert output.audio_data is None
    assert output.duration_ms == 0.0


def test_piper_tts_backend_requires_python_runtime(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "voice.onnx"
    model_path.write_bytes(b"model")
    monkeypatch.setattr("ailen.audio.piper_backend.piper_runtime_available", lambda: False)
    backend = PiperTtsBackend(model_path=str(model_path))
    assert backend.health().status == ServiceStatus.DISABLED


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


def test_alsa_input_requests_frame_sized_pipewire_periods(monkeypatch) -> None:
    captured_cmd: list[str] = []

    class RunningProcess:
        stdout = object()
        stderr = None

        def poll(self):  # type: ignore[no-untyped-def]
            return None

        def terminate(self) -> None:
            return None

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            del timeout
            return 0

    def fake_popen(cmd, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        captured_cmd.extend(cmd)
        return RunningProcess()

    monkeypatch.setattr("ailen.audio.alsa_backend.shutil.which", lambda _name: "/usr/bin/arecord")
    monkeypatch.setattr("ailen.audio.alsa_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("ailen.audio.alsa_backend.time.sleep", lambda _seconds: None)

    backend = AlsaAudioInputBackend(device="pipewire", frame_ms=20.0)
    backend.start()

    assert captured_cmd[captured_cmd.index("-F") + 1] == "20000"
    assert captured_cmd[captured_cmd.index("-B") + 1] == "80000"
    backend.stop()


def test_alsa_output_preserves_stop_requested_during_process_spawn(monkeypatch) -> None:
    spawn_started = threading.Event()
    allow_spawn_to_return = threading.Event()

    class InterruptibleProcess:
        def __init__(self) -> None:
            self.returncode = None
            self.killed = False

        def communicate(self, input=None, timeout=None):  # type: ignore[no-untyped-def]
            del input, timeout
            self.returncode = -9 if self.killed else 0
            return b"", b""

        def poll(self):  # type: ignore[no-untyped-def]
            return self.returncode

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            del timeout
            return self.returncode

    process = InterruptibleProcess()

    def fake_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        spawn_started.set()
        assert allow_spawn_to_return.wait(timeout=1.0)
        return process

    monkeypatch.setattr("ailen.audio.alsa_backend.shutil.which", lambda _name: "/usr/bin/aplay")
    monkeypatch.setattr("ailen.audio.alsa_backend.subprocess.Popen", fake_popen)
    backend = AlsaAudioOutputBackend(device="pipewire")
    playback = threading.Thread(target=backend.play, args=(b"\x00\x00" * 160,))
    playback.start()
    assert spawn_started.wait(timeout=1.0)

    backend.stop()
    allow_spawn_to_return.set()
    playback.join(timeout=1.0)

    assert playback.is_alive() is False
    assert process.killed is True
    assert backend.health().detail == "Playback interrupted"


def test_alsa_output_does_not_spawn_for_already_cancelled_turn(monkeypatch) -> None:
    cancel_event = threading.Event()
    cancel_event.set()
    spawned = False

    def fake_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal spawned
        del args, kwargs
        spawned = True
        raise AssertionError("cancelled playback must not spawn aplay")

    monkeypatch.setattr("ailen.audio.alsa_backend.subprocess.Popen", fake_popen)
    backend = AlsaAudioOutputBackend(device="pipewire")

    backend.play(b"\x00\x00" * 160, cancel_event=cancel_event)

    assert spawned is False


def test_alsa_output_stop_never_waits_for_active_aplay() -> None:
    class ActiveProcess:
        returncode = None

        def __init__(self) -> None:
            self.killed = False

        def poll(self):  # type: ignore[no-untyped-def]
            return self.returncode

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            del timeout
            raise AssertionError("stop() must not wait before cancelling aplay")

    process = ActiveProcess()
    backend = AlsaAudioOutputBackend(device="pipewire")
    backend._process = process  # type: ignore[assignment]

    backend.stop()

    assert process.killed is True



def test_auto_audio_input_waits_for_hotplug_and_reopens_on_inventory_change(monkeypatch) -> None:
    class FakeEnumerator:
        def __init__(self) -> None:
            self.hardware: list[AudioDevice] = []
            self.default_route = "mic-a"

        def list_hardware_devices(self, is_input: bool) -> list[AudioDevice]:
            assert is_input is True
            return list(self.hardware)

        def get_default_route(self, is_input: bool) -> str | None:
            assert is_input is True
            return self.default_route

        def list_devices(self) -> list[AudioDevice]:
            return [AudioDevice("pipewire", "PipeWire", is_input=True, is_output=False)]

    class FakeInputBackend:
        instances: ClassVar[list["FakeInputBackend"]] = []

        def __init__(self, device: str, sample_rate: int, channels: int, frame_ms: float) -> None:
            self.device = device
            self.sample_rate = sample_rate
            self.channels = channels
            self.frame_ms = frame_ms
            self.started = False
            self.stopped = False
            self.__class__.instances.append(self)

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.stopped = True

        def read_frame(self, timeout_seconds: float = 0.1) -> bytes | None:
            del timeout_seconds
            return b"\x01\x00" * 320

        def health(self) -> AudioBackendHealth:
            return AudioBackendHealth(
                ServiceStatus.DISABLED if self.stopped else ServiceStatus.HEALTHY,
                "fake capture",
            )

    enumerator = FakeEnumerator()
    monkeypatch.setattr("ailen.audio.alsa_backend.AlsaAudioInputBackend", FakeInputBackend)
    backend = AutoAlsaAudioInputBackend(rescan_interval_seconds=0.25)
    backend._enumerator = enumerator  # type: ignore[assignment]

    backend.start()
    assert backend.active_device is None
    assert backend.health().status == ServiceStatus.DEGRADED

    enumerator.hardware = [
        AudioDevice("plughw:CARD=USB,DEV=0", "USB mic", is_input=True, is_output=False)
    ]
    backend._rescan(force=True)
    assert backend.active_device == "pipewire"
    assert backend.read_frame() == b"\x01\x00" * 320
    first = FakeInputBackend.instances[-1]

    enumerator.default_route = "mic-b"
    backend._rescan(force=True)
    assert first.stopped is True
    rerouted = FakeInputBackend.instances[-1]
    assert rerouted is not first

    enumerator.hardware.append(
        AudioDevice("plughw:CARD=USB2,DEV=0", "Second mic", is_input=True, is_output=False)
    )
    backend._rescan(force=True)
    assert rerouted.stopped is True
    assert backend.active_device == "pipewire"
    assert FakeInputBackend.instances[-1] is not rerouted

    enumerator.hardware = []
    backend._rescan(force=True)
    assert backend.active_device is None
    assert backend.health().status == ServiceStatus.DEGRADED
    assert "hot-plug" in backend.health().detail


def test_auto_audio_output_follows_playback_inventory_changes(monkeypatch) -> None:
    class FakeEnumerator:
        def __init__(self) -> None:
            self.hardware: list[AudioDevice] = []
            self.default_route = "speaker-a"

        def list_hardware_devices(self, is_input: bool) -> list[AudioDevice]:
            assert is_input is False
            return list(self.hardware)

        def get_default_route(self, is_input: bool) -> str | None:
            assert is_input is False
            return self.default_route

        def list_devices(self) -> list[AudioDevice]:
            return [AudioDevice("pipewire", "PipeWire", is_input=False, is_output=True)]

    class FakeOutputBackend:
        instances: ClassVar[list["FakeOutputBackend"]] = []

        def __init__(self, device: str) -> None:
            self.device = device
            self.stopped = False
            self.played = 0
            self.__class__.instances.append(self)

        def play(self, audio_data: bytes, sample_rate=16000, channels=1, cancel_event=None) -> None:  # type: ignore[no-untyped-def]
            del sample_rate, channels, cancel_event
            if audio_data:
                self.played += 1

        def stop(self) -> None:
            self.stopped = True

        def health(self) -> AudioBackendHealth:
            return AudioBackendHealth(ServiceStatus.HEALTHY, "fake playback")

    enumerator = FakeEnumerator()
    monkeypatch.setattr("ailen.audio.alsa_backend.AlsaAudioOutputBackend", FakeOutputBackend)
    backend = AutoAlsaAudioOutputBackend(rescan_interval_seconds=0.25)
    backend._enumerator = enumerator  # type: ignore[assignment]

    backend.play(b"\x01\x00")
    assert backend.active_device is None

    enumerator.hardware = [
        AudioDevice("plughw:CARD=Speaker,DEV=0", "speaker", is_input=False, is_output=True)
    ]
    backend.play(b"\x01\x00")
    first = FakeOutputBackend.instances[-1]
    assert backend.active_device == "pipewire"
    assert first.played == 1

    enumerator.hardware.append(
        AudioDevice("plughw:CARD=Headset,DEV=0", "headset", is_input=False, is_output=True)
    )
    backend._rescan(force=True)
    assert first.stopped is True
    assert backend.active_device == "pipewire"
    assert FakeOutputBackend.instances[-1] is not first
