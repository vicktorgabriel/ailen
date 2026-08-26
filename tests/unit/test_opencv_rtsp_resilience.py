"""Tests for canonical RTSP transport and transient frame resilience."""

import os
import time

from ailen.domain.enums import ServiceStatus
from ailen.vision.contracts import PresenceObservation
from ailen.vision.opencv_backend import OpenCvVisionBackend


class FakeCapture:
    def __init__(self, reads=None) -> None:
        self.reads = list(reads or [])
        self.released = False
        self.settings = []

    def isOpened(self) -> bool:
        return True

    def set(self, prop, value):  # type: ignore[no-untyped-def]
        self.settings.append((prop, value))
        return True

    def release(self) -> None:
        self.released = True

    def read(self):  # type: ignore[no-untyped-def]
        if self.reads:
            return self.reads.pop(0)
        return False, None


class FakeCv2:
    CAP_FFMPEG = 1900
    CAP_PROP_BUFFERSIZE = 38
    CAP_PROP_OPEN_TIMEOUT_MSEC = 53
    CAP_PROP_READ_TIMEOUT_MSEC = 54

    def __init__(self) -> None:
        self.calls = []
        self.created = []

    def VideoCapture(self, *args):  # type: ignore[no-untyped-def]
        self.calls.append(args)
        cap = FakeCapture()
        self.created.append(cap)
        return cap


def test_rtsp_open_uses_explicit_ffmpeg_transport_and_restores_environment(monkeypatch) -> None:
    fake = FakeCv2()
    backend = OpenCvVisionBackend(
        camera_device="rtsp://camera.local/h264.sdp",
        rtsp_transport="tcp",
    )
    backend._cv2 = fake
    monkeypatch.setenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", "existing;value")

    cap = backend._open_capture("rtsp://camera.local/h264.sdp")

    assert cap.isOpened()
    assert fake.calls == [(
        "rtsp://camera.local/h264.sdp",
        fake.CAP_FFMPEG,
        [
            fake.CAP_PROP_OPEN_TIMEOUT_MSEC,
            3000,
            fake.CAP_PROP_READ_TIMEOUT_MSEC,
            2500,
        ],
    )]
    assert os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] == "existing;value"
    assert (fake.CAP_PROP_BUFFERSIZE, 1) in cap.settings


def test_transient_read_failure_preserves_last_valid_presence() -> None:
    backend = OpenCvVisionBackend(
        camera_device="rtsp://camera.local/h264.sdp",
        rtsp_reconnect_after_failures=5,
    )
    backend._cap = FakeCapture(reads=[(False, None)])
    backend._latest_observation = PresenceObservation(
        present=True,
        faces_count=1,
        confidence=0.92,
    )

    backend._capture_once()

    assert backend.get_latest_presence().present is True
    assert backend._consecutive_read_failures == 1
    assert backend.frames_processed == 0
    assert backend.frame_read_failures == 1


def test_sustained_failures_reconnect_same_source() -> None:
    fake = FakeCv2()
    backend = OpenCvVisionBackend(
        camera_device="rtsp://camera.local/h264.sdp",
        rtsp_transport="tcp",
        rtsp_reconnect_after_failures=2,
    )
    backend._cv2 = fake
    backend._capture_source = "rtsp://camera.local/h264.sdp"
    backend._cap = FakeCapture(reads=[(False, None), (False, None)])
    backend._health_status = ServiceStatus.HEALTHY

    backend._capture_once()
    backend._capture_once()

    assert fake.calls[-1] == (
        "rtsp://camera.local/h264.sdp",
        fake.CAP_FFMPEG,
        [
            fake.CAP_PROP_OPEN_TIMEOUT_MSEC,
            3000,
            fake.CAP_PROP_READ_TIMEOUT_MSEC,
            2500,
        ],
    )
    assert backend.health().status == ServiceStatus.DEGRADED
    assert "waiting for a valid frame" in backend.health().detail


def test_stale_last_frame_degrades_stream_health() -> None:
    backend = OpenCvVisionBackend(
        camera_device="rtsp://camera.local/h264.sdp",
        fps=5,
        rtsp_read_timeout_ms=500,
    )
    backend._running = True
    backend._health_status = ServiceStatus.HEALTHY
    backend._last_valid_frame_monotonic = time.monotonic() - 3.0
    backend.last_valid_frame_at = "2026-08-25T00:00:00+00:00"
    backend.frames_processed = 12

    health = backend.health()

    assert health.status == ServiceStatus.DEGRADED
    assert health.stream_has_frames is False
    assert health.frames_processed == 12
    assert health.last_valid_frame_age_seconds is not None
    assert health.last_valid_frame_age_seconds >= 3.0
    assert "stale" in health.detail


def test_new_capture_run_does_not_reuse_previous_frame_evidence(monkeypatch) -> None:
    backend = OpenCvVisionBackend(
        camera_device="rtsp://camera.local/h264.sdp",
        rtsp_reconnect_after_failures=5,
    )
    capture = FakeCapture(reads=[(False, None)])
    backend.frames_processed = 42
    backend.frame_read_failures = 7
    backend.last_valid_frame_at = "2026-08-25T00:00:00+00:00"
    backend._last_valid_frame_monotonic = time.monotonic()
    monkeypatch.setattr(backend, "_init_opencv", lambda: True)
    monkeypatch.setattr(backend, "_open_capture", lambda _source: capture)

    class NonRunningThread:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            pass

        def is_alive(self) -> bool:
            return True

    monkeypatch.setattr("ailen.vision.opencv_backend.threading.Thread", NonRunningThread)

    backend.start()
    health = backend.health()

    assert backend.frames_processed == 0
    assert backend.frame_read_failures == 1
    assert health.last_valid_frame_at is None
    assert health.stream_has_frames is False
    assert health.status == ServiceStatus.DEGRADED
