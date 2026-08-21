"""Audio package: STT/TTS contracts and fakes."""

from ailen.audio.contracts import (
    AudioBackendHealth,
    AudioSegment,
    SpeechOutput,
    SpeechRequest,
    SttBackend,
    Transcript,
    TtsBackend,
)
from ailen.audio.fake import FakeSttBackend, FakeTtsBackend

__all__ = [
    "AudioBackendHealth",
    "AudioSegment",
    "FakeSttBackend",
    "FakeTtsBackend",
    "SpeechOutput",
    "SpeechRequest",
    "SttBackend",
    "Transcript",
    "TtsBackend",
]
