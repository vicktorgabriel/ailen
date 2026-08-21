"""Fake vision backend. Sin cámara; presencia simulada y controlable."""

from ailen.domain.enums import ServiceStatus
from ailen.vision.contracts import PresenceObservation, VisionBackend, VisionHealth


class FakeVisionBackend(VisionBackend):
    """Visión simulada.

    La presencia se siembra con `set_presence()`; útil para dev del Social
    Engine y tests del dashboard sin cámara.
    """

    def __init__(self) -> None:
        self._running = False
        self._observation = PresenceObservation(present=False)

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False
        self._observation = PresenceObservation(present=False)

    def health(self) -> VisionHealth:
        status = ServiceStatus.HEALTHY if self._running else ServiceStatus.DISABLED
        return VisionHealth(status=status, detail="fake vision")

    def get_latest_presence(self) -> PresenceObservation:
        if not self._running:
            return PresenceObservation(present=False)
        return self._observation

    def set_presence(
        self,
        present: bool,
        faces_count: int = 0,
        x: float | None = None,
        y: float | None = None,
        confidence: float | None = None,
    ) -> None:
        """Seed a presence observation (dev/test hook)."""
        self._observation = PresenceObservation(
            present=present,
            faces_count=faces_count,
            primary_x_normalized=x,
            primary_y_normalized=y,
            confidence=confidence,
        )
