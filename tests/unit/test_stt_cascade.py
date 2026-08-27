"""Tests for confidence-aware STT cascading."""

from ailen.audio.contracts import AudioBackendHealth, AudioSegment, Transcript
from ailen.audio.stt_cascade import CascadingSttBackend
from ailen.domain.enums import ServiceStatus


class StubStt:
    def __init__(self, result: Transcript) -> None:
        self.result = result
        self.calls = 0

    def health(self) -> AudioBackendHealth:
        return AudioBackendHealth(ServiceStatus.HEALTHY, "ok")

    def transcribe(self, segment: AudioSegment) -> Transcript:
        del segment
        self.calls += 1
        return self.result


def test_high_confidence_primary_skips_fallback() -> None:
    primary = StubStt(Transcript(text="hola como estas", confidence=0.91, latency_ms=10))
    fallback = StubStt(Transcript(text="otro", confidence=None, latency_ms=20))
    cascade = CascadingSttBackend(primary, fallback, confidence_threshold=0.72)
    out = cascade.transcribe(AudioSegment(data=b"x"))
    assert out.text == "hola como estas"
    assert fallback.calls == 0


def test_low_confidence_primary_uses_fallback() -> None:
    primary = StubStt(Transcript(text="ala como eta", confidence=0.45, latency_ms=10))
    fallback = StubStt(Transcript(text="hola como estás", confidence=None, latency_ms=20))
    cascade = CascadingSttBackend(primary, fallback, confidence_threshold=0.72)
    out = cascade.transcribe(AudioSegment(data=b"x"))
    assert out.text == "hola como estás"
    assert out.latency_ms == 30
    assert fallback.calls == 1


def test_empty_primary_uses_fallback_even_without_confidence() -> None:
    primary = StubStt(Transcript(text="", confidence=None, latency_ms=10))
    fallback = StubStt(Transcript(text="repetición recuperada", confidence=None, latency_ms=20))
    out = CascadingSttBackend(primary, fallback).transcribe(AudioSegment(data=b"x"))
    assert out.text == "repetición recuperada"
