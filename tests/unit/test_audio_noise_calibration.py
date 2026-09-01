"""Behavioral tests for bounded, RAM-only microphone noise calibration."""

import struct

from ailen.audio.calibration import PcmNoiseCalibrator
from ailen.audio.contracts import AudioBackendHealth
from ailen.audio.level import CaptureLevelProcessor
from ailen.domain.enums import ServiceStatus


class _FrameInput:
    def __init__(self, frames: list[bytes]) -> None:
        self._frames = iter(frames)
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def read_frame(self, timeout_seconds: float = 0.1) -> bytes | None:
        del timeout_seconds
        return next(self._frames, None)

    def health(self) -> AudioBackendHealth:
        return AudioBackendHealth(ServiceStatus.HEALTHY, "test capture")


def _constant_pcm(value: int, samples: int = 320) -> bytes:
    return struct.pack(f"<{samples}h", *([value] * samples))


def test_noise_calibrator_measures_real_pcm_and_always_stops_input() -> None:
    audio_input = _FrameInput([_constant_pcm(3277)] * 5)
    calibrator = PcmNoiseCalibrator(
        input_factory=lambda: audio_input,
        duration_seconds=0.06,
        frame_ms=20.0,
        minimum_frames=3,
    )

    result = calibrator.measure()

    assert result.ok
    assert 0.099 < result.noise_floor_rms < 0.101
    assert result.frames_measured == 3
    assert result.recommended_threshold > result.noise_floor_rms
    assert result.recommended_auto_gain_gate_rms > result.raw_noise_floor_rms
    assert audio_input.started
    assert audio_input.stopped


def test_noise_calibrator_fails_honestly_when_capture_has_no_frames() -> None:
    audio_input = _FrameInput([])
    calibrator = PcmNoiseCalibrator(
        input_factory=lambda: audio_input,
        duration_seconds=0.02,
        frame_ms=20.0,
        minimum_frames=1,
    )

    result = calibrator.measure()

    assert not result.ok
    assert result.status == "unavailable"
    assert result.frames_measured == 0
    assert audio_input.stopped


def test_noise_calibrator_reports_raw_and_processed_levels_without_pcm() -> None:
    audio_input = _FrameInput([_constant_pcm(1000)] * 4)
    calibrator = PcmNoiseCalibrator(
        input_factory=lambda: audio_input,
        duration_seconds=0.06,
        frame_ms=20.0,
        minimum_frames=3,
        frame_processor=CaptureLevelProcessor(capture_gain_db=6.0),
        source_label="pipewire:test_source",
    )

    result = calibrator.measure()

    assert result.ok
    assert result.effective_source == "pipewire:test_source"
    assert result.processed_noise_floor_rms > result.raw_noise_floor_rms
    assert result.applied_gain_db == 6.0
    assert "pcm" not in result.__dict__


def test_noise_calibrator_prefers_observed_route_over_generic_default_label() -> None:
    audio_input = _FrameInput([_constant_pcm(1000)] * 4)
    audio_input.effective_device = "default"  # type: ignore[attr-defined]
    calibrator = PcmNoiseCalibrator(
        input_factory=lambda: audio_input,
        duration_seconds=0.06,
        frame_ms=20.0,
        minimum_frames=3,
        source_label="pipewire:easyeffects_source",
    )

    result = calibrator.measure()

    assert result.ok
    assert result.effective_source == "pipewire:easyeffects_source"
