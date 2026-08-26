"""Tkinter-based 2D vector face renderer POC for AILEN.

Provides an ultra-lightweight, zero-pip-dependency graphical face renderer
using Python stdlib tkinter canvas. Consumes normalized FacePose parameters.
"""

import logging
from typing import Any

from ailen.core.capabilities import CapabilityDescriptor
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
        style: str = "vector",
    ):
        self.width = width
        self.height = height
        self.fullscreen = fullscreen
        self.fps_limit = fps_limit
        self.animator = animator or FaceAnimator()
        self.style = style if style in {"vector", "pixel"} else "vector"

        self._root: Any = None
        self._canvas: Any = None
        self._running: bool = False
        self._delay_ms = max(10, int(1000 / self.fps_limit))
        self._last_rendered_expression: str | None = None

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
        self._root.title("AILEN")
        self._root.geometry(f"{self.width}x{self.height}")
        self._root.configure(bg="#0b0f19")
        self._root.protocol("WM_DELETE_WINDOW", self.close)

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
        self._last_rendered_expression = None
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
        if pose.expression != self._last_rendered_expression:
            logger.info(
                "face_expression stage=rendered expression=%s state=%s style=%s",
                pose.expression,
                self.animator.state.value,
                self.style,
            )
            self._last_rendered_expression = pose.expression
        self._canvas.delete("all")

        w = self._canvas.winfo_width() or self.width
        h = self._canvas.winfo_height() or self.height
        cx = w / 2
        cy = h / 2

        # Color scheme
        eye_color = "#38bdf8"       # Sky blue
        highlight_color = "#bae6fd" # Ice blue
        shadow_color = "#0ea5e9"    # Cyan shadow
        pupil_color = "#075985"     # Deep blue
        mouth_color = "#38bdf8"
        if pose.expression == "error":
            eye_color = "#f43f5e"   # Rose/Red
            highlight_color = "#fecdd3"
            shadow_color = "#be123c"
            pupil_color = "#881337"
            mouth_color = "#f43f5e"
        elif pose.expression == "degraded":
            eye_color = "#fbbf24"   # Amber
            highlight_color = "#fef3c7"
            shadow_color = "#d97706"
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

        if self.style == "pixel":
            self._draw_pixel_face(
                pose=pose,
                width=w,
                height=h,
                eye_color=eye_color,
                highlight_color=highlight_color,
                shadow_color=shadow_color,
                pupil_color=pupil_color,
                mouth_color=mouth_color,
            )
            return

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

    @staticmethod
    def _pixel_block_size(scale: float) -> int:
        """Return a fine but still legible pixel grid for the shortest edge."""
        return max(2, int(scale / 100))

    def _draw_pixel_face(
        self,
        pose: FacePose,
        width: float,
        height: float,
        eye_color: str,
        highlight_color: str,
        shadow_color: str,
        pupil_color: str,
        mouth_color: str,
    ) -> None:
        """Render the normalized pose as layered, 16-bit-inspired pixel art."""
        if not self._canvas:
            return
        scale = min(width, height)
        block = self._pixel_block_size(scale)
        cx = width / 2
        cy = height / 2
        eye_dx = scale * 0.24
        eye_y = cy - scale * 0.10
        eye_w = block * 23

        def snap(value: float) -> float:
            return round(value / block) * block

        tilt_offset = snap(pose.head_tilt * block * 12)

        for eye_cx, eye_y_offset, openness in (
            (cx - eye_dx, -tilt_offset, pose.left_eye_open),
            (cx + eye_dx, tilt_offset, pose.right_eye_open),
        ):
            open_h = max(block, int(block * 15 * openness))
            if openness < 0.08:
                y = snap(eye_y + eye_y_offset)
                self._canvas.create_rectangle(
                    snap(eye_cx - eye_w / 2), y,
                    snap(eye_cx + eye_w / 2), y + block,
                    fill=shadow_color, outline="",
                )
                self._canvas.create_rectangle(
                    snap(eye_cx - eye_w / 2) + block,
                    y,
                    snap(eye_cx + eye_w / 2) - block,
                    y + max(1, block // 2),
                    fill=highlight_color,
                    outline="",
                )
                continue
            left = snap(eye_cx - eye_w / 2)
            top = snap(eye_y + eye_y_offset - open_h / 2)
            right = snap(eye_cx + eye_w / 2)
            bottom = top + open_h
            if open_h < block * 3:
                self._canvas.create_rectangle(
                    left,
                    top,
                    right,
                    bottom,
                    fill=shadow_color,
                    outline="",
                )
                self._canvas.create_rectangle(
                    left + block,
                    top,
                    right - block,
                    top + max(1, block // 2),
                    fill=highlight_color,
                    outline="",
                )
                continue
            # Two stepped corner rows retain the pixel silhouette while three
            # palette levels add the volume associated with richer sprite art.
            if open_h >= block * 5:
                self._canvas.create_rectangle(
                    left,
                    top + block * 2,
                    right,
                    bottom - block * 2,
                    fill=eye_color,
                    outline="",
                )
                self._canvas.create_rectangle(
                    left + block,
                    top + block,
                    right - block,
                    bottom - block,
                    fill=eye_color,
                    outline="",
                )
                corner_inset = block * 2
            else:
                self._canvas.create_rectangle(
                    left,
                    top + block,
                    right,
                    bottom - block,
                    fill=eye_color,
                    outline="",
                )
                corner_inset = block
            self._canvas.create_rectangle(
                left + corner_inset,
                top,
                right - corner_inset,
                top + block,
                fill=highlight_color,
                outline="",
            )
            self._canvas.create_rectangle(
                left + corner_inset,
                bottom - block,
                right - corner_inset,
                bottom,
                fill=shadow_color,
                outline="",
            )
            self._canvas.create_rectangle(
                left,
                top + block * 2,
                left + block,
                bottom - block * 2,
                fill=highlight_color,
                outline="",
            )

            pupil_blocks = 6 if pose.pupil_size < 0.65 else 8
            px = snap(eye_cx + pose.gaze_x * block * 5.0)
            py = snap(eye_y + eye_y_offset - pose.gaze_y * block * 3.5)
            half = (pupil_blocks * block) / 2
            # Colored iris ring and a smaller deep pupil make gaze legible
            # without abandoning the block grid.
            self._canvas.create_rectangle(
                px - half,
                py - half + block,
                px + half,
                py + half - block,
                fill=shadow_color,
                outline="",
            )
            self._canvas.create_rectangle(
                px - half + block,
                py - half,
                px + half - block,
                py + half,
                fill=shadow_color,
                outline="",
            )
            pupil_half = half - block
            self._canvas.create_rectangle(
                px - pupil_half,
                py - pupil_half + block,
                px + pupil_half,
                py + pupil_half - block,
                fill=pupil_color,
                outline="",
            )
            self._canvas.create_rectangle(
                px - pupil_half + block,
                py - pupil_half,
                px + pupil_half - block,
                py + pupil_half,
                fill=pupil_color,
                outline="",
            )
            self._canvas.create_rectangle(
                px - pupil_half + block,
                py - pupil_half + block,
                px - pupil_half + block * 2,
                py - pupil_half + block * 2,
                fill=highlight_color,
                outline="",
            )

        nose_x = snap(cx)
        nose_y = snap(cy + scale * 0.055)
        self._canvas.create_rectangle(
            nose_x,
            nose_y,
            nose_x + block,
            nose_y + block * 3,
            fill=shadow_color,
            outline="",
        )
        self._canvas.create_rectangle(
            nose_x - block,
            nose_y + block * 2,
            nose_x + block,
            nose_y + block * 3,
            fill=eye_color,
            outline="",
        )
        self._canvas.create_rectangle(
            nose_x - block,
            nose_y + block * 2,
            nose_x,
            nose_y + max(block * 2 + 1, block * 5 // 2),
            fill=highlight_color,
            outline="",
        )

        # Explicit gestures need block-level silhouettes. Relying only on the
        # normalized eye/mouth scalars made most expressions collapse to the
        # same pixels after snapping at 800x480.
        brow_y = snap(eye_y - block * 11)

        def draw_brow(eye_cx: float, outer_level: int, inner_level: int) -> None:
            for offset, level in ((-6, outer_level), (0, inner_level)):
                left = snap(eye_cx + offset * block)
                top = brow_y + level * block
                self._canvas.create_rectangle(
                    left,
                    top,
                    left + block * 6,
                    top + block,
                    fill=shadow_color,
                    outline="",
                )
                self._canvas.create_rectangle(
                    left,
                    top,
                    left + block * 6,
                    top + max(1, block // 2),
                    fill=eye_color,
                    outline="",
                )

        speech_lift = -1 if pose.mouth_open > 0.52 else 0
        if pose.expression == "happy":
            draw_brow(cx - eye_dx, 0 + speech_lift, -1 + speech_lift)
            draw_brow(cx + eye_dx, -1 + speech_lift, 0 + speech_lift)
        elif pose.expression == "curious":
            draw_brow(cx - eye_dx, -2, -2)
            draw_brow(cx + eye_dx, 0, 0)
        elif pose.expression == "surprised":
            draw_brow(cx - eye_dx, -2, -2)
            draw_brow(cx + eye_dx, -2, -2)
        elif pose.expression == "confused":
            draw_brow(cx - eye_dx, -1, 0)
            draw_brow(cx + eye_dx, 0, -1)
        elif pose.expression == "focused":
            draw_brow(cx - eye_dx, -1, 1)
            draw_brow(cx + eye_dx, 1, -1)
        elif pose.expression == "sad":
            draw_brow(cx - eye_dx, 1, -1)
            draw_brow(cx + eye_dx, -1, 1)
        elif pose.expression == "skeptical":
            draw_brow(cx - eye_dx, -2, -2)
            draw_brow(cx + eye_dx, 1, 1)
        elif pose.expression == "excited":
            draw_brow(cx - eye_dx, -2 + speech_lift, -2 + speech_lift)
            draw_brow(cx + eye_dx, -2 + speech_lift, -2 + speech_lift)
        elif pose.expression == "playful":
            draw_brow(cx - eye_dx, -2, -1)
            draw_brow(cx + eye_dx, 0, 1)
        elif pose.expression in {"speaking", "attentive", "listening"}:
            draw_brow(cx - eye_dx, speech_lift, speech_lift)
            draw_brow(cx + eye_dx, speech_lift, speech_lift)

        if pose.expression in {"happy", "excited", "playful"}:
            cheek_y = snap(eye_y + block * 5)
            for cheek_x in (cx - eye_dx - block * 8, cx + eye_dx + block * 5):
                self._canvas.create_rectangle(
                    snap(cheek_x),
                    cheek_y,
                    snap(cheek_x) + block * 5,
                    cheek_y + block,
                    fill=shadow_color,
                    outline="",
                )
                self._canvas.create_rectangle(
                    snap(cheek_x) + block * 2,
                    cheek_y,
                    snap(cheek_x) + block * 3,
                    cheek_y + max(1, block // 2),
                    fill=highlight_color,
                    outline="",
                )

        if pose.expression == "excited":
            for direction in (-1, 1):
                sparkle_x = snap(cx + direction * (eye_dx + block * 16))
                sparkle_y = snap(eye_y - block * 3)
                self._canvas.create_rectangle(
                    sparkle_x,
                    sparkle_y - block * 2,
                    sparkle_x + block,
                    sparkle_y + block * 3,
                    fill=highlight_color,
                    outline="",
                )
                self._canvas.create_rectangle(
                    sparkle_x - block * 2,
                    sparkle_y,
                    sparkle_x + block * 3,
                    sparkle_y + block,
                    fill=eye_color,
                    outline="",
                )
        elif pose.expression == "sad":
            tear_x = snap(cx + eye_dx + block * 5)
            tear_y = snap(eye_y + block * 7)
            self._canvas.create_rectangle(
                tear_x,
                tear_y,
                tear_x + block * 2,
                tear_y + block * 4,
                fill=shadow_color,
                outline="",
            )
            self._canvas.create_rectangle(
                tear_x,
                tear_y,
                tear_x + block,
                tear_y + block * 2,
                fill=highlight_color,
                outline="",
            )
        elif pose.expression == "surprised":
            for direction in (-1, 1):
                accent_x = snap(cx + direction * (eye_dx + block * 15))
                accent_y = snap(eye_y - block)
                self._canvas.create_rectangle(
                    accent_x,
                    accent_y,
                    accent_x + block,
                    accent_y + block * 3,
                    fill=highlight_color,
                    outline="",
                )

        mouth_y = snap(cy + scale * 0.23)
        mouth_half_w = block * max(7, min(14, round(6 + pose.mouth_width * 10)))

        def draw_mouth_segment(
            left: float,
            top: float,
            right: float,
            bottom: float,
        ) -> None:
            self._canvas.create_rectangle(
                left,
                top,
                right,
                bottom,
                fill=shadow_color,
                outline="",
            )
            self._canvas.create_rectangle(
                left,
                top,
                right,
                min(bottom, top + max(1, block // 2)),
                fill=mouth_color,
                outline="",
            )

        if pose.mouth_open > 0.08:
            # Four-sided pixel mouth: the aperture and width change on every
            # articulation phase while the current emotional brows remain.
            open_blocks = max(3, min(14, round(2 + pose.mouth_open * 13)))
            dynamic_half_w = mouth_half_w
            if pose.mouth_open > 0.62:
                dynamic_half_w = max(block * 7, mouth_half_w - block * 2)
            left = snap(cx - dynamic_half_w)
            right = snap(cx + dynamic_half_w)
            top = snap(mouth_y - open_blocks * block / 2)
            bottom = top + open_blocks * block
            self._canvas.create_rectangle(
                left + block,
                top + block,
                right - block,
                bottom - block,
                fill=pupil_color,
                outline="",
            )
            self._canvas.create_rectangle(
                left + block,
                top,
                right - block,
                top + block,
                fill=highlight_color,
                outline="",
            )
            self._canvas.create_rectangle(
                left + block,
                bottom - block,
                right - block,
                bottom,
                fill=shadow_color,
                outline="",
            )
            self._canvas.create_rectangle(
                left,
                top + block,
                left + block,
                bottom - block,
                fill=mouth_color,
                outline="",
            )
            if open_blocks >= 5:
                self._canvas.create_rectangle(
                    left + block * 2,
                    top + block,
                    right - block * 2,
                    top + block * 2,
                    fill=highlight_color,
                    outline="",
                )
            if open_blocks >= 7:
                self._canvas.create_rectangle(
                    left + block * 3,
                    bottom - block * 2,
                    right - block * 3,
                    bottom - block,
                    fill=mouth_color,
                    outline="",
                )
            self._canvas.create_rectangle(
                right - block,
                top + block,
                right,
                bottom - block,
                fill=mouth_color,
                outline="",
            )
        elif pose.expression in {"happy", "excited"}:
            draw_mouth_segment(
                snap(cx - mouth_half_w),
                mouth_y,
                snap(cx - block * 3),
                mouth_y + block,
            )
            draw_mouth_segment(
                snap(cx - block * 3),
                mouth_y + block,
                snap(cx + block * 3),
                mouth_y + block * 2,
            )
            draw_mouth_segment(
                snap(cx + block * 3),
                mouth_y,
                snap(cx + mouth_half_w),
                mouth_y + block,
            )
        elif pose.expression in {"confused", "skeptical"}:
            draw_mouth_segment(
                snap(cx - mouth_half_w),
                mouth_y,
                snap(cx),
                mouth_y + block,
            )
            draw_mouth_segment(
                snap(cx),
                mouth_y + block,
                snap(cx + mouth_half_w),
                mouth_y + block * 2,
            )
        elif pose.expression == "sad":
            draw_mouth_segment(
                snap(cx - mouth_half_w),
                mouth_y + block,
                snap(cx - block * 3),
                mouth_y + block * 2,
            )
            draw_mouth_segment(
                snap(cx - block * 3),
                mouth_y,
                snap(cx + block * 3),
                mouth_y + block,
            )
            draw_mouth_segment(
                snap(cx + block * 3),
                mouth_y + block,
                snap(cx + mouth_half_w),
                mouth_y + block * 2,
            )
        elif pose.expression == "curious":
            draw_mouth_segment(
                snap(cx - block * 2),
                mouth_y,
                snap(cx + block * 5),
                mouth_y + block,
            )
        elif pose.expression == "focused":
            draw_mouth_segment(
                snap(cx - block * 3),
                mouth_y,
                snap(cx + block * 3),
                mouth_y + block,
            )
        elif pose.expression == "playful":
            draw_mouth_segment(
                snap(cx - block * 5),
                mouth_y,
                snap(cx + mouth_half_w),
                mouth_y + block,
            )
        else:
            draw_mouth_segment(
                snap(cx - mouth_half_w),
                mouth_y,
                snap(cx + mouth_half_w),
                mouth_y + block,
            )

        # Small state glyph above the eyes: thinking/attention/error remain
        # legible even on a low-resolution appliance display.
        if pose.expression in {"thinking", "working"}:
            for idx in range(3):
                x = snap(cx + (idx - 1) * block * 2)
                y = snap(cy - scale * 0.36 - idx * block * 0.4)
                self._canvas.create_rectangle(x, y, x + block, y + block, fill=eye_color, outline="")

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

    def capabilities(self) -> list[CapabilityDescriptor]:
        return [
            CapabilityDescriptor(
                key="face.display",
                description="mostrar una cara pixelada animada",
                available=self._running,
                source="face",
            ),
            CapabilityDescriptor(
                key="face.expression",
                description="cambiar la expresión de la cara entre gestos disponibles",
                available=self._running,
                source="face",
            ),
        ]

    def set_state(self, state: AssistantState) -> None:
        self.animator.set_state(state)

    def set_gaze(self, x: float, y: float) -> None:
        self.animator.set_gaze(x, y)

    def set_speech_level(self, level: float) -> None:
        self.animator.set_speech_level(level)

    def set_expression(self, expression: str, duration_seconds: float = 5.0) -> None:
        self.animator.set_expression(expression, duration_seconds)
        logger.info(
            "face_expression stage=requested expression=%s duration_seconds=%.1f",
            expression.strip().lower(),
            duration_seconds,
        )

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

    def update(self) -> None:
        """Pump one Tk event-loop iteration for integration in LabRunner."""
        if not self._root or not self._running:
            return
        try:
            self._root.update_idletasks()
            self._root.update()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tkinter update stopped: %s", exc)
            self.close()

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
