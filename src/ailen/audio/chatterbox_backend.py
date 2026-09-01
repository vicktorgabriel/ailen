"""Lightweight HTTP client for an external/local Chatterbox TTS service."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from typing import ClassVar

from ailen.audio.contracts import AudioBackendHealth, SpeechOutput, SpeechRequest, TtsBackend
from ailen.audio.speech_text import split_speech_for_streaming
from ailen.domain.enums import ServiceStatus

logger = logging.getLogger(__name__)


class ChatterboxHttpTtsBackend(TtsBackend):
    """Use a persistent Chatterbox service without importing Torch into AILEN."""

    _PROFILES: ClassVar[dict[str, tuple[float, float, float, float, float]]] = {
        # exaggeration, temperature, cfg_weight, pitch_semitones, rate_factor
        "neutral": (0.50, 0.80, 0.50, 0.00, 1.00),
        "happy": (0.62, 0.82, 0.45, 0.35, 1.03),
        "curious": (0.56, 0.80, 0.50, 0.25, 1.00),
        "surprised": (0.72, 0.85, 0.38, 0.80, 1.06),
        "confused": (0.50, 0.72, 0.55, 0.10, 0.96),
        "focused": (0.42, 0.65, 0.60, -0.05, 0.98),
        "sad": (0.45, 0.68, 0.55, -0.55, 0.92),
        "skeptical": (0.48, 0.72, 0.55, -0.20, 0.96),
        "excited": (0.76, 0.88, 0.35, 0.90, 1.07),
        "playful": (0.66, 0.85, 0.40, 0.50, 1.04),
    }

    def __init__(
        self,
        endpoint: str,
        timeout_seconds: float = 6.0,
        fallback: TtsBackend | None = None,
        base_pitch_semitones: float = 0.0,
        rate_scale: float = 1.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = max(0.5, float(timeout_seconds))
        self.fallback = fallback
        self.base_pitch_semitones = max(-2.0, min(2.0, float(base_pitch_semitones)))
        self.rate_scale = max(0.85, min(1.15, float(rate_scale)))
        self._health_status = ServiceStatus.UNKNOWN
        self._health_detail = "Uninitialized"
        self._last_failure_time: float = 0.0
        self._circuit_open_seconds: float = 15.0

    @classmethod
    def _params_for_request(cls, request: SpeechRequest) -> tuple[float, float, float, float, float]:
        neutral = cls._PROFILES["neutral"]
        target = cls._PROFILES.get(request.emotion.strip().lower(), neutral)
        strength = max(0.0, min(1.0, request.expressiveness))
        values = tuple(base + (dest - base) * strength for base, dest in zip(neutral, target, strict=True))
        exaggeration, temperature, cfg_weight, pitch_semitones, rate_factor = values
        return (
            max(0.25, min(1.25, exaggeration)),
            max(0.20, min(1.20, temperature)),
            max(0.20, min(1.00, cfg_weight)),
            max(-1.5, min(1.5, pitch_semitones)),
            max(0.90, min(1.10, rate_factor)),
        )

    def _request(self, path: str, payload: dict[str, object] | None = None, timeout: float | None = None) -> bytes:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint}{path}",
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method="POST" if data is not None else "GET",
        )
        with urllib.request.urlopen(request, timeout=timeout or self.timeout_seconds) as response:
            return response.read()

    def _primary_health(self) -> AudioBackendHealth:
        try:
            payload = json.loads(self._request("/health", timeout=min(1.5, self.timeout_seconds)).decode("utf-8"))
            if payload.get("status") == "ok" and payload.get("model_loaded") is True:
                return AudioBackendHealth(ServiceStatus.HEALTHY, f"Chatterbox service ready at {self.endpoint}")
            return AudioBackendHealth(ServiceStatus.UNHEALTHY, f"Chatterbox service not ready: {payload}")
        except (OSError, ValueError, urllib.error.URLError) as exc:
            return AudioBackendHealth(ServiceStatus.UNHEALTHY, f"Chatterbox service unavailable: {exc}")

    def health(self) -> AudioBackendHealth:
        primary = self._primary_health()
        if primary.status == ServiceStatus.HEALTHY:
            self._health_status = primary.status
            self._health_detail = primary.detail
            return primary
        if self.fallback is not None:
            fallback = self.fallback.health()
            if fallback.status == ServiceStatus.HEALTHY:
                self._health_status = ServiceStatus.DEGRADED
                self._health_detail = f"{primary.detail}; fallback ready: {fallback.detail}"
                return AudioBackendHealth(self._health_status, self._health_detail)
        self._health_status = primary.status
        self._health_detail = primary.detail
        return primary

    def _synthesize_primary(self, text: str, request: SpeechRequest) -> SpeechOutput:
        exaggeration, temperature, cfg_weight, pitch_offset, rate_factor = self._params_for_request(request)
        pitch_semitones = max(-2.0, min(2.0, self.base_pitch_semitones + pitch_offset))
        rate = max(0.85, min(1.15, request.rate * self.rate_scale * rate_factor))
        payload = {
            "text": text,
            "emotion": request.emotion,
            "expressiveness": max(0.0, min(1.0, request.expressiveness)),
            "exaggeration": exaggeration,
            "temperature": temperature,
            "cfg_weight": cfg_weight,
            "pitch_semitones": pitch_semitones,
            "rate": rate,
        }
        start = time.monotonic()
        raw = self._request("/synthesize", payload=payload)
        if len(raw) < 12:
            raise RuntimeError("Chatterbox returned empty PCM")
        # Service contract is canonical signed 16-bit mono PCM at 24 kHz.
        return SpeechOutput(
            audio_data=raw,
            sample_rate=24000,
            channels=1,
            duration_ms=len(raw) / float(24000 * 2) * 1000.0,
            latency_ms=(time.monotonic() - start) * 1000.0,
        )

    def synthesize_chunks(self, request: SpeechRequest) -> Iterable[SpeechOutput]:
        phrases = split_speech_for_streaming(request.text, min_chars=22, max_chars=48)
        if not phrases:
            return
        circuit_open = (time.time() - self._last_failure_time < self._circuit_open_seconds)
        primary_failed = circuit_open
        for phrase in phrases:
            if not primary_failed:
                try:
                    output = self._synthesize_primary(phrase, request)
                    self._health_status = ServiceStatus.HEALTHY
                    self._health_detail = f"Chatterbox service active at {self.endpoint}"
                    yield output
                    continue
                except Exception as exc:  # noqa: BLE001
                    primary_failed = True
                    self._last_failure_time = time.time()
                    self._health_status = ServiceStatus.UNHEALTHY
                    self._health_detail = f"Chatterbox synthesis failed: {exc}"
                    logger.warning("Chatterbox synthesis failed; using fallback if available: %s", exc)

            if self.fallback is None:
                continue
            fallback_request = SpeechRequest(
                text=phrase,
                voice_id=request.voice_id,
                rate=request.rate,
                volume=request.volume,
                emotion=request.emotion,
                expressiveness=request.expressiveness,
            )
            if hasattr(self.fallback, "synthesize_chunks"):
                yield from self.fallback.synthesize_chunks(fallback_request)  # type: ignore[attr-defined]
            else:
                output = self.fallback.synthesize(fallback_request)
                if output.audio_data:
                    yield output

    def synthesize(self, request: SpeechRequest) -> SpeechOutput:
        chunks = list(self.synthesize_chunks(request))
        if not chunks:
            return SpeechOutput(audio_data=None, duration_ms=0.0, latency_ms=0.0)
        sample_rate = chunks[0].sample_rate
        channels = chunks[0].channels
        if any(chunk.sample_rate != sample_rate or chunk.channels != channels for chunk in chunks):
            return chunks[0]
        return SpeechOutput(
            audio_data=b"".join(chunk.audio_data or b"" for chunk in chunks),
            sample_rate=sample_rate,
            channels=channels,
            duration_ms=sum(chunk.duration_ms for chunk in chunks),
            latency_ms=chunks[0].latency_ms,
        )

    def warmup(self) -> bool:
        try:
            payload = json.loads(self._request("/warmup", payload={}).decode("utf-8"))
            return payload.get("status") == "ok" and payload.get("model_loaded") is True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chatterbox warmup failed: %s", exc)
            return self.fallback is not None and bool(getattr(self.fallback, "warmup", lambda: True)())
