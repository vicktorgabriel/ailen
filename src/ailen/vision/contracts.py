"""Vision contracts. Ver MODULE_CONTRACTS.md sección 10.

Face recibe observaciones normalizadas, nunca frames de cámara.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from ailen.domain.enums import ServiceStatus


@dataclass
class PresenceObservation:
    """Normalized presence/face observation. Sin imágenes ni biometría."""
    present: bool
    faces_count: int = 0
    primary_x_normalized: float | None = None
    primary_y_normalized: float | None = None
    confidence: float | None = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass
class VisionHealth:
    """Health of a vision backend."""
    status: ServiceStatus = ServiceStatus.UNKNOWN
    detail: str = ""
    stream_has_frames: bool = False
    frames_processed: int = 0
    frame_read_failures: int = 0
    last_valid_frame_at: str | None = None
    last_valid_frame_age_seconds: float | None = None
    capture_thread_alive: bool | None = None
    last_inference_ms: float | None = None


@runtime_checkable
class VisionBackend(Protocol):
    """Camera/presence backend contract."""

    def start(self) -> None:
        """Start capture/processing. Best-effort; errores controlados."""
        ...

    def stop(self) -> None:
        """Stop capture and release resources."""
        ...

    def health(self) -> VisionHealth:
        """Return backend health."""
        ...

    def get_latest_presence(self) -> PresenceObservation:
        """Return the latest normalized presence observation."""
        ...
