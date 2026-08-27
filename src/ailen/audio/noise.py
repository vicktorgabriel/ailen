"""Optional lightweight PCM cleanup processors for noisy physical environments."""

from collections.abc import Callable
from typing import Any


class WebRtcNoiseProcessor:
    """WebRTC noise suppression/high-pass filter for 16 kHz mono 16-bit PCM."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        noise_suppression: int = 2,
        auto_gain: int = 0,
        processor_factory: Callable[..., Any] | None = None,
    ) -> None:
        if sample_rate != 16000 or channels != 1:
            raise ValueError("WebRTC noise processor currently requires 16 kHz mono PCM")
        if noise_suppression not in {0, 1, 2, 3}:
            raise ValueError("noise_suppression must be between 0 and 3")
        if auto_gain not in {0, 1}:
            raise ValueError("auto_gain must be 0 or 1")
        self.sample_rate = sample_rate
        self.channels = channels
        self.noise_suppression = noise_suppression
        self.auto_gain = auto_gain
        self._processor_factory = processor_factory or self._load_factory()
        self._processor = self._new_processor()
        self._chunk_bytes = int(self.sample_rate * 0.010) * 2

    @staticmethod
    def _load_factory() -> Callable[..., Any]:
        try:
            from webrtc_noise_gain import AudioProcessor  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "webrtc-noise-gain is required for WebRTC noise suppression"
            ) from exc
        return AudioProcessor

    def _new_processor(self) -> Any:
        return self._processor_factory(
            auto_gain=self.auto_gain,
            noise_suppression=self.noise_suppression,
        )

    def process(self, frame: bytes) -> bytes:
        if not frame or len(frame) % self._chunk_bytes != 0:
            return frame
        output = bytearray()
        for offset in range(0, len(frame), self._chunk_bytes):
            result = self._processor.Process10ms(frame[offset : offset + self._chunk_bytes])
            cleaned = result.audio
            if not isinstance(cleaned, bytes) or len(cleaned) != self._chunk_bytes:
                return frame
            output.extend(cleaned)
        return bytes(output)

    def reset(self) -> None:
        self._processor = self._new_processor()
