"""whisper.cpp-based offline Speech-to-Text (STT) backend.

Wraps the whisper.cpp CLI binary for quantized local transformer inference.
"""

import logging
import os
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path

from ailen.audio.contracts import (
    AudioBackendHealth,
    AudioSegment,
    SttBackend,
    Transcript,
)
from ailen.domain.enums import ServiceStatus

logger = logging.getLogger(__name__)


class WhisperCppSttBackend(SttBackend):
    """whisper.cpp STT recognition backend."""

    def __init__(
        self,
        binary_path: str = "whisper-cli",
        model_path: str = "",
        language: str = "es",
        threads: int = 4,
    ) -> None:
        self.binary_path = binary_path
        self.model_path = model_path
        self.language = language
        self.threads = threads

        self._health_status = ServiceStatus.UNKNOWN
        self._health_detail = "Uninitialized"
        self._resolved_binary: str | None = None

    def _resolve_binary(self) -> str | None:
        configured = Path(self.binary_path)
        if configured.is_file():
            return str(configured)
        resolved = shutil.which(self.binary_path)
        if resolved:
            return resolved
        if self.binary_path in {"whisper-cli", "whisper-cpp", "main"}:
            for candidate in ("whisper-cli", "whisper-cpp", "main"):
                resolved = shutil.which(candidate)
                if resolved:
                    return resolved
        return None

    def _check_availability(self) -> bool:
        """Check if binary and model exist."""
        self._resolved_binary = self._resolve_binary()
        if not self._resolved_binary:
            self._health_status = ServiceStatus.DISABLED
            self._health_detail = f"whisper.cpp binary not found: {self.binary_path}"
            return False

        if not self.model_path or not Path(self.model_path).is_file():
            self._health_status = ServiceStatus.DISABLED
            self._health_detail = (
                f"whisper model file not found: {self.model_path or '<empty>'}"
            )
            return False

        self._health_status = ServiceStatus.HEALTHY
        self._health_detail = f"whisper.cpp ready (model: {Path(self.model_path).name})"
        return True

    def health(self) -> AudioBackendHealth:
        """Return backend health status."""
        self._check_availability()
        return AudioBackendHealth(status=self._health_status, detail=self._health_detail)

    def transcribe(self, segment: AudioSegment) -> Transcript:
        """Transcribe AudioSegment using whisper.cpp binary."""
        start_t = time.monotonic()

        if not segment.data:
            return Transcript(
                text="", confidence=0.0, latency_ms=0.0, engine="whisper_cpp"
            )

        if not self._check_availability() or self._resolved_binary is None:
            return Transcript(
                text="", confidence=0.0, latency_ms=0.0, engine="whisper_cpp"
            )

        binary = self._resolved_binary
        temp_wav: str | None = None
        try:
            # Write segment to temporary WAV file (16kHz 16-bit mono)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_wav = f.name
                with wave.open(temp_wav, "wb") as wf:
                    wf.setnchannels(segment.channels)
                    wf.setsampwidth(2)  # 16-bit
                    wf.setframerate(segment.sample_rate)
                    wf.writeframes(segment.data)

            cmd = [
                binary,
                "-m",
                self.model_path,
                "-l",
                self.language,
                "-t",
                str(self.threads),
                "-nt",  # no timestamps in output
                "-f",
                temp_wav,
            ]

            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15.0,
                check=False,
            )

            latency_ms = (time.monotonic() - start_t) * 1000.0
            if res.returncode == 0:
                raw_text = res.stdout.strip()
                # Clean extraneous whisper brackets / blank lines
                cleaned_lines = [
                    line.strip() for line in raw_text.splitlines() if line.strip()
                ]
                text = " ".join(cleaned_lines)
                return Transcript(
                    text=text,
                    language=self.language,
                    confidence=None,
                    latency_ms=latency_ms,
                    engine="whisper_cpp",
                )
            else:
                logger.warning("whisper.cpp exited with code %d: %s", res.returncode, res.stderr)
                return Transcript(
                    text="",
                    confidence=0.0,
                    latency_ms=latency_ms,
                    engine="whisper_cpp",
                )

        except Exception as e:  # noqa: BLE001
            logger.warning("Error running whisper.cpp: %s", e)
            return Transcript(
                text="",
                confidence=0.0,
                latency_ms=(time.monotonic() - start_t) * 1000.0,
                engine="whisper_cpp",
            )
        finally:
            if temp_wav and os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except Exception as e:  # noqa: BLE001
                    logger.debug("Failed to remove temporary WAV %s: %s", temp_wav, e)
