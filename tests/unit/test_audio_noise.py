"""Tests for optional PCM cleanup processors."""

from types import SimpleNamespace

from ailen.audio.noise import WebRtcNoiseProcessor


class FakeProcessor:
    def __init__(self, auto_gain: int, noise_suppression: int) -> None:
        self.auto_gain = auto_gain
        self.noise_suppression = noise_suppression

    def Process10ms(self, chunk: bytes):  # type: ignore[no-untyped-def]
        return SimpleNamespace(audio=bytes((byte ^ 1) for byte in chunk), is_speech=False)


def test_webrtc_noise_processor_splits_20ms_into_two_10ms_blocks() -> None:
    processor = WebRtcNoiseProcessor(
        processor_factory=FakeProcessor,
        noise_suppression=2,
        auto_gain=0,
    )
    frame = bytes([10, 20]) * 320
    cleaned = processor.process(frame)
    assert len(cleaned) == len(frame)
    assert cleaned != frame


def test_webrtc_noise_processor_preserves_invalid_partial_frame() -> None:
    processor = WebRtcNoiseProcessor(processor_factory=FakeProcessor)
    partial = b"\x01\x02" * 10
    assert processor.process(partial) == partial
