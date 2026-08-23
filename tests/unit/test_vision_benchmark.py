"""Unit tests for the vision detector benchmark helpers."""

from ailen.vision.benchmark import (
    VisionBenchmarkSample,
    build_report,
    collect_samples,
    percentile,
)
from ailen.vision.contracts import PresenceObservation


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_percentile_nearest_rank() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile([], 95) == 0.0
    assert percentile(values, 0) == 10.0
    assert percentile(values, 50) == 30.0
    assert percentile(values, 95) == 50.0
    assert percentile(values, 100) == 50.0


def test_build_report_aggregates_statistics() -> None:
    samples = [
        VisionBenchmarkSample(True, 1, 0.92, -0.5, 0.2, 55.0),
        VisionBenchmarkSample(True, 1, 0.95, 0.4, 0.1, 57.0),
        VisionBenchmarkSample(False, 0, None, None, None, 56.0),
        VisionBenchmarkSample(True, 2, 0.90, 0.6, -0.3, 60.0),
    ]
    report = build_report(
        detector="yunet",
        camera_device="/dev/video0",
        requested_fps=5,
        phase="face",
        samples=samples,
        duration_s=0.8,
    )

    assert report.frames == 4
    assert report.detections == 3
    assert report.detection_rate == 75.0
    assert report.avg_latency_ms == (55.0 + 57.0 + 56.0 + 60.0) / 4
    assert report.p50_latency_ms == 56.0
    assert report.p95_latency_ms == 60.0
    assert report.confidence_avg == (0.92 + 0.95 + 0.90) / 3
    assert report.confidence_min == 0.90
    assert report.gaze_x_range == (-0.5, 0.6)
    assert report.gaze_y_range == (-0.3, 0.2)

    data = report.to_dict()
    assert data["detector"] == "yunet"
    assert data["confidence_avg"] == 0.9233
    # Haar-style reports carry no confidence and must not fabricate one.
    haar_report = build_report(
        detector="haar",
        camera_device="0",
        requested_fps=5,
        phase="empty",
        samples=[VisionBenchmarkSample(False, 0, None, None, None, 12.0)],
        duration_s=0.2,
    )
    assert haar_report.to_dict()["confidence_avg"] is None


class _StubBackend:
    """Simulates OpenCvVisionBackend counters without a real camera."""

    def __init__(self) -> None:
        self.frames_processed = 0
        self.last_inference_ms = 0.0
        self._observation = PresenceObservation(present=False)

    def _push_frame(self, present: bool, inference_ms: float) -> None:
        self.last_inference_ms = inference_ms
        self._observation = PresenceObservation(
            present=present,
            faces_count=1 if present else 0,
            confidence=0.93 if present else None,
            primary_x_normalized=0.25 if present else None,
            primary_y_normalized=-0.1 if present else None,
        )
        self.frames_processed += 1

    def get_latest_presence(self) -> PresenceObservation:
        return self._observation


def test_collect_samples_waits_for_new_frames() -> None:
    backend = _StubBackend()
    clock = _FakeClock()

    def sleep(seconds: float) -> None:
        clock.now += seconds
        if 0.01 <= clock.now < 10.0 and int(clock.now * 100) % 2 == 0:
            # Produce one new frame every other simulated tick.
            backend._push_frame(present=clock.now % 0.04 == 0, inference_ms=50.0 + clock.now)

    samples = collect_samples(
        backend,
        max_frames=5,
        timeout_seconds=5.0,
        poll_interval=0.01,
        clock=clock,
        sleep=sleep,
    )

    assert len(samples) == 5
    assert all(s.inference_ms > 0 for s in samples)
    assert any(s.present for s in samples)


def test_collect_samples_respects_timeout() -> None:
    backend = _StubBackend()
    clock = _FakeClock()

    def sleep(seconds: float) -> None:
        clock.now += 1.0  # No frames ever produced.

    samples = collect_samples(
        backend,
        max_frames=10,
        timeout_seconds=5.0,
        poll_interval=0.01,
        clock=clock,
        sleep=sleep,
    )
    assert samples == []


def test_collect_samples_does_not_duplicate_unobserved_frames() -> None:
    backend = _StubBackend()
    clock = _FakeClock()
    jumped = False

    def sleep(seconds: float) -> None:
        nonlocal jumped
        clock.now += seconds
        if not jumped:
            # Simulate the backend advancing three frames between benchmark polls.
            backend._push_frame(present=False, inference_ms=10.0)
            backend._push_frame(present=True, inference_ms=20.0)
            backend._push_frame(present=True, inference_ms=30.0)
            jumped = True
        else:
            clock.now += 1.0

    samples = collect_samples(
        backend,
        max_frames=3,
        timeout_seconds=2.0,
        poll_interval=0.01,
        clock=clock,
        sleep=sleep,
    )

    # Only the latest frame was actually observable; the two missed frames must
    # not be fabricated by cloning the latest observation/latency.
    assert len(samples) == 1
    assert samples[0].inference_ms == 30.0
    assert samples[0].present is True
