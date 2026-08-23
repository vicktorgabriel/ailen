"""Vision detector benchmark for AILEN Lab.

CPU-first, headless measurement of face-detector frame latency and detection
statistics. No GUI, no frames persisted, no biometrics. The operator marks the
scene phase (empty/face/movement) per invocation; reports never infer false
positives without ground truth.
"""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VisionBenchmarkSample:
    """One processed camera frame sample."""

    present: bool
    faces_count: int
    confidence: float | None
    gaze_x: float | None
    gaze_y: float | None
    inference_ms: float


@dataclass
class VisionBenchmarkReport:
    """Aggregated detector benchmark report."""

    detector: str
    camera_device: str
    requested_fps: int
    phase: str
    frames: int = 0
    detections: int = 0
    detection_rate: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    confidence_avg: float | None = None
    confidence_min: float | None = None
    gaze_x_range: tuple[float, float] | None = None
    gaze_y_range: tuple[float, float] | None = None
    duration_s: float = 0.0
    samples: list[VisionBenchmarkSample] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe report without per-frame samples."""
        return {
            "detector": self.detector,
            "camera_device": str(self.camera_device),
            "requested_fps": self.requested_fps,
            "phase": self.phase,
            "frames": self.frames,
            "detections": self.detections,
            "detection_rate": round(self.detection_rate, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 3),
            "p50_latency_ms": round(self.p50_latency_ms, 3),
            "p95_latency_ms": round(self.p95_latency_ms, 3),
            "max_latency_ms": round(self.max_latency_ms, 3),
            "confidence_avg": None if self.confidence_avg is None else round(self.confidence_avg, 4),
            "confidence_min": None if self.confidence_min is None else round(self.confidence_min, 4),
            "gaze_x_range": None if self.gaze_x_range is None else [round(v, 4) for v in self.gaze_x_range],
            "gaze_y_range": None if self.gaze_y_range is None else [round(v, 4) for v in self.gaze_y_range],
            "duration_s": round(self.duration_s, 3),
        }


def percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile over an ascending-sorted list. Empty input returns 0.0."""
    if not sorted_values:
        return 0.0
    if pct <= 0:
        return sorted_values[0]
    if pct >= 100:
        return sorted_values[-1]
    rank = max(1, math.ceil((pct / 100.0) * len(sorted_values)))
    return sorted_values[rank - 1]


def build_report(
    *,
    detector: str,
    camera_device: str,
    requested_fps: int,
    phase: str,
    samples: list[VisionBenchmarkSample],
    duration_s: float,
) -> VisionBenchmarkReport:
    """Aggregate raw samples into a report. Never fabricates confidence values."""
    frames = len(samples)
    detections = sum(1 for s in samples if s.present)
    latencies = sorted(s.inference_ms for s in samples)
    confidences = [s.confidence for s in samples if s.confidence is not None]
    gaze_x = [s.gaze_x for s in samples if s.gaze_x is not None]
    gaze_y = [s.gaze_y for s in samples if s.gaze_y is not None]

    return VisionBenchmarkReport(
        detector=detector,
        camera_device=camera_device,
        requested_fps=requested_fps,
        phase=phase,
        frames=frames,
        detections=detections,
        detection_rate=(100.0 * detections / frames) if frames else 0.0,
        avg_latency_ms=(sum(latencies) / len(latencies)) if latencies else 0.0,
        p50_latency_ms=percentile(latencies, 50),
        p95_latency_ms=percentile(latencies, 95),
        max_latency_ms=latencies[-1] if latencies else 0.0,
        confidence_avg=(sum(confidences) / len(confidences)) if confidences else None,
        confidence_min=min(confidences) if confidences else None,
        gaze_x_range=(min(gaze_x), max(gaze_x)) if gaze_x else None,
        gaze_y_range=(min(gaze_y), max(gaze_y)) if gaze_y else None,
        duration_s=duration_s,
        samples=samples,
    )


def collect_samples(
    backend: Any,
    *,
    max_frames: int,
    timeout_seconds: float,
    poll_interval: float = 0.005,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> list[VisionBenchmarkSample]:
    """Collect one sample per newly processed backend frame.

    Requires the backend to expose ``get_latest_presence()``, and benefits from
    ``frames_processed``/``last_inference_ms`` counters when available. Frames
    are never copied or stored; only scalar statistics leave this function.
    """
    samples: list[VisionBenchmarkSample] = []
    last_frame_index = int(getattr(backend, "frames_processed", 0) or 0)
    start_t = clock()

    while len(samples) < max_frames:
        if clock() - start_t > timeout_seconds:
            break

        current_index = int(getattr(backend, "frames_processed", last_frame_index) or 0)
        if current_index <= last_frame_index:
            sleep(poll_interval)
            continue

        # Sample only the latest frame we actually observed. If the backend
        # advanced by multiple frames between polls, those intermediate metrics
        # are unavailable and must be dropped rather than duplicated/fabricated.
        observation = backend.get_latest_presence()
        inference_ms = float(getattr(backend, "last_inference_ms", 0.0) or 0.0)
        samples.append(
            VisionBenchmarkSample(
                present=bool(observation.present),
                faces_count=int(observation.faces_count),
                confidence=observation.confidence,
                gaze_x=observation.primary_x_normalized,
                gaze_y=observation.primary_y_normalized,
                inference_ms=inference_ms,
            )
        )
        last_frame_index = current_index

    return samples
