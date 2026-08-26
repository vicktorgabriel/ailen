"""Canonical Piper offline Text-to-Speech backend using the piper-tts Python API."""

import importlib.util
import logging
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ailen.audio.contracts import AudioBackendHealth, SpeechOutput, SpeechRequest, TtsBackend
from ailen.audio.speech_text import normalize_text_for_speech
from ailen.domain.enums import ServiceStatus

logger = logging.getLogger(__name__)


def piper_runtime_available() -> bool:
    """Return whether the canonical piper-tts Python runtime is installed."""
    try:
        return (
            importlib.util.find_spec("piper") is not None
            and importlib.util.find_spec("piper.voice") is not None
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


class PiperTtsBackend(TtsBackend):
    """Cached PiperVoice backend with incremental sentence audio."""

    def __init__(self, model_path: str = "", config_path: str = "") -> None:
        self.model_path = model_path
        self.config_path = config_path
        self._health_status = ServiceStatus.UNKNOWN
        self._health_detail = "Uninitialized"
        self._voice: Any | None = None
        self._load_attempted = False

    def _check_availability(self) -> bool:
        if not piper_runtime_available():
            self._health_status = ServiceStatus.DISABLED
            self._health_detail = "piper-tts Python package is not installed"
            return False
        if not self.model_path or not Path(self.model_path).is_file():
            self._health_status = ServiceStatus.DISABLED
            self._health_detail = f"Piper ONNX model file not found: {self.model_path or '<empty>'}"
            return False
        if self.config_path and not Path(self.config_path).is_file():
            self._health_status = ServiceStatus.DISABLED
            self._health_detail = f"Piper voice config file not found: {self.config_path}"
            return False
        self._health_status = ServiceStatus.HEALTHY
        self._health_detail = f"Piper Python runtime ready (model: {Path(self.model_path).name})"
        return True

    def _load_voice(self) -> Any | None:
        if self._voice is not None:
            return self._voice
        if self._load_attempted:
            return None
        self._load_attempted = True
        if not self._check_availability():
            return None
        try:
            from piper.voice import PiperVoice  # type: ignore[import-untyped]

            config = self.config_path or None
            self._voice = PiperVoice.load(self.model_path, config_path=config, use_cuda=False)
            self._health_status = ServiceStatus.HEALTHY
            self._health_detail = f"Piper voice loaded (model: {Path(self.model_path).name})"
        except Exception as exc:  # noqa: BLE001
            self._voice = None
            self._health_status = ServiceStatus.UNHEALTHY
            self._health_detail = f"Piper voice load failed: {exc}"
            logger.warning("Piper voice load failed: %s", exc)
        return self._voice

    @staticmethod
    def _make_synthesis_config(request: SpeechRequest) -> Any:
        from piper.config import SynthesisConfig  # type: ignore[import-untyped]

        return SynthesisConfig(
            length_scale=(1.0 / max(0.2, min(3.0, request.rate))) if request.rate != 1.0 else None,
            volume=max(0.0, min(2.0, request.volume)),
        )

    def synthesize_chunks(self, request: SpeechRequest) -> Iterable[SpeechOutput]:
        """Yield canonical 16-bit PCM chunks directly from the cached PiperVoice."""
        clean_text = normalize_text_for_speech(request.text)
        if not clean_text:
            return
        voice = self._load_voice()
        if voice is None:
            return

        start_t = time.monotonic()
        syn_config = self._make_synthesis_config(request)
        try:
            for chunk in voice.synthesize(clean_text, syn_config=syn_config):
                if chunk.sample_width != 2:
                    raise ValueError(f"Unsupported Piper sample width: {chunk.sample_width * 8}-bit")
                pcm = chunk.audio_int16_bytes
                if not pcm:
                    continue
                duration_ms = (
                    len(pcm)
                    / float(chunk.sample_rate * chunk.sample_channels * chunk.sample_width)
                    * 1000.0
                )
                yield SpeechOutput(
                    audio_data=pcm,
                    sample_rate=chunk.sample_rate,
                    channels=chunk.sample_channels,
                    duration_ms=duration_ms,
                    latency_ms=(time.monotonic() - start_t) * 1000.0,
                )
            self._health_status = ServiceStatus.HEALTHY
            self._health_detail = f"Piper voice active (model: {Path(self.model_path).name})"
        except Exception as exc:  # noqa: BLE001
            self._health_status = ServiceStatus.UNHEALTHY
            self._health_detail = f"Piper synthesis failed: {exc}"
            logger.warning("Piper synthesis failed: %s", exc)

    def synthesize(self, request: SpeechRequest) -> SpeechOutput:
        """Aggregate the same canonical streaming path into one SpeechOutput."""
        chunks = list(self.synthesize_chunks(request))
        if not chunks:
            return SpeechOutput(audio_data=None, duration_ms=0.0, latency_ms=0.0)
        sample_rate = chunks[0].sample_rate
        channels = chunks[0].channels
        if any(chunk.sample_rate != sample_rate or chunk.channels != channels for chunk in chunks):
            self._health_status = ServiceStatus.UNHEALTHY
            self._health_detail = "Piper returned inconsistent audio formats across chunks"
            return SpeechOutput(audio_data=None, duration_ms=0.0, latency_ms=chunks[0].latency_ms)
        return SpeechOutput(
            audio_data=b"".join(chunk.audio_data or b"" for chunk in chunks),
            sample_rate=sample_rate,
            channels=channels,
            duration_ms=sum(chunk.duration_ms for chunk in chunks),
            latency_ms=chunks[0].latency_ms,
        )

    def warmup(self) -> bool:
        """Load and cache the configured voice before the first spoken turn."""
        return self._load_voice() is not None

    def health(self) -> AudioBackendHealth:
        self._check_availability()
        return AudioBackendHealth(status=self._health_status, detail=self._health_detail)
