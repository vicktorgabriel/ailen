"""Vosk-based offline Speech-to-Text (STT) backend.

Kaldi/Vosk provides streaming, lightweight offline speech recognition
ideal for resource-constrained hardware (e.g. 4 GB RAM / Celeron).
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

from ailen.audio.contracts import (
    AudioBackendHealth,
    AudioSegment,
    SttBackend,
    Transcript,
)
from ailen.domain.enums import ServiceStatus

logger = logging.getLogger(__name__)


class VoskSttBackend(SttBackend):
    """Vosk STT recognition backend."""

    def __init__(
        self,
        model_path: str = "",
        sample_rate: int = 16000,
    ) -> None:
        self.model_path = model_path
        self.sample_rate = sample_rate

        self._model: Any = None
        self._health_status = ServiceStatus.UNKNOWN
        self._health_detail = "Uninitialized"
        self._vosk_module: Any = None

    def _init_model(self) -> bool:
        """Attempt to load Vosk and the model directory."""
        if self._model is not None:
            return True

        try:
            import vosk  # type: ignore[import-not-found,import-untyped]
            self._vosk_module = vosk
            # Suppress noisy Vosk C logs to stderr
            vosk.SetLogLevel(-1)
        except ImportError:
            self._health_status = ServiceStatus.DISABLED
            self._health_detail = "vosk not installed (optional dependency [stt-vosk])"
            logger.info("Vosk not installed; STT backend disabled.")
            return False
        except Exception as e:  # noqa: BLE001
            self._health_status = ServiceStatus.UNHEALTHY
            self._health_detail = f"Failed to import vosk: {e}"
            return False

        if not self.model_path or not Path(self.model_path).exists():
            self._health_status = ServiceStatus.DISABLED
            self._health_detail = (
                f"Vosk model path missing or not found: {self.model_path or '<empty>'}"
            )
            return False

        try:
            self._model = self._vosk_module.Model(self.model_path)
            self._health_status = ServiceStatus.HEALTHY
            self._health_detail = f"Model loaded from {self.model_path}"
            return True
        except Exception as e:
            self._health_status = ServiceStatus.UNHEALTHY
            self._health_detail = f"Failed to load Vosk model: {e}"
            logger.exception("Failed to load Vosk model from %s", self.model_path)
            return False

    def health(self) -> AudioBackendHealth:
        """Return current Vosk backend health."""
        if self._health_status == ServiceStatus.UNKNOWN:
            self._init_model()
        return AudioBackendHealth(status=self._health_status, detail=self._health_detail)

    def transcribe(self, segment: AudioSegment) -> Transcript:
        """Transcribe an AudioSegment to text."""
        start_t = time.monotonic()

        if not segment.data:
            return Transcript(text="", confidence=0.0, latency_ms=0.0)

        if not self._init_model() or self._model is None:
            return Transcript(text="", confidence=0.0, latency_ms=0.0)

        try:
            rec = self._vosk_module.KaldiRecognizer(self._model, segment.sample_rate)
            rec.AcceptWaveform(segment.data)
            res = json.loads(rec.FinalResult())
            text = res.get("text", "").strip()

            latency_ms = (time.monotonic() - start_t) * 1000.0
            return Transcript(
                text=text,
                language="es",
                confidence=None,
                latency_ms=latency_ms,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Vosk transcription error: %s", e)
            return Transcript(
                text="",
                confidence=0.0,
                latency_ms=(time.monotonic() - start_t) * 1000.0,
            )
