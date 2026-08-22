"""ALSA-based Audio Input, Output, and Device Enumeration backends for Linux.

Uses standard Linux `arecord` and `aplay` utilities via safe subprocess invocations
without requiring heavy external C wrappers or PortAudio dependencies.
"""

import logging
import os
import re
import select
import shutil
import subprocess

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

        if not shutil.which("arecord"):
            self._health_status = ServiceStatus.DISABLED
            self._health_detail = "arecord binary not found (alsa-utils not installed)"
            logger.info("arecord binary not found; ALSA audio input disabled.")
            return

        cmd = [
            "arecord",
            "-q",
            "-D",
            self.device,
            "-r",
            str(self.sample_rate),
            "-c",
            str(self.channels),
            "-f",
            "S16_LE",
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
            self._running = True
            self._health_status = ServiceStatus.HEALTHY
            self._health_detail = f"Recording from {self.device} @ {self.sample_rate}Hz"
        except Exception as e:
            self._health_status = ServiceStatus.UNHEALTHY
            self._health_detail = f"Failed to start arecord: {e}"
            logger.exception("Failed to start arecord process")

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
                    self._health_detail = f"arecord exited with code {return_code}"
                return None
            return data
        except Exception as e:  # noqa: BLE001
            logger.debug("Error reading PCM frame from arecord: %s", e)
            return None

    def health(self) -> AudioBackendHealth:
        """Return input backend health."""
        return AudioBackendHealth(status=self._health_status, detail=self._health_detail)


class AlsaAudioOutputBackend(AudioOutputBackend):
    """Audio playback backend using ALSA `aplay`."""

    def __init__(self, device: str = "default") -> None:
        self.device = device
        self._health_status = ServiceStatus.UNKNOWN
        self._health_detail = "Uninitialized"

    def play(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> None:
        """Play PCM audio data using aplay."""
        if not audio_data:
            return

        if not shutil.which("aplay"):
            self._health_status = ServiceStatus.DISABLED
            self._health_detail = "aplay binary not found (alsa-utils not installed)"
            logger.info("aplay binary not found; ALSA playback skipped.")
            return

        is_wav = audio_data.startswith(b"RIFF") and b"WAVE" in audio_data[:12]

        if is_wav:
            cmd = ["aplay", "-q", "-D", self.device, "-t", "wav"]
        else:
            cmd = [
                "aplay",
                "-q",
                "-D",
                self.device,
                "-r",
                str(sample_rate),
                "-c",
                str(channels),
                "-f",
                "S16_LE",
                "-t",
                "raw",
            ]

        try:
            self._health_status = ServiceStatus.HEALTHY
            self._health_detail = f"Playing on {self.device}"
            result = subprocess.run(
                cmd,
                input=audio_data,
                capture_output=True,
                timeout=30.0,
                check=False,
            )
            if result.returncode != 0:
                self._health_status = ServiceStatus.UNHEALTHY
                stderr = result.stderr.decode("utf-8", errors="replace").strip()
                self._health_detail = f"aplay exited with code {result.returncode}"
                logger.warning("aplay exited with code %d: %s", result.returncode, stderr)
        except Exception as e:  # noqa: BLE001
            self._health_status = ServiceStatus.UNHEALTHY
            self._health_detail = f"aplay error: {e}"
            logger.warning("aplay playback error: %s", e)

    def stop(self) -> None:
        """Stop current playback."""
        # For aplay one-shot subprocess, stop is a no-op / reset

    def health(self) -> AudioBackendHealth:
        """Return output backend health."""
        if self._health_status == ServiceStatus.UNKNOWN:
            if shutil.which("aplay"):
                return AudioBackendHealth(
                    status=ServiceStatus.HEALTHY, detail=f"aplay available on {self.device}"
                )
            return AudioBackendHealth(
                status=ServiceStatus.DISABLED, detail="aplay not installed"
            )
        return AudioBackendHealth(status=self._health_status, detail=self._health_detail)
