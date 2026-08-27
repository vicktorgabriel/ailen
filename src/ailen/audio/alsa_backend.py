"""ALSA-based Audio Input, Output, and Device Enumeration backends for Linux.

Uses standard Linux `arecord` and `aplay` utilities via safe subprocess invocations
without requiring heavy external C wrappers or PortAudio dependencies.
"""

import json
import logging
import os
import re
import select
import shutil
import subprocess
import threading
import time
from threading import Event

from ailen.audio.contracts import (
    AudioBackendHealth,
    AudioDevice,
    AudioDeviceEnumerator,
    AudioInputBackend,
    AudioOutputBackend,
)
from ailen.domain.enums import ServiceStatus

logger = logging.getLogger(__name__)


class AlsaDeviceEnumerator(AudioDeviceEnumerator):
    """Discovers input and output audio devices via ALSA command-line tools."""

    def list_devices(self) -> list[AudioDevice]:
        """List ALSA capture and playback devices."""
        devices: list[AudioDevice] = []

        # 1. Capture devices (arecord -L)
        if shutil.which("arecord"):
            try:
                out = subprocess.run(
                    ["arecord", "-L"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                    check=False,
                )
                if out.returncode == 0:
                    devices.extend(self._parse_alsa_lines(out.stdout, is_input=True))
            except Exception as e:  # noqa: BLE001
                logger.debug("Failed to list ALSA capture devices: %s", e)

        # 2. Playback devices (aplay -L)
        if shutil.which("aplay"):
            try:
                out = subprocess.run(
                    ["aplay", "-L"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                    check=False,
                )
                if out.returncode == 0:
                    devices.extend(self._parse_alsa_lines(out.stdout, is_input=False))
            except Exception as e:  # noqa: BLE001
                logger.debug("Failed to list ALSA playback devices: %s", e)

        return devices

    def get_default_route(self, is_input: bool) -> str | None:
        """Return the current PipeWire/Pulse default source or sink when available."""
        if not shutil.which("pactl"):
            return None
        command = "get-default-source" if is_input else "get-default-sink"
        try:
            result = subprocess.run(
                ["pactl", command],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to query default audio route: %s", exc)
            return None
        if result.returncode != 0:
            return None
        route = result.stdout.strip()
        return route or None

    def get_default_alsa_endpoint(self, is_input: bool) -> str | None:
        """Map the current PipeWire/Pulse default route to a physical ALSA endpoint."""
        route = self.get_default_route(is_input=is_input)
        if not route or not shutil.which("pactl"):
            return None
        collection = "sources" if is_input else "sinks"
        try:
            result = subprocess.run(
                ["pactl", "-f", "json", "list", collection],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to inspect default audio route properties: %s", exc)
            return None
        if result.returncode != 0:
            return None
        try:
            entries = json.loads(result.stdout)
        except (TypeError, ValueError):
            return None
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if not isinstance(entry, dict) or str(entry.get("name", "")) != route:
                continue
            properties = entry.get("properties")
            if not isinstance(properties, dict):
                return None
            card = properties.get("alsa.card", properties.get("api.alsa.pcm.card"))
            device = properties.get("alsa.device", "0")
            card_text = str(card).strip() if card is not None else ""
            device_text = str(device).strip()
            if card_text.isdigit() and device_text.isdigit():
                return f"plughw:CARD={card_text},DEV={device_text}"
            return None
        return None

    def list_hardware_devices(self, is_input: bool) -> list[AudioDevice]:
        """List physical ALSA card/device endpoints using ``-l`` rather than plugins.

        ``arecord -L``/``aplay -L`` include virtual plugins such as ``null``,
        ``pulse`` and rate converters. They are useful routing endpoints but do
        not prove that physical capture/playback hardware exists. This method
        requests the hardware list with a stable C locale and returns ``plughw``
        IDs suitable for AILEN's PCM format conversion.
        """
        binary = "arecord" if is_input else "aplay"
        if not shutil.which(binary):
            return []
        try:
            env = dict(os.environ)
            env["LC_ALL"] = "C"
            result = subprocess.run(
                [binary, "-l"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
                env=env,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to list ALSA hardware devices: %s", exc)
            return []
        if result.returncode != 0:
            return []
        return self._parse_hardware_lines(result.stdout, is_input=is_input)

    def _parse_hardware_lines(self, output: str, is_input: bool) -> list[AudioDevice]:
        """Parse stable ``arecord/aplay -l`` C-locale card/device lines."""
        devices: list[AudioDevice] = []
        pattern = re.compile(
            r"^card\s+(?P<card>\d+):\s+(?P<card_id>[^\s]+)\s+\[(?P<card_name>.*?)\],\s+"
            r"device\s+(?P<device>\d+):\s+(?P<device_name>.*?)\s+\[.*?\]$"
        )
        for raw_line in output.splitlines():
            match = pattern.match(raw_line.strip())
            if not match:
                continue
            card_id = match.group("card_id")
            device_id = match.group("device")
            endpoint = f"plughw:CARD={card_id},DEV={device_id}"
            name = f"{match.group('card_name')}, {match.group('device_name')}"
            devices.append(
                AudioDevice(
                    id=endpoint,
                    name=name,
                    is_input=is_input,
                    is_output=not is_input,
                    is_default=False,
                )
            )
        return devices

    def _parse_alsa_lines(self, output: str, is_input: bool) -> list[AudioDevice]:
        """Parse `arecord -L` or `aplay -L` output into AudioDevice list."""
        devices: list[AudioDevice] = []
        current_id = ""
        current_desc = ""

        for line in output.splitlines():
            if not line.strip():
                continue
            if not line.startswith(" ") and not line.startswith("\t"):
                if current_id:
                    devices.append(
                        AudioDevice(
                            id=current_id,
                            name=current_desc or current_id,
                            is_input=is_input,
                            is_output=not is_input,
                            is_default=(current_id == "default"),
                        )
                    )
                current_id = line.strip()
                current_desc = ""
            else:
                desc_chunk = line.strip()
                if desc_chunk:
                    current_desc = (f"{current_desc} {desc_chunk}").strip()

        if current_id:
            devices.append(
                AudioDevice(
                    id=current_id,
                    name=current_desc or current_id,
                    is_input=is_input,
                    is_output=not is_input,
                    is_default=(current_id == "default"),
                )
            )

        return devices


class AlsaAudioInputBackend(AudioInputBackend):
    """Audio capture backend using ALSA `arecord` pipe."""

    def __init__(
        self,
        device: str = "default",
        sample_rate: int = 16000,
        channels: int = 1,
        frame_ms: float = 20.0,
    ) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_ms = frame_ms

        # 16-bit mono: 2 bytes per sample
        samples_per_frame = int(sample_rate * (frame_ms / 1000.0))
        self.frame_bytes_size = samples_per_frame * channels * 2

        self._process: subprocess.Popen[bytes] | None = None
        self._running = False
        self._health_status = ServiceStatus.UNKNOWN
        self._health_detail = "Uninitialized"

    def start(self) -> None:
        """Start capturing audio stream from arecord."""
        if self._running:
            return

        backend_name = "arecord"
        if self.device == "pipewire":
            binary = shutil.which("pw-record")
            if not binary:
                self._health_status = ServiceStatus.DISABLED
                self._health_detail = "pw-record binary not found"
                logger.info("pw-record binary not found; PipeWire audio input disabled.")
                return
            backend_name = "pw-record"
            cmd = [
                binary,
                "--raw",
                "--format", "s16",
                "--rate", str(self.sample_rate),
                "--channels", str(self.channels),
                "--latency", f"{max(20, round(self.frame_ms * 2))}ms",
                "-",
            ]
        else:
            binary = shutil.which("arecord")
            if not binary:
                self._health_status = ServiceStatus.DISABLED
                self._health_detail = "arecord binary not found (alsa-utils not installed)"
                logger.info("arecord binary not found; ALSA audio input disabled.")
                return
            cmd = [
                binary,
                "-q",
                "-D",
                self.device,
                "-r",
                str(self.sample_rate),
                "-c",
                str(self.channels),
                "-f",
                "S16_LE",
                "-F",
                str(max(1_000, round(self.frame_ms * 1_000.0))),
                "-B",
                str(max(4_000, round(self.frame_ms * 4_000.0))),
                "-t",
                "raw",
            ]

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=self.frame_bytes_size * 4,
            )
            # arecord may fail immediately after Popen for an invalid/busy ALSA
            # endpoint. Give it a short probe window before reporting HEALTHY.
            time.sleep(0.05)
            return_code = self._process.poll()
            if return_code is not None:
                stderr = b""
                if self._process.stderr is not None:
                    stderr = self._process.stderr.read()
                detail = stderr.decode("utf-8", errors="replace").strip()
                self._process = None
                self._running = False
                self._health_status = ServiceStatus.UNHEALTHY
                self._health_detail = (
                    f"{backend_name} failed for {self.device} (code {return_code})"
                    + (f": {detail}" if detail else "")
                )
                return
            self._running = True
            self._health_status = ServiceStatus.HEALTHY
            self._health_detail = (
                f"Recording via {backend_name} from {self.device} @ {self.sample_rate}Hz"
            )
        except Exception as e:
            self._health_status = ServiceStatus.UNHEALTHY
            self._health_detail = f"Failed to start {backend_name}: {e}"
            logger.exception("Failed to start %s process", backend_name)

    def stop(self) -> None:
        """Stop capture process and close pipes."""
        self._running = False
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=0.5)
            except Exception as e:  # noqa: BLE001
                logger.debug("Exception terminating arecord: %s", e)
                try:
                    self._process.kill()
                except Exception as e_kill:  # noqa: BLE001
                    logger.debug("Exception killing arecord: %s", e_kill)
            self._process = None

        self._health_status = ServiceStatus.DISABLED
        self._health_detail = "Stopped"

    def read_frame(self, timeout_seconds: float = 0.1) -> bytes | None:
        """Read exactly one PCM frame (e.g. 640 bytes for 20ms @ 16kHz) from stdout."""
        if not self._running or self._process is None or self._process.stdout is None:
            return None

        try:
            ready, _, _ = select.select(
                [self._process.stdout], [], [], max(0.0, timeout_seconds)
            )
            if not ready:
                return None
            data = self._process.stdout.read(self.frame_bytes_size)
            if len(data) == self.frame_bytes_size:
                return data
            if len(data) == 0:
                return_code = self._process.poll()
                if return_code is not None:
                    self._health_status = ServiceStatus.UNHEALTHY
                    self._health_detail = f"capture process exited with code {return_code}"
                return None
            return data
        except Exception as e:  # noqa: BLE001
            logger.debug("Error reading PCM frame from arecord: %s", e)
            return None

    def health(self) -> AudioBackendHealth:
        """Return input backend health."""
        return AudioBackendHealth(status=self._health_status, detail=self._health_detail)


class AlsaAudioOutputBackend(AudioOutputBackend):
    """Cancelable playback via PipeWire when requested, otherwise ALSA ``aplay``."""

    def __init__(self, device: str = "default") -> None:
        self.device = device
        self._health_status = ServiceStatus.UNKNOWN
        self._health_detail = "Uninitialized"
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._stop_requested = False

    def _playback_command(
        self,
        *,
        is_wav: bool,
        sample_rate: int,
        channels: int,
    ) -> tuple[list[str] | None, str]:
        """Build the canonical shared/server or direct playback command."""
        if self.device == "pipewire":
            binary = shutil.which("pw-play")
            if not binary:
                return None, "pw-play"
            if is_wav:
                return [binary, "-"], "pw-play"
            return [
                binary,
                "--raw",
                "--format", "s16",
                "--rate", str(sample_rate),
                "--channels", str(channels),
                "--latency", "50ms",
                "-",
            ], "pw-play"

        binary = shutil.which("aplay")
        if not binary:
            return None, "aplay"
        if is_wav:
            return [binary, "-q", "-D", self.device, "-t", "wav"], "aplay"
        return [
            binary, "-q", "-D", self.device,
            "-r", str(sample_rate), "-c", str(channels),
            "-f", "S16_LE", "-t", "raw",
        ], "aplay"

    def play(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        channels: int = 1,
        cancel_event: Event | None = None,
    ) -> None:
        """Play PCM/WAV audio and allow ``stop()`` to cancel it concurrently."""
        if not audio_data or (cancel_event is not None and cancel_event.is_set()):
            return

        is_wav = audio_data.startswith(b"RIFF") and b"WAVE" in audio_data[:12]
        cmd, backend_name = self._playback_command(
            is_wav=is_wav,
            sample_rate=sample_rate,
            channels=channels,
        )
        if cmd is None:
            self._health_status = ServiceStatus.DISABLED
            self._health_detail = f"{backend_name} binary not found"
            return

        expected_seconds = 0.0
        if not is_wav and sample_rate > 0 and channels > 0:
            expected_seconds = len(audio_data) / float(sample_rate * channels * 2)
        timeout = min(180.0, max(30.0, expected_seconds + 15.0))
        process: subprocess.Popen[bytes] | None = None
        try:
            with self._lock:
                if cancel_event is not None and cancel_event.is_set():
                    return
                self._stop_requested = False
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            with self._lock:
                self._process = process
                stop_requested = self._stop_requested
            logger.info(
                "audio_timing stage=playback_process_registered timestamp_monotonic=%.6f "
                "backend=%s device=%s stop_requested=%s",
                time.monotonic(),
                backend_name,
                self.device,
                stop_requested,
            )
            if stop_requested and process.poll() is None:
                process.kill()
            self._health_status = ServiceStatus.HEALTHY
            self._health_detail = f"Playing via {backend_name} on {self.device}"
            _stdout, stderr = process.communicate(input=audio_data, timeout=timeout)
            with self._lock:
                interrupted = self._stop_requested
            if process.returncode != 0 and not interrupted:
                detail = (stderr or b"").decode("utf-8", errors="replace").strip()
                self._health_status = ServiceStatus.UNHEALTHY
                self._health_detail = f"{backend_name} exited with code {process.returncode}"
                logger.warning(
                    "%s exited with code %d: %s",
                    backend_name,
                    process.returncode,
                    detail,
                )
            elif interrupted:
                self._health_status = ServiceStatus.HEALTHY
                self._health_detail = "Playback interrupted"
            else:
                self._health_status = ServiceStatus.HEALTHY
                self._health_detail = f"Playback completed via {backend_name} on {self.device}"
        except subprocess.TimeoutExpired:
            if process is not None:
                process.kill()
                process.communicate()
            self._health_status = ServiceStatus.UNHEALTHY
            self._health_detail = f"{backend_name} playback timed out"
        except Exception as exc:  # noqa: BLE001
            self._health_status = ServiceStatus.UNHEALTHY
            self._health_detail = f"{backend_name} error: {exc}"
            logger.warning("%s playback error: %s", backend_name, exc)
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None

    def stop(self) -> None:
        """Cancel current playback immediately; safe when no audio is playing."""
        started = time.monotonic()
        with self._lock:
            process = self._process
            self._stop_requested = True
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError as exc:
                logger.debug("Could not stop playback process: %s", exc)
        logger.info(
            "audio_timing stage=playback_stop timestamp_monotonic=%.6f duration_ms=%.1f process_active=%s",
            started,
            (time.monotonic() - started) * 1000.0,
            process is not None,
        )

    def health(self) -> AudioBackendHealth:
        """Return output backend health."""
        if self._health_status == ServiceStatus.UNKNOWN:
            binary = "pw-play" if self.device == "pipewire" else "aplay"
            if shutil.which(binary):
                return AudioBackendHealth(
                    status=ServiceStatus.HEALTHY,
                    detail=f"{binary} available on {self.device}",
                )
            return AudioBackendHealth(
                status=ServiceStatus.DISABLED,
                detail=f"{binary} not installed",
            )
        return AudioBackendHealth(status=self._health_status, detail=self._health_detail)


class AutoAlsaAudioInputBackend(AudioInputBackend):
    """Hot-pluggable ALSA/PipeWire capture that survives device changes."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        frame_ms: float = 20.0,
        rescan_interval_seconds: float = 1.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_ms = frame_ms
        self.rescan_interval_seconds = max(0.25, rescan_interval_seconds)
        self._enumerator = AlsaDeviceEnumerator()
        self._delegate: AlsaAudioInputBackend | None = None
        self._running = False
        self._last_scan = 0.0
        self._hardware_signature: tuple[str, ...] | None = None
        self._health = AudioBackendHealth(
            status=ServiceStatus.DEGRADED,
            detail="Waiting for an audio capture device",
        )

    @property
    def active_device(self) -> str | None:
        return self._delegate.device if self._delegate is not None else None

    def start(self) -> None:
        self._running = True
        self._rescan(force=True)

    def stop(self) -> None:
        self._running = False
        self._detach()
        self._health = AudioBackendHealth(ServiceStatus.DISABLED, "Stopped")

    def read_frame(self, timeout_seconds: float = 0.1) -> bytes | None:
        if not self._running:
            return None
        self._rescan()
        delegate = self._delegate
        if delegate is None:
            time.sleep(min(max(0.0, timeout_seconds), 0.05))
            return None

        frame = delegate.read_frame(timeout_seconds)
        health = delegate.health()
        if health.status in {ServiceStatus.UNHEALTHY, ServiceStatus.DISABLED}:
            logger.info("Auto audio input lost %s: %s", delegate.device, health.detail)
            self._detach()
            self._health = AudioBackendHealth(
                ServiceStatus.DEGRADED,
                "Capture device disappeared; rescanning",
            )
        else:
            self._health = health
        return frame

    def health(self) -> AudioBackendHealth:
        if self._delegate is not None:
            return self._delegate.health()
        return self._health

    def _rescan(self, force: bool = False) -> None:
        if not self._running:
            return
        now = time.monotonic()
        if not force and now - self._last_scan < self.rescan_interval_seconds:
            return
        self._last_scan = now

        hardware = self._enumerator.list_hardware_devices(is_input=True)
        default_route = self._enumerator.get_default_route(is_input=True)
        signature = tuple(sorted(device.id for device in hardware)) + (
            (f"route:{default_route}",) if default_route else ()
        )
        inventory_changed = (
            self._hardware_signature is not None
            and signature != self._hardware_signature
        )
        self._hardware_signature = signature
        if inventory_changed and self._delegate is not None:
            logger.info("Audio capture inventory changed; reopening default route")
            self._detach()

        if self._delegate is not None:
            return
        if not hardware:
            self._health = AudioBackendHealth(
                ServiceStatus.DEGRADED,
                "No microphone detected; waiting for hot-plug",
            )
            return

        endpoint = self._select_input_endpoint(hardware, default_route=default_route)
        delegate = AlsaAudioInputBackend(
            device=endpoint,
            sample_rate=self.sample_rate,
            channels=self.channels,
            frame_ms=self.frame_ms,
        )
        delegate.start()
        health = delegate.health()
        if health.status == ServiceStatus.HEALTHY:
            self._delegate = delegate
            self._health = health
            logger.info("Auto audio input attached: %s", endpoint)
            return
        delegate.stop()
        self._health = AudioBackendHealth(
            ServiceStatus.DEGRADED,
            f"Detected capture endpoint {endpoint} but could not open it: {health.detail}",
        )

    def _select_input_endpoint(
        self,
        hardware: list[AudioDevice],
        default_route: str | None = None,
    ) -> str:
        # Prefer the shared PipeWire server when it owns the default source.
        # This keeps desktop capture non-exclusive and lets PipeWire perform
        # high-quality resampling from the microphone's native format.
        if default_route and shutil.which("pw-record"):
            return "pipewire"
        default_alsa = self._enumerator.get_default_alsa_endpoint(is_input=True)
        if default_alsa:
            return default_alsa
        routing = self._enumerator.list_devices()
        if any(device.is_input and device.id == "pipewire" for device in routing) and shutil.which("pw-record"):
            return "pipewire"
        if any(device.is_input and device.id == "default" for device in routing):
            return "default"
        return hardware[0].id

    def _detach(self) -> None:
        if self._delegate is not None:
            try:
                self._delegate.stop()
            finally:
                self._delegate = None


class AutoAlsaAudioOutputBackend(AudioOutputBackend):
    """Hot-pluggable ALSA/PipeWire playback that follows hardware changes."""

    def __init__(self, rescan_interval_seconds: float = 1.0) -> None:
        self.rescan_interval_seconds = max(0.25, rescan_interval_seconds)
        self._enumerator = AlsaDeviceEnumerator()
        self._delegate: AlsaAudioOutputBackend | None = None
        self._last_scan = 0.0
        self._hardware_signature: tuple[str, ...] | None = None
        self._health = AudioBackendHealth(
            status=ServiceStatus.DEGRADED,
            detail="Waiting for an audio playback device",
        )

    @property
    def active_device(self) -> str | None:
        return self._delegate.device if self._delegate is not None else None

    def play(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        channels: int = 1,
        cancel_event: Event | None = None,
    ) -> None:
        self._rescan(force=self._delegate is None)
        delegate = self._delegate
        if delegate is None:
            return
        delegate.play(
            audio_data,
            sample_rate=sample_rate,
            channels=channels,
            cancel_event=cancel_event,
        )
        health = delegate.health()
        if health.status == ServiceStatus.UNHEALTHY:
            logger.info("Auto audio output lost %s: %s", delegate.device, health.detail)
            self._delegate = None
            self._health = AudioBackendHealth(
                ServiceStatus.DEGRADED,
                "Playback device unavailable; rescanning",
            )
        else:
            self._health = health

    def stop(self) -> None:
        if self._delegate is not None:
            self._delegate.stop()

    def health(self) -> AudioBackendHealth:
        if self._delegate is not None:
            return self._delegate.health()
        return self._health

    def _rescan(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_scan < self.rescan_interval_seconds:
            return
        self._last_scan = now

        hardware = self._enumerator.list_hardware_devices(is_input=False)
        default_route = self._enumerator.get_default_route(is_input=False)
        signature = tuple(sorted(device.id for device in hardware)) + (
            (f"route:{default_route}",) if default_route else ()
        )
        inventory_changed = (
            self._hardware_signature is not None
            and signature != self._hardware_signature
        )
        self._hardware_signature = signature
        if inventory_changed and self._delegate is not None:
            logger.info("Audio playback inventory changed; reopening default route")
            self._delegate.stop()
            self._delegate = None

        if self._delegate is not None:
            return
        if not hardware:
            self._health = AudioBackendHealth(
                ServiceStatus.DEGRADED,
                "No playback device detected; waiting for hot-plug",
            )
            return

        default_alsa = self._enumerator.get_default_alsa_endpoint(is_input=False)
        routing = self._enumerator.list_devices()
        shared_pipewire = bool(default_route and shutil.which("pw-play")) or any(
            device.is_output and device.id == "pipewire" for device in routing
        )
        if shared_pipewire:
            endpoint = "pipewire"
        elif any(device.is_output and device.id in {"pulse", "default"} for device in routing):
            endpoint = next(
                device.id
                for device in routing
                if device.is_output and device.id in {"pulse", "default"}
            )
        elif default_alsa:
            endpoint = default_alsa
        else:
            endpoint = hardware[0].id
        self._delegate = AlsaAudioOutputBackend(device=endpoint)
        self._health = AudioBackendHealth(
            ServiceStatus.HEALTHY,
            f"Playback endpoint selected: {endpoint}",
        )
        logger.info("Auto audio output attached: %s", endpoint)
