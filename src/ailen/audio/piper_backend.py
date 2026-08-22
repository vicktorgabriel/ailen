"""Piper-based offline Text-to-Speech (TTS) backend.

Wraps the current Piper CLI using safe argv execution. Piper remains an optional
external component: AILEN Core does not depend on it being installed.
"""

import logging
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

from ailen.audio.contracts import (
    AudioBackendHealth,
    SpeechOutput,
    SpeechRequest,
    TtsBackend,
)
from ailen.domain.enums import ServiceStatus

logger = logging.getLogger(__name__)


def resolve_piper_executable(binary_path: str = "piper") -> str | None:
    """Resolve Piper from an explicit path, PATH, or the active Python environment."""
    configured = Path(binary_path)
    if configured.is_file():
        return str(configured)

    resolved = shutil.which(binary_path)
    if resolved:
        return resolved

    # When AILEN is invoked directly as .venv/bin/ailen, the venv's bin
    # directory is not guaranteed to be on PATH. Prefer its sibling executable
    # before declaring Piper unavailable.
    if not configured.parent.parts or str(configured.parent) == ".":
        # Do not resolve sys.executable here: virtualenv Python is commonly a
        # symlink to /usr/bin/python, while console scripts such as `piper` live
        # next to the venv launcher in .venv/bin.
        sibling = Path(sys.executable).absolute().with_name(configured.name)
        if sibling.is_file():
            return str(sibling)
    return None


class PiperTtsBackend(TtsBackend):
    """Piper TTS backend using the local command-line executable."""

    def __init__(
        self,
        binary_path: str = "piper",
        model_path: str = "",
        config_path: str = "",
    ) -> None:
        self.binary_path = binary_path
        self.model_path = model_path
        self.config_path = config_path
        self._resolved_binary: str | None = None
        self._health_status = ServiceStatus.UNKNOWN
        self._health_detail = "Uninitialized"

    def _resolve_binary(self) -> str | None:
        return resolve_piper_executable(self.binary_path)

    def _check_availability(self) -> bool:
        """Check if Piper binary and ONNX model are available."""
        self._resolved_binary = self._resolve_binary()
        if not self._resolved_binary:
            self._health_status = ServiceStatus.DISABLED
            self._health_detail = f"Piper binary not found: {self.binary_path}"
            return False

        if not self.model_path or not Path(self.model_path).is_file():
            self._health_status = ServiceStatus.DISABLED
            self._health_detail = (
                f"Piper ONNX model file not found: {self.model_path or '<empty>'}"
            )
            return False

        self._health_status = ServiceStatus.HEALTHY
        self._health_detail = f"Piper ready (model: {Path(self.model_path).name})"
        return True

    def health(self) -> AudioBackendHealth:
        self._check_availability()
        return AudioBackendHealth(status=self._health_status, detail=self._health_detail)

    def synthesize(self, request: SpeechRequest) -> SpeechOutput:
        """Synthesize text and return canonical 16-bit PCM extracted from Piper WAV output."""
        start_t = time.monotonic()
        if not request.text.strip():
            return SpeechOutput(audio_data=b"", duration_ms=0.0, latency_ms=0.0)

        if not self._check_availability() or self._resolved_binary is None:
            return SpeechOutput(audio_data=None, duration_ms=0.0, latency_ms=0.0)

        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                temp_path = tmp.name

            cmd = [
                self._resolved_binary,
                "-m",
                self.model_path,
                "-f",
                temp_path,
            ]
            if self.config_path and Path(self.config_path).is_file():
                cmd.extend(["-c", self.config_path])
            if request.rate != 1.0:
                length_scale = 1.0 / max(0.2, min(3.0, request.rate))
                cmd.extend(["--length-scale", f"{length_scale:.3f}"])
            if request.volume != 1.0:
                cmd.extend(["--volume", f"{max(0.0, min(2.0, request.volume)):.3f}"])

            result = subprocess.run(
                cmd,
                input=(request.text.strip() + "\n").encode("utf-8"),
                capture_output=True,
                timeout=30.0,
                check=False,
            )
            latency_ms = (time.monotonic() - start_t) * 1000.0
            if result.returncode != 0:
                self._health_status = ServiceStatus.UNHEALTHY
                stderr = result.stderr.decode("utf-8", errors="replace").strip()
                self._health_detail = f"Piper exited with code {result.returncode}"
                logger.warning("Piper exited with code %d: %s", result.returncode, stderr)
                return SpeechOutput(audio_data=None, latency_ms=latency_ms)

            with wave.open(temp_path, "rb") as wav_file:
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate()
                frame_count = wav_file.getnframes()
                pcm = wav_file.readframes(frame_count)

            if sample_width != 2:
                self._health_status = ServiceStatus.UNHEALTHY
                self._health_detail = f"Unsupported Piper sample width: {sample_width * 8}-bit"
                return SpeechOutput(audio_data=None, latency_ms=latency_ms)

            duration_ms = (frame_count / sample_rate * 1000.0) if sample_rate > 0 else 0.0
            self._health_status = ServiceStatus.HEALTHY
            self._health_detail = f"Piper ready (model: {Path(self.model_path).name})"
            return SpeechOutput(
                audio_data=pcm,
                sample_rate=sample_rate,
                channels=channels,
                duration_ms=duration_ms,
                latency_ms=latency_ms,
            )
        except (subprocess.TimeoutExpired, OSError, wave.Error) as exc:
            self._health_status = ServiceStatus.UNHEALTHY
            self._health_detail = f"Piper synthesis failed: {exc}"
            logger.warning("Piper synthesis failed: %s", exc)
            return SpeechOutput(
                audio_data=None,
                duration_ms=0.0,
                latency_ms=(time.monotonic() - start_t) * 1000.0,
            )
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except OSError as exc:
                    logger.debug("Failed to remove Piper temp file %s: %s", temp_path, exc)
