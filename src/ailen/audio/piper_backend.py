"""Canonical Piper offline Text-to-Speech backend using the piper-tts Python API."""

import importlib.util
import json
import logging
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ailen.audio.contracts import AudioBackendHealth, SpeechOutput, SpeechRequest, TtsBackend
from ailen.audio.speech_text import split_speech_for_streaming
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

    def __init__(
        self,
        model_path: str = "",
        config_path: str = "",
        threads: int = 0,
    ) -> None:
        self.model_path = model_path
        self.config_path = config_path
        self.threads = max(0, threads)
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
            if self.threads > 0:
                self._voice = self._load_threaded_voice()
            else:
                self._voice = PiperVoice.load(self.model_path, config_path=config, use_cuda=False)
            self._health_status = ServiceStatus.HEALTHY
            self._health_detail = f"Piper voice loaded (model: {Path(self.model_path).name})"
        except Exception as exc:  # noqa: BLE001
            self._voice = None
            self._health_status = ServiceStatus.UNHEALTHY
            self._health_detail = f"Piper voice load failed: {exc}"
            logger.warning("Piper voice load failed: %s", exc)
        return self._voice

    def _load_threaded_voice(self) -> Any:
        """Load Piper with an explicit ONNX CPU thread count for slower recycled CPUs."""
        import onnxruntime as ort  # type: ignore[import-untyped]
        from piper.config import PiperConfig  # type: ignore[import-untyped]
        from piper.voice import ESPEAK_DATA_DIR, PiperVoice  # type: ignore[import-untyped]

        config_path = self.config_path or f"{self.model_path}.json"
        config_dict = json.loads(Path(config_path).read_text(encoding="utf-8"))
        session_options = ort.SessionOptions()
        session_options.intra_op_num_threads = self.threads
        session_options.inter_op_num_threads = 1
        session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        session = ort.InferenceSession(
            self.model_path,
            sess_options=session_options,
            providers=["CPUExecutionProvider"],
        )
        return PiperVoice(
            session=session,
            config=PiperConfig.from_dict(config_dict),
            espeak_data_dir=Path(ESPEAK_DATA_DIR),
        )

    @staticmethod
    def _make_synthesis_config(request: SpeechRequest) -> Any:
        """Translate bounded affect into subtle Piper prosody changes.

        Values stay close to the common Piper Spanish defaults (noise_scale≈0.667,
        noise_w≈0.8). The goal is audible mood, not voice distortion.
        """
        from piper.config import SynthesisConfig  # type: ignore[import-untyped]

        emotion = request.emotion.strip().lower()
        expressiveness = max(0.0, min(1.0, request.expressiveness))
        # rate multiplier, noise_scale target, noise_w target, volume multiplier
        profiles: dict[str, tuple[float, float, float, float]] = {
            "neutral": (1.00, 0.667, 0.80, 1.00),
            "happy": (1.04, 0.71, 0.84, 1.02),
            "curious": (1.02, 0.70, 0.84, 1.00),
            "surprised": (1.07, 0.74, 0.88, 1.03),
            "confused": (0.96, 0.68, 0.82, 0.99),
            "focused": (0.97, 0.61, 0.73, 0.99),
            "sad": (0.90, 0.57, 0.68, 0.96),
            "skeptical": (0.95, 0.63, 0.76, 0.99),
            "excited": (1.10, 0.76, 0.91, 1.05),
            "playful": (1.06, 0.73, 0.88, 1.03),
        }
        target_rate, target_noise, target_noise_w, target_volume = profiles.get(
            emotion, profiles["neutral"]
        )

        # Blend toward neutral according to personality expressiveness so the
        # same affect vocabulary works from subtle to animated personalities.
        rate_mult = 1.0 + (target_rate - 1.0) * expressiveness
        noise_scale = 0.667 + (target_noise - 0.667) * expressiveness
        noise_w_scale = 0.80 + (target_noise_w - 0.80) * expressiveness
        volume_mult = 1.0 + (target_volume - 1.0) * expressiveness
        effective_rate = max(0.55, min(1.6, request.rate * rate_mult))

        return SynthesisConfig(
            length_scale=1.0 / effective_rate,
            noise_scale=max(0.45, min(0.90, noise_scale)),
            noise_w_scale=max(0.55, min(1.05, noise_w_scale)),
            volume=max(0.0, min(2.0, request.volume * volume_mult)),
        )

    def synthesize_chunks(self, request: SpeechRequest) -> Iterable[SpeechOutput]:
        """Yield canonical 16-bit PCM chunks directly from the cached PiperVoice."""
        phrases = split_speech_for_streaming(request.text)
        if not phrases:
            return
        voice = self._load_voice()
        if voice is None:
            return

        start_t = time.monotonic()
        syn_config = self._make_synthesis_config(request)
        try:
            for phrase in phrases:
                for chunk in voice.synthesize(phrase, syn_config=syn_config):
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
