"""Tkinter-based 2D vector face renderer POC for AILEN.

Provides an ultra-lightweight, zero-pip-dependency graphical face renderer
using Python stdlib tkinter canvas. Consumes normalized FacePose parameters.
"""

import logging
from typing import Any

from ailen.domain.enums import AssistantState
from ailen.face.animator import FaceAnimator
from ailen.face.models import FacePose

logger = logging.getLogger("ailen.face.gui")


class TkinterFaceController:
    """Zero-dependency graphical face controller using Tkinter canvas."""

    def __init__(
        self,
        width: int = 800,
        height: int = 480,
        fullscreen: bool = False,
        fps_limit: int = 30,
        animator: FaceAnimator | None = None,
    ):
        self.width = width
        self.height = height
        self.fullscreen = fullscreen
        self.fps_limit = fps_limit
        self.animator = animator or FaceAnimator()

        self._root: Any = None
        self._canvas: Any = None
        self._running: bool = False
        self._delay_ms = max(10, int(1000 / self.fps_limit))

    def is_available(self) -> bool:
        """Check whether Tk can actually open a display in this environment."""
        try:
            import tkinter as tk
        except ImportError:
            return False

        root: Any = None
        try:
            root = tk.Tk()
            root.withdraw()
            root.update_idletasks()
            return True
        except (tk.TclError, RuntimeError, OSError):
            return False
        finally:
            if root is not None:
                try:
                    root.destroy()
                except tk.TclError:
                    pass

    def start_window(self, interactive_keys: bool = True) -> None:
        """Initialize Tkinter window and start rendering loop."""
        import tkinter as tk

        self._root = tk.Tk()
        self._root.title("AILEN Face (POC)")
        self._root.geometry(f"{self.width}x{self.height}")
        self._root.configure(bg="#0b0f19")

        if self.fullscreen:
            self._root.attributes("-fullscreen", True)

        self._canvas = tk.Canvas(
            self._root,
            width=self.width,
            height=self.height,
            bg="#0b0f19",
            highlightthickness=0,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)

        if interactive_keys:
            self._bind_keys()

        self._running = True
        self._schedule_next_frame()

    def _bind_keys(self) -> None:
        """Bind keyboard shortcuts for interactive demo."""
        if not self._root:
            return

        self._root.bind("<Escape>", lambda e: self.close())
        self._root.bind("q", lambda e: self.close())
        self._root.bind("1", lambda e: self.set_state(AssistantState.IDLE))
        self._root.bind("2", lambda e: self.set_state(AssistantState.ATTENTION))
        self._root.bind("3", lambda e: self.set_state(AssistantState.LISTENING))
        self._root.bind("4", lambda e: self.set_state(AssistantState.PROCESSING))
        self._root.bind("5", lambda e: self._toggle_speaking())
        self._root.bind("6", lambda e: self.sleep())
        self._root.bind("7", lambda e: self.wake())
        self._root.bind("8", lambda e: self.set_state(AssistantState.ERROR))

        self._root.bind("<Left>", lambda e: self.set_gaze(-0.8, 0.0))
        self._root.bind("<Right>", lambda e: self.set_gaze(0.8, 0.0))
        self._root.bind("<Up>", lambda e: self.set_gaze(0.0, 0.8))
        self._root.bind("<Down>", lambda e: self.set_gaze(0.0, -0.8))
        self._root.bind("<space>", lambda e: self._cycle_speech())

    def _toggle_speaking(self) -> None:
        self.set_state(AssistantState.SPEAKING)
        self.set_speech_level(0.7)

    def _cycle_speech(self) -> None:
        cur = self.animator.speech_level
        new_val = 0.0 if cur > 0.6 else cur + 0.35
        self.set_speech_level(new_val)

    def _schedule_next_frame(self) -> None:
        if self._running and self._root:
            self._render_frame()
            self._root.after(self._delay_ms, self._schedule_next_frame)

    def _render_frame(self) -> None:
        """Render a single frame from the current FacePose."""
        if not self._canvas:
            return

        pose = self.animator.step()
        self._canvas.delete("all")

        w = self._canvas.winfo_width() or self.width
        h = self._canvas.winfo_height() or self.height
        cx = w / 2
        cy = h / 2

        # Color scheme
        eye_color = "#38bdf8"       # Sky blue
        pupil_color = "#0369a1"     # Deep blue
        mouth_color = "#38bdf8"
        if pose.expression == "error":
            eye_color = "#f43f5e"   # Rose/Red
            pupil_color = "#881337"
            mouth_color = "#f43f5e"
        elif pose.expression == "degraded":
            eye_color = "#fbbf24"   # Amber
            pupil_color = "#78350f"
            mouth_color = "#fbbf24"

        # Geometry dimensions
        eye_spacing = min(w, h) * 0.28
        eye_rx = min(w, h) * 0.14
        eye_ry = min(w, h) * 0.18

        # Left & Right Eye centers
        left_cx = cx - eye_spacing
        right_cx = cx + eye_spacing
        eye_cy = cy - min(w, h) * 0.08

        # Draw left eye
        self._draw_eye(left_cx, eye_cy, eye_rx, eye_ry, pose.left_eye_open, pose.gaze_x, pose.gaze_y, pose.pupil_size, eye_color, pupil_color)
        # Draw right eye
        self._draw_eye(right_cx, eye_cy, eye_rx, eye_ry, pose.right_eye_open, pose.gaze_x, pose.gaze_y, pose.pupil_size, eye_color, pupil_color)

        # Draw mouth
        mouth_cy = cy + min(w, h) * 0.22
        mouth_w = eye_spacing * (0.8 + pose.mouth_width * 0.4)
        mouth_h = max(2.0, min(w, h) * 0.12 * pose.mouth_open)

        if pose.mouth_open > 0.05:
            self._canvas.create_oval(
                cx - mouth_w / 2,
                mouth_cy - mouth_h / 2,
                cx + mouth_w / 2,
                mouth_cy + mouth_h / 2,
                fill=mouth_color,
                outline="",
            )
        else:
            # Closed gentle curve / line
            self._canvas.create_line(
                cx - mouth_w / 2,
                mouth_cy,
                cx + mouth_w / 2,
                mouth_cy,
                fill=mouth_color,
                width=4,
                capstyle="round",
            )

    def _draw_eye(
        self,
        cx: float,
        cy: float,
        rx: float,
        ry: float,
        eye_open: float,
        gaze_x: float,
        gaze_y: float,
        pupil_size: float,
        eye_color: str,
        pupil_color: str,
    ) -> None:
        """Draw an individual stylized eye with gaze-driven pupil."""
        effective_ry = max(1.0, ry * eye_open)

        # If eyes completely closed (sleep or mid-blink)
        if eye_open < 0.05:
            self._canvas.create_line(
                cx - rx,
                cy,
                cx + rx,
                cy,
                fill=eye_color,
                width=4,
                capstyle="round",
            )
            return

        # Sclera / eye shape
        self._canvas.create_oval(
            cx - rx,
            cy - effective_ry,
            cx + rx,
            cy + effective_ry,
            fill=eye_color,
            outline="",
        )

        # Pupil
        max_gaze_offset_x = rx * 0.45
        max_gaze_offset_y = effective_ry * 0.45
        px = cx + (gaze_x * max_gaze_offset_x)
        py = cy - (gaze_y * max_gaze_offset_y)  # Note: y inverted in screen coordinates

        pupil_rx = rx * (0.35 + 0.15 * pupil_size)
        pupil_ry = effective_ry * (0.35 + 0.15 * pupil_size)

        self._canvas.create_oval(
            px - pupil_rx,
            py - pupil_ry,
            px + pupil_rx,
            py + pupil_ry,
            fill=pupil_color,
            outline="",
        )

    # -------------------------------------------------------------------------
    # FaceController Protocol Methods
    # -------------------------------------------------------------------------

    def set_state(self, state: AssistantState) -> None:
        self.animator.set_state(state)

    def set_gaze(self, x: float, y: float) -> None:
        self.animator.set_gaze(x, y)

    def set_speech_level(self, level: float) -> None:
        self.animator.set_speech_level(level)

    def set_expression(self, expression: str) -> None:
        self.animator.set_expression(expression)

    def sleep(self) -> None:
        self.animator.sleep()

    def wake(self) -> None:
        self.animator.wake()

    def get_current_pose(self) -> FacePose:
        return self.animator.step()

    def schedule_close(self, delay_ms: int) -> None:
        """Schedule demo/window close without exposing Tk internals to callers."""
        if self._root:
            self._root.after(max(0, delay_ms), self.close)

    def mainloop(self) -> None:
        """Run Tkinter event loop."""
        if self._root:
            self._root.mainloop()

    def close(self) -> None:
        """Close window and stop rendering."""
        self._running = False
        if self._root:
            try:
                self._root.destroy()
            except Exception as e:  # noqa: BLE001
                logger.debug("Exception during window close: %s", e)
            self._root = None
