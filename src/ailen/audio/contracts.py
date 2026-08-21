"""Audio contracts: STT and TTS. Ver MODULE_CONTRACTS.md secciones 11-13."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ailen.domain.enums import ServiceStatus


@dataclass
class AudioSegment:
    """A chunk of recorded audio.

    `data` es PCM crudo en bytes; los backends reales lo interpretan según
    `sample_rate`/`channels`. Los eventos del Core nunca cargan audio crudo.
    """
    data: bytes
    sample_rate: int = 16000
    channels: int = 1
    duration_ms: float = 0.0


@dataclass
class Transcript:
    """Normalized STT output."""
    text: str
    language: str = "es"
    confidence: float | None = None
    latency_ms: float = 0.0


@dataclass
class SpeechRequest:
    """Normalized TTS input."""
    text: str
    voice_id: str = "es_ES-standard"
    rate: float = 1.0
    volume: float = 1.0


@dataclass
class SpeechOutput:
    """Normalized TTS output.

    `audio_data` puede ser None si la implementación produce una referencia
    temporal (archivo/stream) indicada en `ref`.
    """
    audio_data: bytes | None = None
    ref: str | None = None
    sample_rate: int = 22050
    duration_ms: float = 0.0
    latency_ms: float = 0.0


@dataclass
class AudioBackendHealth:
    """Health of an audio backend."""
    status: ServiceStatus = ServiceStatus.UNKNOWN
    detail: str = ""


@runtime_checkable
class SttBackend(Protocol):
    """Speech-to-text backend contract."""

    def health(self) -> AudioBackendHealth:
        """Return backend health."""
        ...

    def transcribe(self, segment: AudioSegment) -> Transcript:
        """Transcribe an audio segment to text."""
        ...


@runtime_checkable
class TtsBackend(Protocol):
    """Text-to-speech backend contract."""

    def health(self) -> AudioBackendHealth:
        """Return backend health."""
        ...

    def synthesize(self, request: SpeechRequest) -> SpeechOutput:
        """Synthesize speech from text."""
        ...
