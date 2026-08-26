"""Audio contracts: STT and TTS. Ver MODULE_CONTRACTS.md secciones 11-13."""

from collections.abc import Iterable
from dataclasses import dataclass
from threading import Event
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
    channels: int = 1
    duration_ms: float = 0.0
    latency_ms: float = 0.0


@dataclass
class AudioBackendHealth:
    """Health of an audio backend."""
    status: ServiceStatus = ServiceStatus.UNKNOWN
    detail: str = ""


@dataclass
class AudioDevice:
    """Information about an audio input or output device."""
    id: str
    name: str
    is_input: bool = True
    is_output: bool = False
    is_default: bool = False


@dataclass
class VadResult:
    """Output of voice activity analysis on a PCM frame."""
    is_speech: bool
    rms: float = 0.0
    energy: float = 0.0
    is_trigger: bool | None = None


@runtime_checkable
class AudioDeviceEnumerator(Protocol):
    """Protocol for discovering available audio devices."""

    def list_devices(self) -> list[AudioDevice]:
        """Return list of detected audio devices."""
        ...


@runtime_checkable
class AudioInputBackend(Protocol):
    """Audio capture backend contract."""

    def start(self) -> None:
        """Start capturing audio."""
        ...

    def stop(self) -> None:
        """Stop capturing audio."""
        ...

    def read_frame(self, timeout_seconds: float = 0.1) -> bytes | None:
        """Read a PCM frame of audio or return None if timeout/empty."""
        ...

    def health(self) -> AudioBackendHealth:
        """Return backend health status."""
        ...


@runtime_checkable
class AudioOutputBackend(Protocol):
    """Audio playback backend contract."""

    def play(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        channels: int = 1,
        cancel_event: Event | None = None,
    ) -> None:
        """Play PCM audio data unless the owning speech turn was cancelled."""
        ...

    def stop(self) -> None:
        """Stop playback immediately."""
        ...

    def health(self) -> AudioBackendHealth:
        """Return backend health status."""
        ...


@runtime_checkable
class VoiceActivityDetector(Protocol):
    """Voice activity detection contract."""

    def process_frame(self, frame: bytes) -> VadResult:
        """Analyze a PCM frame and determine if voice is present."""
        ...

    def reset(self) -> None:
        """Reset internal state/hangover counters."""
        ...


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


@runtime_checkable
class StreamingTtsBackend(Protocol):
    """Optional TTS capability yielding playable PCM chunks incrementally."""

    def synthesize_chunks(self, request: SpeechRequest) -> Iterable[SpeechOutput]:
        """Yield speech outputs as soon as each audio chunk becomes available."""
        ...
