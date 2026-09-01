"""Lightweight bounded level control for S16LE microphone frames."""

from __future__ import annotations

import math
import sys
from array import array
from dataclasses import dataclass

from ailen.audio.contracts import AudioFrameProcessor


@dataclass(frozen=True)
class CaptureLevelMetrics:
    """Scalar measurements for the last frame; never contains PCM."""

    input_rms: float = 0.0
    input_peak: float = 0.0
    output_rms: float = 0.0
    output_peak: float = 0.0
    clipping_ratio: float = 0.0
    fixed_gain_db: float = 0.0
    auto_gain_db: float = 0.0
    applied_gain_db: float = 0.0
    noise_gate_rms: float = 0.008
    gate_open: bool = False


def pcm_s16le_levels(frame: bytes) -> tuple[float, float]:
    """Return normalized RMS/peak for complete S16LE samples."""

    usable = len(frame) - (len(frame) % 2)
    if usable <= 0:
        return 0.0, 0.0
    samples = array("h")
    samples.frombytes(frame[:usable])
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return 0.0, 0.0
    square_sum = sum(float(sample) * float(sample) for sample in samples)
    rms = math.sqrt(square_sum / len(samples)) / 32768.0
    peak = max(abs(int(sample)) for sample in samples) / 32768.0
    return min(1.0, rms), min(1.0, peak)


class CaptureLevelProcessor:
    """Apply fixed pre-gain, bounded smoothed AGC and a hard safety limiter."""

    def __init__(
        self,
        *,
        capture_gain_db: float = 0.0,
        auto_gain_enabled: bool = False,
        target_rms: float = 0.12,
        max_auto_gain_db: float = 18.0,
        attack_ms: float = 120.0,
        release_ms: float = 600.0,
        noise_gate_rms: float = 0.008,
        gate_hold_ms: float = 300.0,
        limiter_peak: float = 0.98,
        frame_ms: float = 20.0,
    ) -> None:
        if not -24.0 <= capture_gain_db <= 30.0:
            raise ValueError("capture_gain_db must be between -24 and 30 dB")
        if not 0.01 <= target_rms <= 0.5:
            raise ValueError("target_rms must be between 0.01 and 0.5")
        if not 0.0 <= max_auto_gain_db <= 30.0:
            raise ValueError("max_auto_gain_db must be between 0 and 30 dB")
        if attack_ms <= 0.0 or release_ms <= 0.0 or frame_ms <= 0.0:
            raise ValueError("attack/release/frame durations must be positive")
        if not 0.0 <= noise_gate_rms <= 0.5:
            raise ValueError("noise_gate_rms must be between 0 and 0.5")
        if not 0.0 <= gate_hold_ms <= 5000.0:
            raise ValueError("gate_hold_ms must be between 0 and 5000")
        if not 0.5 <= limiter_peak <= 1.0:
            raise ValueError("limiter_peak must be between 0.5 and 1.0")
        self.capture_gain_db = float(capture_gain_db)
        self.auto_gain_enabled = bool(auto_gain_enabled)
        self.target_rms = float(target_rms)
        self.max_auto_gain_db = float(max_auto_gain_db)
        self.attack_ms = float(attack_ms)
        self.release_ms = float(release_ms)
        self.noise_gate_rms = float(noise_gate_rms)
        self.gate_hold_ms = float(gate_hold_ms)
        self.limiter_peak = float(limiter_peak)
        self.frame_ms = float(frame_ms)
        self._auto_gain_db = 0.0
        self._below_gate_ms = 0.0
        self.metrics = CaptureLevelMetrics(
            fixed_gain_db=self.capture_gain_db,
            noise_gate_rms=self.noise_gate_rms,
        )

    def process(self, frame: bytes) -> bytes:
        usable = len(frame) - (len(frame) % 2)
        if usable <= 0:
            return frame
        samples = array("h")
        samples.frombytes(frame[:usable])
        if sys.byteorder != "little":
            samples.byteswap()
        input_rms, input_peak = pcm_s16le_levels(frame[:usable])

        gate_open = bool(
            input_rms > 1e-6
            and (self.noise_gate_rms <= 0.0 or input_rms >= self.noise_gate_rms)
        )
        if self.auto_gain_enabled and gate_open:
            self._below_gate_ms = 0.0
            desired_db = 20.0 * math.log10(self.target_rms / input_rms)
            desired_db = min(self.max_auto_gain_db, max(-12.0, desired_db))
            duration = self.attack_ms if desired_db > self._auto_gain_db else self.release_ms
            alpha = min(1.0, self.frame_ms / duration)
            self._auto_gain_db += (desired_db - self._auto_gain_db) * alpha
        elif self.auto_gain_enabled:
            self._below_gate_ms += self.frame_ms
            if self._below_gate_ms > self.gate_hold_ms:
                alpha = min(1.0, self.frame_ms / self.release_ms)
                self._auto_gain_db += (0.0 - self._auto_gain_db) * alpha
        else:
            self._auto_gain_db = 0.0
            self._below_gate_ms = 0.0

        applied_db = self.capture_gain_db + self._auto_gain_db
        multiplier = 10.0 ** (applied_db / 20.0)
        limit = max(1, min(32767, round(32767 * self.limiter_peak)))
        clipped = 0
        for index, sample in enumerate(samples):
            scaled = round(float(sample) * multiplier)
            if scaled > limit:
                scaled = limit
                clipped += 1
            elif scaled < -limit:
                scaled = -limit
                clipped += 1
            samples[index] = scaled
        if sys.byteorder != "little":
            samples.byteswap()
        processed = samples.tobytes() + frame[usable:]
        output_rms, output_peak = pcm_s16le_levels(processed[:usable])
        self.metrics = CaptureLevelMetrics(
            input_rms=input_rms,
            input_peak=input_peak,
            output_rms=output_rms,
            output_peak=output_peak,
            clipping_ratio=clipped / len(samples) if samples else 0.0,
            fixed_gain_db=self.capture_gain_db,
            auto_gain_db=self._auto_gain_db,
            applied_gain_db=applied_db,
            noise_gate_rms=self.noise_gate_rms,
            gate_open=gate_open,
        )
        return processed

    def reset(self) -> None:
        self._auto_gain_db = 0.0
        self._below_gate_ms = 0.0
        self.metrics = CaptureLevelMetrics(
            fixed_gain_db=self.capture_gain_db,
            noise_gate_rms=self.noise_gate_rms,
        )


class AudioProcessorChain:
    """Run a small ordered processor chain without changing the audio contract."""

    def __init__(self, processors: list[AudioFrameProcessor]) -> None:
        self.processors = tuple(processors)

    def process(self, frame: bytes) -> bytes:
        output = frame
        for processor in self.processors:
            output = processor.process(output)
        return output

    def process_with_stages(self, frame: bytes) -> list[tuple[str, bytes]]:
        """Return in-memory stage snapshots for bounded laboratory measurement."""

        output = frame
        snapshots: list[tuple[str, bytes]] = [("raw", output)]
        for processor in self.processors:
            output = processor.process(output)
            snapshots.append((type(processor).__name__, output))
        return snapshots

    def reset(self) -> None:
        for processor in self.processors:
            processor.reset()


def resolve_capture_processing_mode(
    configured_mode: str,
    *,
    input_device: str,
    effective_source: str = "",
) -> str:
    """Resolve ``auto`` without applying AILEN gain twice to Easy Effects."""

    if configured_mode not in {"auto", "raw", "easyeffects"}:
        raise ValueError(
            "input_processing_mode must be one of: auto, raw, easyeffects"
        )
    if configured_mode != "auto":
        return configured_mode
    observed = f"{input_device} {effective_source}".casefold()
    return "easyeffects" if "easyeffects" in observed else "auto"


def resolve_effective_capture_source(
    reported_source: str,
    observed_source: str = "",
) -> str:
    """Prefer an observed PipeWire node over a backend's generic route label."""

    reported = reported_source.strip()
    observed = observed_source.strip()
    if reported.casefold() in {"", "auto", "default", "pipewire"} and observed:
        return observed
    return reported or observed


def build_capture_processor(
    *,
    sample_rate: int,
    channels: int,
    frame_ms: float,
    capture_gain_db: float,
    auto_gain_enabled: bool,
    auto_gain_target_rms: float,
    max_auto_gain_db: float,
    auto_gain_attack_ms: float,
    auto_gain_release_ms: float,
    auto_gain_noise_gate_rms: float,
    auto_gain_gate_hold_ms: float,
    capture_limiter_peak: float,
    noise_suppression_engine: str,
    noise_suppression_level: int,
    input_processing_mode: str = "auto",
    input_device: str = "default",
    effective_source: str = "",
    processing_profile: str = "full",
) -> AudioProcessorChain:
    """Build the canonical capture order without double-processing virtual DSP."""

    from ailen.audio.noise import WebRtcNoiseProcessor

    resolved_mode = resolve_capture_processing_mode(
        input_processing_mode,
        input_device=input_device,
        effective_source=effective_source,
    )
    if processing_profile not in {"raw", "noise_only", "full"}:
        raise ValueError("processing_profile must be one of: raw, noise_only, full")
    if resolved_mode in {"raw", "easyeffects"} or processing_profile == "raw":
        return AudioProcessorChain([])

    processors: list[AudioFrameProcessor] = []
    # WebRTC NS/high-pass precedes digital level control so the AGC gate follows
    # the cleaned floor rather than amplifying noise that would be removed later.
    if noise_suppression_engine == "webrtc":
        processors.append(
            WebRtcNoiseProcessor(
                sample_rate=sample_rate,
                channels=channels,
                noise_suppression=noise_suppression_level,
                auto_gain=0,
            )
        )
    elif noise_suppression_engine != "none":
        raise ValueError(f"unsupported noise suppression engine: {noise_suppression_engine}")
    if processing_profile == "full":
        processors.append(CaptureLevelProcessor(
            capture_gain_db=capture_gain_db,
            auto_gain_enabled=auto_gain_enabled,
            target_rms=auto_gain_target_rms,
            max_auto_gain_db=max_auto_gain_db,
            attack_ms=auto_gain_attack_ms,
            release_ms=auto_gain_release_ms,
            noise_gate_rms=auto_gain_noise_gate_rms,
            gate_hold_ms=auto_gain_gate_hold_ms,
            limiter_peak=capture_limiter_peak,
            frame_ms=frame_ms,
        ))
    return AudioProcessorChain(processors)
