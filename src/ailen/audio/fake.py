"""Fake STT/TTS backends. Sin audio real; deterministas para tests."""

import time
from threading import Event

from ailen.audio.contracts import (
    AudioBackendHealth,
    AudioDevice,
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
            engine="fake",
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
            channels=1,
            duration_ms=duration_ms,
            latency_ms=(time.monotonic() - start) * 1000.0,
        )


class FakeAudioInputBackend:
    """Fake audio input backend that yields injected or empty PCM frames."""

    def __init__(self, frame_size: int = 640) -> None:
        self.frame_size = frame_size
        self._frames: list[bytes] = []
        self._running = False

    def push_frame(self, frame: bytes) -> None:
        """Inject a frame into the read queue."""
        self._frames.append(frame)

    def push_frames(self, frames: list[bytes]) -> None:
        """Inject multiple frames into the read queue."""
        self._frames.extend(frames)

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False
        self._frames.clear()

    def read_frame(self, timeout_seconds: float = 0.1) -> bytes | None:
        if not self._running:
            return None
        if self._frames:
            return self._frames.pop(0)
        return None

    def health(self) -> AudioBackendHealth:
        return AudioBackendHealth(status=ServiceStatus.HEALTHY, detail="fake audio input")


class FakeAudioOutputBackend:
    """Fake audio output backend that captures played audio in memory."""

    def __init__(self) -> None:
        self.played_chunks: list[bytes] = []
        self.stopped = False

    def play(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        channels: int = 1,
        cancel_event: Event | None = None,
    ) -> None:
        if audio_data and not (cancel_event and cancel_event.is_set()):
            self.played_chunks.append(audio_data)
            self.stopped = False

    def stop(self) -> None:
        self.stopped = True

    def health(self) -> AudioBackendHealth:
        return AudioBackendHealth(status=ServiceStatus.HEALTHY, detail="fake audio output")


class FakeDeviceEnumerator:
    """Fake device enumerator returning deterministic mock devices."""

    def list_devices(self) -> list[AudioDevice]:
        return [
            AudioDevice(
                id="default",
                name="Default System Audio",
                is_input=True,
                is_output=True,
                is_default=True,
            ),
            AudioDevice(
                id="hw:0,0",
                name="Built-in Microphone",
                is_input=True,
                is_output=False,
                is_default=False,
            ),
            AudioDevice(
                id="hw:0,1",
                name="Built-in Speaker",
                is_input=False,
                is_output=True,
                is_default=False,
            ),
        ]
