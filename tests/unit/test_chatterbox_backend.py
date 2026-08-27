from __future__ import annotations

from ailen.audio.chatterbox_backend import ChatterboxHttpTtsBackend
from ailen.audio.contracts import AudioBackendHealth, SpeechOutput, SpeechRequest
from ailen.domain.enums import ServiceStatus


class _FallbackTts:
    def health(self) -> AudioBackendHealth:
        return AudioBackendHealth(ServiceStatus.HEALTHY, "fallback ready")

    def synthesize(self, request: SpeechRequest) -> SpeechOutput:
        return SpeechOutput(audio_data=b"\x00\x00" * 100, sample_rate=22050, channels=1, duration_ms=10.0)


def test_chatterbox_emotion_profiles_are_bounded_and_distinct() -> None:
    neutral = ChatterboxHttpTtsBackend._params_for_request(
        SpeechRequest(text="hola", emotion="neutral", expressiveness=1.0)
    )
    excited = ChatterboxHttpTtsBackend._params_for_request(
        SpeechRequest(text="hola", emotion="excited", expressiveness=1.0)
    )
    sad = ChatterboxHttpTtsBackend._params_for_request(
        SpeechRequest(text="hola", emotion="sad", expressiveness=1.0)
    )

    assert excited[0] > neutral[0]
    assert excited[1] > neutral[1]
    assert excited[3] > neutral[3]
    assert excited[4] > neutral[4]
    assert sad[1] < neutral[1]
    assert sad[3] < neutral[3]
    assert sad[4] < neutral[4]
    for values in (neutral, excited, sad):
        assert 0.25 <= values[0] <= 1.25
        assert 0.20 <= values[1] <= 1.20
        assert 0.20 <= values[2] <= 1.00
        assert -1.5 <= values[3] <= 1.5
        assert 0.90 <= values[4] <= 1.10


def test_chatterbox_yields_pcm_from_primary(monkeypatch) -> None:
    backend = ChatterboxHttpTtsBackend("http://127.0.0.1:8765")
    pcm = b"\x01\x00" * 2400

    monkeypatch.setattr(backend, "_request", lambda *args, **kwargs: pcm)

    chunks = list(backend.synthesize_chunks(SpeechRequest(text="Hola.", emotion="happy")))

    assert len(chunks) == 1
    assert chunks[0].audio_data == pcm
    assert chunks[0].sample_rate == 24000
    assert chunks[0].channels == 1
    assert 99.0 <= chunks[0].duration_ms <= 101.0


def test_chatterbox_falls_back_when_primary_fails(monkeypatch) -> None:
    backend = ChatterboxHttpTtsBackend(
        "http://127.0.0.1:8765",
        fallback=_FallbackTts(),
    )

    def fail(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(backend, "_request", fail)
    chunks = list(backend.synthesize_chunks(SpeechRequest(text="Hola.")))

    assert len(chunks) == 1
    assert chunks[0].sample_rate == 22050
    assert chunks[0].audio_data


def test_chatterbox_health_reports_healthy_fallback(monkeypatch) -> None:
    backend = ChatterboxHttpTtsBackend(
        "http://127.0.0.1:8765",
        fallback=_FallbackTts(),
    )

    def fail(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(backend, "_request", fail)
    health = backend.health()

    assert health.status == ServiceStatus.DEGRADED
    assert "fallback ready" in health.detail


def test_chatterbox_sends_bounded_pitch_and_rate(monkeypatch) -> None:
    backend = ChatterboxHttpTtsBackend(
        "http://127.0.0.1:8765",
        base_pitch_semitones=0.2,
        rate_scale=1.02,
    )
    seen = {}

    def capture(path, payload=None, timeout=None):  # type: ignore[no-untyped-def]
        seen.update(payload or {})
        return b"\x01\x00" * 2400

    monkeypatch.setattr(backend, "_request", capture)
    backend.synthesize(
        SpeechRequest(text="Buenísimo", emotion="excited", expressiveness=1.0, rate=1.0)
    )

    assert 0.2 < float(seen["pitch_semitones"]) <= 2.0
    assert 1.0 < float(seen["rate"]) <= 1.15
