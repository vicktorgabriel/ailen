"""Normalized domain models and geometric parameters for AILEN Face rendering."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class FacePose:
    """Normalized geometric facial pose parameters.
    
    All coordinates and amplitudes are normalized to [-1.0, 1.0] or [0.0, 1.0],
    completely decoupled from any graphical library, window size, or display backend.
    """
    gaze_x: float = 0.0         # -1.0 (left) .. 1.0 (right)
    gaze_y: float = 0.0         # -1.0 (down) .. 1.0 (up)
    left_eye_open: float = 1.0  # 0.0 (closed) .. 1.0 (fully open)
    right_eye_open: float = 1.0 # 0.0 (closed) .. 1.0 (fully open)
    pupil_size: float = 0.5     # 0.0 (constricted) .. 1.0 (dilated)
    mouth_open: float = 0.0     # 0.0 (closed) .. 1.0 (wide open)
    mouth_width: float = 0.5    # 0.0 (narrow) .. 1.0 (wide smile)
    expression: str = "neutral" # named expression hint
    blink_progress: float = 0.0 # 0.0 (open) .. 1.0 (fully closed blink)
    head_tilt: float = 0.0      # -1.0 .. 1.0 (subtle natural angle)
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize pose to dictionary."""
        return asdict(self)
