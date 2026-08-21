"""OpenCV-based real camera presence backend POC.

Provides lightweight face detection using standard Haar cascades without
heavy neural networks, biometrics, or facial recognition.
Degrades cleanly if OpenCV or the video device is unavailable.
"""

import logging
import threading
import time
from typing import Any

from ailen.domain.enums import ServiceStatus
from ailen.vision.contracts import PresenceObservation, VisionBackend, VisionHealth

logger = logging.getLogger("ailen.vision.opencv")


class OpenCvVisionBackend(VisionBackend):
    """Real camera presence detection using OpenCV Haar cascade classifier."""

    def __init__(
        self,
        camera_device: str | int = 0,
        fps: int = 5,
    ):
        self.camera_device = camera_device
        self.fps = max(1, fps)

        self._running = False
        self._thread: threading.Thread | None = None
        self._latest_observation = PresenceObservation(present=False)
        self._health_status = ServiceStatus.UNKNOWN
        self._health_detail = "Initialized"

        self._cap: Any = None
        self._classifier: Any = None

    def _init_opencv(self) -> bool:
        """Attempt to import and initialize OpenCV."""
        try:
            import cv2  # type: ignore[import-not-found]
            self._cv2 = cv2
            # Load default frontal face cascade from OpenCV data directory
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._classifier = cv2.CascadeClassifier(cascade_path)
            return True
        except ImportError:
            self._health_status = ServiceStatus.DISABLED
            self._health_detail = "opencv-python not installed (optional dependency [vision])"
            logger.info("OpenCV not installed; camera backend disabled.")
            return False
        except Exception as e:  # noqa: BLE001
            self._health_status = ServiceStatus.UNHEALTHY
            self._health_detail = f"Failed to initialize OpenCV: {e}"
            logger.warning("Failed to initialize OpenCV cascade: %s", e)
            return False

    def start(self) -> None:
        """Start camera capture and background detection thread."""
        if self._running:
            return

        if not self._init_opencv():
            return

        device_index: Any = self.camera_device
        if isinstance(self.camera_device, str) and self.camera_device.startswith("/dev/video"):
            try:
                device_index = int(self.camera_device.replace("/dev/video", ""))
            except ValueError:
                device_index = self.camera_device

        try:
            self._cap = self._cv2.VideoCapture(device_index)
            if not self._cap.isOpened():
                self._health_status = ServiceStatus.DEGRADED
                self._health_detail = f"Cannot open video capture device: {self.camera_device}"
                logger.warning("Camera device %s not available", self.camera_device)
                return

            self._running = True
            self._health_status = ServiceStatus.HEALTHY
            self._health_detail = f"Running on {self.camera_device} @ {self.fps} FPS"
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
        except Exception as e:
            self._health_status = ServiceStatus.UNHEALTHY
            self._health_detail = f"Error starting capture: {e}"
            logger.exception("Error starting OpenCV camera capture")

    def stop(self) -> None:
        """Stop background capture thread and release camera device."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None

        if self._cap is not None:
            try:
                self._cap.release()
            except Exception as e:  # noqa: BLE001
                logger.debug("Exception releasing video capture: %s", e)
            self._cap = None

        self._latest_observation = PresenceObservation(present=False)
        self._health_status = ServiceStatus.DISABLED
        self._health_detail = "Stopped"

    def health(self) -> VisionHealth:
        """Return current vision backend health status."""
        return VisionHealth(status=self._health_status, detail=self._health_detail)

    def get_latest_presence(self) -> PresenceObservation:
        """Return the latest normalized presence observation."""
        return self._latest_observation

    def _capture_loop(self) -> None:
        """Background thread loop capturing frames at target FPS."""
        interval = 1.0 / self.fps
        while self._running and self._cap is not None:
            start_t = time.time()
            try:
                ret, frame = self._cap.read()
                if not ret or frame is None:
                    self._latest_observation = PresenceObservation(present=False)
                else:
                    self._process_frame(frame)
            except Exception as e:  # noqa: BLE001
                logger.debug("Error in frame capture cycle: %s", e)
                self._latest_observation = PresenceObservation(present=False)

            elapsed = time.time() - start_t
            sleep_time = max(0.01, interval - elapsed)
            time.sleep(sleep_time)

    def _process_frame(self, frame: Any) -> None:
        """Detect faces on a downscaled grayscale frame and normalize coordinates."""
        h, w = frame.shape[:2]
        if h == 0 or w == 0:
            self._latest_observation = PresenceObservation(present=False)
            return

        # Downscale for CPU efficiency (width ~320px)
        scale = 320.0 / w if w > 320 else 1.0
        small_w = int(w * scale)
        small_h = int(h * scale)
        small_frame = self._cv2.resize(frame, (small_w, small_h))
        gray = self._cv2.cvtColor(small_frame, self._cv2.COLOR_BGR2GRAY)

        faces = self._classifier.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=(24, 24),
        )

        if len(faces) == 0:
            self._latest_observation = PresenceObservation(
                present=False,
                faces_count=0,
            )
            return

        # Select primary face (largest detected bounding box)
        primary_face = max(faces, key=lambda rect: rect[2] * rect[3])
        fx, fy, fw, fh = primary_face

        # Center in small frame coordinates
        fcx = fx + fw / 2.0
        fcy = fy + fh / 2.0

        # Normalize to [-1.0, 1.0]
        # x: -1.0 (left of camera) .. 1.0 (right of camera)
        # y: -1.0 (bottom) .. 1.0 (top)
        norm_x = (fcx - small_w / 2.0) / (small_w / 2.0)
        norm_y = (small_h / 2.0 - fcy) / (small_h / 2.0)

        self._latest_observation = PresenceObservation(
            present=True,
            faces_count=len(faces),
            primary_x_normalized=max(-1.0, min(1.0, norm_x)),
            primary_y_normalized=max(-1.0, min(1.0, norm_y)),
            # Haar Cascade no expone una confianza calibrada comparable entre
            # detecciones. No inventamos un valor: dejamos confidence sin dato.
            confidence=None,
        )
