"""Bounded, RAM-only microphone noise-floor calibration."""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ailen.audio.contracts import AudioFrameProcessor, AudioInputBackend
from ailen.audio.level import (
    AudioProcessorChain,
    CaptureLevelProcessor,
    pcm_s16le_levels,
    resolve_effective_capture_source,
)
from ailen.domain.enums import ServiceStatus


@dataclass(frozen=True)
class NoiseCalibrationResult:
    """Noise measurement outcome; never contains captured PCM."""

    ok: bool
    status: str
    noise_floor_rms: float = 0.0
    peak_noise_rms: float = 0.0
    recommended_threshold: float = 0.0
    recommended_auto_gain_gate_rms: float = 0.0
    frames_measured: int = 0
    duration_ms: float = 0.0
    detail: str = ""
    effective_source: str = ""
    raw_noise_floor_rms: float = 0.0
    processed_noise_floor_rms: float = 0.0
    raw_peak: float = 0.0
    processed_peak: float = 0.0
    clipping_ratio: float = 0.0
    applied_gain_db: float = 0.0


@runtime_checkable
class NoiseCalibrator(Protocol):
    """Explicit boundary used by the Web panel and lab tooling."""

    def measure(self) -> NoiseCalibrationResult:
        """Measure the configured input without persisting audio."""
        ...


def recommend_auto_gain_gate_rms(
    raw_rms_values: list[float],
    *,
    threshold_multiplier: float = 1.5,
    threshold_margin: float = 0.002,
) -> float | None:
    """Derive a bounded AGC gate from the p95 of RAM-only silence RMS."""

    if not raw_rms_values:
        return None
    ordered = sorted(max(0.0, float(value)) for value in raw_rms_values)
    p95_index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
    peak = ordered[p95_index]
    multiplier = max(1.0, float(threshold_multiplier))
    margin = max(0.0, float(threshold_margin))
    return min(0.5, max(peak * multiplier, peak + margin))


class PcmNoiseCalibrator:
    """Measure S16LE PCM RMS for a bounded number of input frames."""

    def __init__(
        self,
        input_factory: Callable[[], AudioInputBackend],
        *,
        duration_seconds: float = 1.0,
        frame_ms: float = 20.0,
        minimum_frames: int = 10,
        threshold_multiplier: float = 1.5,
        threshold_margin: float = 0.002,
        frame_processor: AudioFrameProcessor | None = None,
        source_label: str = "",
    ) -> None:
        if duration_seconds <= 0.0:
            raise ValueError("duration_seconds must be positive")
        if frame_ms <= 0.0:
            raise ValueError("frame_ms must be positive")
        if minimum_frames <= 0:
            raise ValueError("minimum_frames must be positive")
        self._input_factory = input_factory
        self._target_frames = max(1, math.ceil(duration_seconds * 1000.0 / frame_ms))
        self._frame_ms = frame_ms
        self._minimum_frames = minimum_frames
        self._threshold_multiplier = max(1.0, threshold_multiplier)
        self._threshold_margin = max(0.0, threshold_margin)
        self._frame_processor = frame_processor
        self._source_label = source_label

    def measure(self) -> NoiseCalibrationResult:
        audio_input = self._input_factory()
        raw_rms_values: list[float] = []
        processed_rms_values: list[float] = []
        raw_peaks: list[float] = []
        processed_peaks: list[float] = []
        clipping_ratios: list[float] = []
        applied_gains: list[float] = []
        attempts = 0
        max_attempts = max(self._target_frames * 3, self._minimum_frames)
        effective_source = self._source_label
        try:
            audio_input.start()
            health = audio_input.health()
            if health.status is not ServiceStatus.HEALTHY:
                return NoiseCalibrationResult(
                    ok=False,
                    status="unavailable",
                    detail=health.detail or "audio input is not healthy",
                )
            effective_source = resolve_effective_capture_source(
                str(getattr(audio_input, "effective_device", "") or ""),
                effective_source,
            )
            while len(processed_rms_values) < self._target_frames and attempts < max_attempts:
                attempts += 1
                frame = audio_input.read_frame(timeout_seconds=max(0.05, self._frame_ms / 1000.0))
                if frame:
                    raw_rms, raw_peak = pcm_s16le_levels(frame)
                    processed = (
                        self._frame_processor.process(frame)
                        if self._frame_processor is not None
                        else frame
                    )
                    processed_rms, processed_peak = pcm_s16le_levels(processed)
                    raw_rms_values.append(raw_rms)
                    processed_rms_values.append(processed_rms)
                    raw_peaks.append(raw_peak)
                    processed_peaks.append(processed_peak)
                    level_processor = _capture_level_processor(self._frame_processor)
                    if level_processor is not None:
                        clipping_ratios.append(level_processor.metrics.clipping_ratio)
                        applied_gains.append(level_processor.metrics.applied_gain_db)
        except Exception as exc:  # noqa: BLE001 - hardware boundary returns typed failure
            return NoiseCalibrationResult(
                ok=False,
                status="unavailable",
                frames_measured=len(processed_rms_values),
                duration_ms=len(processed_rms_values) * self._frame_ms,
                detail=f"{type(exc).__name__}: {exc}",
                effective_source=effective_source,
            )
        finally:
            if self._frame_processor is not None:
                self._frame_processor.reset()
            audio_input.stop()

        if len(processed_rms_values) < self._minimum_frames:
            return NoiseCalibrationResult(
                ok=False,
                status="unavailable",
                frames_measured=len(processed_rms_values),
                duration_ms=len(processed_rms_values) * self._frame_ms,
                detail="insufficient PCM frames for a real measurement",
                effective_source=effective_source,
            )

        ordered = sorted(processed_rms_values)
        p95_index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
        floor = statistics.median(ordered)
        peak = ordered[p95_index]
        recommended = min(1.0, max(peak * self._threshold_multiplier, peak + self._threshold_margin))
        recommended_gate = recommend_auto_gain_gate_rms(
            raw_rms_values,
            threshold_multiplier=self._threshold_multiplier,
            threshold_margin=self._threshold_margin,
        )
        return NoiseCalibrationResult(
            ok=True,
            status="measured",
            noise_floor_rms=floor,
            peak_noise_rms=peak,
            recommended_threshold=recommended,
            recommended_auto_gain_gate_rms=recommended_gate or 0.0,
            frames_measured=len(processed_rms_values),
            duration_ms=len(processed_rms_values) * self._frame_ms,
            detail="S16LE input measured in RAM; no PCM persisted",
            effective_source=effective_source,
            raw_noise_floor_rms=statistics.median(raw_rms_values),
            processed_noise_floor_rms=floor,
            raw_peak=max(raw_peaks, default=0.0),
            processed_peak=max(processed_peaks, default=0.0),
            clipping_ratio=statistics.mean(clipping_ratios) if clipping_ratios else 0.0,
            applied_gain_db=statistics.median(applied_gains) if applied_gains else 0.0,
        )


def _capture_level_processor(
    processor: AudioFrameProcessor | None,
) -> CaptureLevelProcessor | None:
    if isinstance(processor, CaptureLevelProcessor):
        return processor
    if isinstance(processor, AudioProcessorChain):
        return next(
            (
                item
                for item in processor.processors
                if isinstance(item, CaptureLevelProcessor)
            ),
            None,
        )
    return None
