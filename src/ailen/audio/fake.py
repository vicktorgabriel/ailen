"""Fake STT/TTS backends. Sin audio real; deterministas para tests."""

import time

from ailen.audio.contracts import (
    AudioBackendHealth,
    AudioSegment,
    SpeechOutput,
    SpeechRequest,
    SttBackend,
    Transcript,
    TtsBackend,
)
from ailen.domain.enums import ServiceStatus


class FakeSttBackend(SttBackend):
    """STT simulado. Devuelve texto fijo o el texto sembrado en el segmento."""

    def __init__(self, canned_text: str = "texto simulado") -> None:
        self._canned_text = canned_text

    def health(self) -> AudioBackendHealth:
        return AudioBackendHealth(status=ServiceStatus.HEALTHY, detail="fake stt")

    def transcribe(self, segment: AudioSegment) -> Transcript:
        start = time.monotonic()
        # Convención dev: si el payload es UTF-8 decodificable y no vacío, se usa
        # como "transcripción"; si no, texto fijo. Nunca falla.
        text = self._canned_text
        if segment.data:
            try:
                decoded = segment.data.decode("utf-8").strip()
                if decoded:
                    text = decoded
            except UnicodeDecodeError:
                pass
        return Transcript(
            text=text,
            language="es",
            confidence=0.99,
            latency_ms=(time.monotonic() - start) * 1000.0,
        )


class FakeTtsBackend(TtsBackend):
    """TTS simulado. Genera silencio PCM de duración proporcional al texto."""

    def health(self) -> AudioBackendHealth:
        return AudioBackendHealth(status=ServiceStatus.HEALTHY, detail="fake tts")

    def synthesize(self, request: SpeechRequest) -> SpeechOutput:
        start = time.monotonic()
        rate = max(request.rate, 0.1)
        duration_ms = max(200.0, len(request.text) * 55.0 / rate)
        sample_rate = 22050
        n_samples = int(sample_rate * duration_ms / 1000.0)
        audio = b"\x00\x00" * n_samples  # silencio 16-bit mono
        return SpeechOutput(
            audio_data=audio,
            sample_rate=sample_rate,
            duration_ms=duration_ms,
            latency_ms=(time.monotonic() - start) * 1000.0,
        )
