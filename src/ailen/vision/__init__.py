"""Vision package: contracts and fake backend."""

from ailen.vision.contracts import PresenceObservation, VisionBackend, VisionHealth
from ailen.vision.fake import FakeVisionBackend

__all__ = [
    "FakeVisionBackend",
    "PresenceObservation",
    "VisionBackend",
    "VisionHealth",
]
