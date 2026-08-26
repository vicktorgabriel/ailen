"""OpenCV camera backend with selectable lightweight face detectors."""

import logging
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ailen.core.capabilities import CapabilityDescriptor
from ailen.domain.enums import ServiceStatus
from ailen.vision.contracts import PresenceObservation, VisionBackend, VisionHealth

logger = logging.getLogger("ailen.vision.opencv")


class OpenCvVisionBackend(VisionBackend):
    """Real camera presence backend using Haar or YuNet face detection."""

    def __init__(
        self,
        camera_device: str | int = 0,
        fps: int = 5,
        *,
        detector: str = "haar",
        yunet_model_path: str = "",
        yunet_score_threshold: float = 0.8,
        rtsp_transport: str = "tcp",
        rtsp_open_timeout_ms: int = 3000,
        rtsp_read_timeout_ms: int = 2500,
        rtsp_reconnect_after_failures: int = 3,
    ) -> None:
        detector_name = detector.strip().lower()
        if detector_name not in {"haar", "yunet"}:
            raise ValueError("detector must be 'haar' or 'yunet'")
        self.camera_device = camera_device
        self.source_label = self._safe_source_label(camera_device)
        self.fps = max(1, fps)
        self.detector_name = detector_name
        self.yunet_model_path = yunet_model_path
        self.yunet_score_threshold = max(0.0, min(1.0, yunet_score_threshold))
        self.rtsp_transport = rtsp_transport.strip().lower()
        if self.rtsp_transport not in {"tcp", "udp"}:
            raise ValueError("rtsp_transport must be 'tcp' or 'udp'")
        self.rtsp_open_timeout_ms = max(250, int(rtsp_open_timeout_ms))
        self.rtsp_read_timeout_ms = max(250, int(rtsp_read_timeout_ms))
        self.rtsp_reconnect_after_failures = max(1, int(rtsp_reconnect_after_failures))
        self._consecutive_read_failures = 0
        self._capture_source: Any = camera_device

        self._running = False
        self._thread: threading.Thread | None = None
        self._latest_observation = PresenceObservation(present=False)
        self._health_status = ServiceStatus.UNKNOWN
        self._health_detail = "Initialized"
        self._cap: Any = None
        self._classifier: Any = None
        self._yunet: Any = None
        self._cv2: Any = None
        self.frames_processed: int = 0
        self.frame_read_failures: int = 0
        self.last_inference_ms: float = 0.0
        self.last_valid_frame_at: str | None = None
        self._last_valid_frame_monotonic: float | None = None


    @staticmethod
    def _safe_source_label(source: str | int) -> str:
        """Return a log-safe camera label with RTSP userinfo stripped."""
        if not isinstance(source, str) or not source.lower().startswith(("rtsp://", "rtsps://")):
            return str(source)
        try:
            parsed = urlsplit(source)
            host = parsed.hostname or "network-camera"
            port = f":{parsed.port}" if parsed.port else ""
            return f"{parsed.scheme}://{host}{port}{parsed.path}"
        except ValueError:
            return "rtsp://network-camera"

    def capabilities(self) -> list[CapabilityDescriptor]:
        healthy = self.health().status == ServiceStatus.HEALTHY
        return [
            CapabilityDescriptor(
                key="vision.face_presence",
                description="detectar presencia de rostros y su posición aproximada en la cámara",
                available=healthy,
                source="vision",
            )
        ]

    @property
    def provides_face_confidence(self) -> bool:
        return self.detector_name == "yunet"

    def _init_opencv(self) -> bool:
        try:
            import cv2  # type: ignore[import-not-found]

            self._cv2 = cv2
            if self.detector_name == "yunet":
                model_path = Path(self.yunet_model_path).expanduser()
                if not model_path.is_file():
                    raise RuntimeError(f"YuNet model not found: {model_path}")
                if not hasattr(cv2, "FaceDetectorYN"):
                    raise RuntimeError("OpenCV build lacks FaceDetectorYN")
                self._yunet = cv2.FaceDetectorYN.create(
                    str(model_path),
                    "",
                    (320, 320),
                    self.yunet_score_threshold,
                    0.3,
                    5000,
                )
                return True

            cascade_root = getattr(getattr(cv2, "data", None), "haarcascades", "")
            if not cascade_root:
                raise RuntimeError("OpenCV Haar cascade data directory is unavailable")
            frontal_path = cascade_root + "haarcascade_frontalface_default.xml"
            self._classifier = cv2.CascadeClassifier(frontal_path)
            if self._classifier.empty():
                raise RuntimeError("OpenCV frontal Haar cascade could not be loaded")
            return True
        except ImportError:
            self._health_status = ServiceStatus.DISABLED
            self._health_detail = "opencv-python not installed (optional dependency [vision])"
            return False
        except Exception as exc:  # noqa: BLE001
            self._health_status = ServiceStatus.UNHEALTHY
            self._health_detail = f"Failed to initialize OpenCV {self.detector_name}: {exc}"
            logger.warning("Failed to initialize OpenCV %s detector: %s", self.detector_name, exc)
            return False

    def start(self) -> None:
        if self._running:
            return
        # Frame evidence belongs to one capture run. Reusing a recent timestamp
        # from a previous start would make an opened-but-silent stream appear
        # healthy until the freshness window elapsed.
        self._latest_observation = PresenceObservation(present=False)
        self._consecutive_read_failures = 0
        self.frames_processed = 0
        self.frame_read_failures = 0
        self.last_inference_ms = 0.0
        self.last_valid_frame_at = None
        self._last_valid_frame_monotonic = None
        if not self._init_opencv():
            return

        device_index: Any = self.camera_device
        if isinstance(self.camera_device, str) and self.camera_device.startswith("/dev/video"):
            try:
                device_index = int(self.camera_device.replace("/dev/video", ""))
            except ValueError:
                device_index = self.camera_device

        self._capture_source = device_index
        try:
            self._cap = self._open_capture(device_index)
            if self._cap is None or not self._cap.isOpened():
                self._health_status = ServiceStatus.DEGRADED
                self._health_detail = f"Cannot open video capture source: {self.source_label}"
                return
            self._running = True
            self._health_status = ServiceStatus.DEGRADED
            self._health_detail = f"Video source opened; waiting for first frame from {self.source_label}"
            self._capture_once()
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
        except Exception as exc:
            self._health_status = ServiceStatus.UNHEALTHY
            self._health_detail = f"Error starting capture: {exc}"
            logger.exception("Error starting OpenCV camera capture")

    def _open_capture(self, device_index: Any) -> Any:
        """Open the configured source once; RTSP uses the configured FFmpeg transport."""
        is_rtsp = isinstance(device_index, str) and device_index.lower().startswith("rtsp://")
        if not is_rtsp:
            return self._cv2.VideoCapture(device_index)

        option_name = "OPENCV_FFMPEG_CAPTURE_OPTIONS"
        previous = os.environ.get(option_name)
        os.environ[option_name] = f"rtsp_transport;{self.rtsp_transport}"
        try:
            params = [
                self._cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                self.rtsp_open_timeout_ms,
                self._cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                self.rtsp_read_timeout_ms,
            ]
            capture = self._cv2.VideoCapture(
                device_index,
                self._cv2.CAP_FFMPEG,
                params,
            )
            if capture.isOpened():
                capture.set(self._cv2.CAP_PROP_BUFFERSIZE, 1)
            return capture
        finally:
            if previous is None:
                os.environ.pop(option_name, None)
            else:
                os.environ[option_name] = previous

    def _reconnect_capture(self) -> bool:
        """Reconnect the exact same configured source after sustained read failure."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error releasing capture before reconnect: %s", exc)
        self._cap = self._open_capture(self._capture_source)
        opened = bool(self._cap is not None and self._cap.isOpened())
        if opened:
            self._consecutive_read_failures = 0
            self._health_status = ServiceStatus.DEGRADED
            self._health_detail = (
                f"Reconnected {self.source_label} via {self.rtsp_transport.upper()}; "
                "waiting for a valid frame"
            )
        else:
            self._health_status = ServiceStatus.DEGRADED
            self._health_detail = f"Could not reconnect video source: {self.source_label}"
        return opened

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Exception releasing video capture: %s", exc)
            self._cap = None
        self._latest_observation = PresenceObservation(present=False)
        self._health_status = ServiceStatus.DISABLED
        self._health_detail = "Stopped"

    def health(self) -> VisionHealth:
        status = self._health_status
        detail = self._health_detail
        thread_alive = self._thread.is_alive() if self._thread is not None else None
        if self._running and self._thread is not None and not thread_alive:
            status = ServiceStatus.UNHEALTHY
            detail = "Vision capture thread stopped unexpectedly"

        last_frame_age: float | None = None
        if self._last_valid_frame_monotonic is not None:
            last_frame_age = max(0.0, time.monotonic() - self._last_valid_frame_monotonic)
        freshness_limit = max(
            2.0,
            3.0 / self.fps,
            (self.rtsp_read_timeout_ms / 1000.0) * 2.0,
        )
        if self._running and last_frame_age is None:
            status = ServiceStatus.DEGRADED
            detail = f"Video source open but no valid frame received from {self.source_label}"
        elif self._running and last_frame_age is not None and last_frame_age > freshness_limit:
            status = ServiceStatus.DEGRADED
            detail = f"Last valid frame is stale ({last_frame_age:.1f}s) on {self.source_label}"

        return VisionHealth(
            status=status,
            detail=detail,
            stream_has_frames=last_frame_age is not None and last_frame_age <= freshness_limit,
            frames_processed=self.frames_processed,
            frame_read_failures=self.frame_read_failures,
            last_valid_frame_at=self.last_valid_frame_at,
            last_valid_frame_age_seconds=last_frame_age,
            capture_thread_alive=thread_alive,
            last_inference_ms=self.last_inference_ms if self.frames_processed else None,
        )

    def get_latest_presence(self) -> PresenceObservation:
        return self._latest_observation

    def _capture_once(self) -> None:
        """Read/process one frame while preserving the last valid observation on transport errors."""
        if self._cap is None:
            return
        try:
            ret, frame = self._cap.read()
            if not ret or frame is None:
                self._consecutive_read_failures += 1
                self.frame_read_failures += 1
                self._health_status = ServiceStatus.DEGRADED
                self._health_detail = (
                    f"No frame from {self.source_label} "
                    f"({self._consecutive_read_failures}/{self.rtsp_reconnect_after_failures})"
                )
                if self._consecutive_read_failures >= self.rtsp_reconnect_after_failures:
                    logger.warning(
                        "Video source %s had %d consecutive read failures; reconnecting same source",
                        self.source_label,
                        self._consecutive_read_failures,
                    )
                    self._reconnect_capture()
            else:
                self._consecutive_read_failures = 0
                infer_start = time.perf_counter()
                self._process_frame(frame)
                self.last_inference_ms = (time.perf_counter() - infer_start) * 1000.0
                self.frames_processed += 1
                self._last_valid_frame_monotonic = time.monotonic()
                self.last_valid_frame_at = datetime.now(UTC).isoformat()
                self._health_status = ServiceStatus.HEALTHY
                self._health_detail = (
                    f"Running {self.detector_name} on {self.source_label} @ {self.fps} FPS"
                )
        except Exception as exc:  # noqa: BLE001
            self.frame_read_failures += 1
            logger.debug("Error in frame capture cycle: %s", exc)
            self._health_status = ServiceStatus.DEGRADED
            self._health_detail = f"Transient capture error on {self.source_label}: {type(exc).__name__}"

    def _capture_loop(self) -> None:
        interval = 1.0 / self.fps
        while self._running and self._cap is not None:
            start_t = time.time()
            self._capture_once()
            elapsed = time.time() - start_t
            time.sleep(max(0.01, interval - elapsed))

    def _process_frame(self, frame: Any) -> None:
        if self.detector_name == "yunet":
            self._process_frame_yunet(frame)
        else:
            self._process_frame_haar(frame)

    def _process_frame_yunet(self, frame: Any) -> None:
        h, w = frame.shape[:2]
        if h == 0 or w == 0 or self._yunet is None:
            self._latest_observation = PresenceObservation(present=False)
            return
        self._yunet.setInputSize((w, h))
        _result, faces = self._yunet.detect(frame)
        if faces is None or len(faces) == 0:
            self._latest_observation = PresenceObservation(present=False, faces_count=0)
            return

        primary = max(faces, key=lambda row: float(row[2]) * float(row[3]))
        fx, fy, fw, fh = [float(v) for v in primary[:4]]
        score = float(primary[14])
        fcx = fx + fw / 2.0
        fcy = fy + fh / 2.0
        norm_x = (fcx - w / 2.0) / (w / 2.0)
        norm_y = (h / 2.0 - fcy) / (h / 2.0)
        self._latest_observation = PresenceObservation(
            present=True,
            faces_count=len(faces),
            primary_x_normalized=max(-1.0, min(1.0, norm_x)),
            primary_y_normalized=max(-1.0, min(1.0, norm_y)),
            confidence=score,
        )

    def _process_frame_haar(self, frame: Any) -> None:
        h, w = frame.shape[:2]
        if h == 0 or w == 0 or self._classifier is None:
            self._latest_observation = PresenceObservation(present=False)
            return
        detection_width = 480.0
        scale = detection_width / w if w > detection_width else 1.0
        small_w = int(w * scale)
        small_h = int(h * scale)
        small_frame = self._cv2.resize(frame, (small_w, small_h))
        gray = self._cv2.equalizeHist(self._cv2.cvtColor(small_frame, self._cv2.COLOR_BGR2GRAY))
        faces = self._classifier.detectMultiScale(
            gray,
            scaleFactor=1.08,
            minNeighbors=4,
            minSize=(24, 24),
        )
        if len(faces) == 0:
            self._latest_observation = PresenceObservation(present=False, faces_count=0)
            return
        primary = max(faces, key=lambda rect: rect[2] * rect[3])
        fx, fy, fw, fh = primary
        fcx = fx + fw / 2.0
        fcy = fy + fh / 2.0
        norm_x = (fcx - small_w / 2.0) / (small_w / 2.0)
        norm_y = (small_h / 2.0 - fcy) / (small_h / 2.0)
        self._latest_observation = PresenceObservation(
            present=True,
            faces_count=len(faces),
            primary_x_normalized=max(-1.0, min(1.0, norm_x)),
            primary_y_normalized=max(-1.0, min(1.0, norm_y)),
            confidence=None,
        )
