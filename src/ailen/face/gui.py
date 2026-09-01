"""
Tkinter-based 128-bit-inspired high-detail portrait and vector face renderer for AILEN.

Provides an ultra-lightweight, zero-pip-dependency graphical face renderer
using Python stdlib tkinter canvas. Consumes normalized FacePose parameters.

Enhanced version with more details, color and realism.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ailen.core.capabilities import CapabilityDescriptor
from ailen.domain.enums import AssistantState
from ailen.face.animator import FaceAnimator
from ailen.face.contracts import CONVERSATIONAL_EXPRESSIONS, FACE_EXPRESSIONS
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
        skin_tone: str = "light",  # "light", "medium", "dark"
        hair_color: str = "blue",  # "blue", "black", "brown", "pink", "green"
    ):
        self.width = width
        self.height = height
        self.fullscreen = fullscreen
        self.fps_limit = fps_limit
        self.animator = animator or FaceAnimator()
        if style not in {"portrait", "vector", "pixel"}:
            raise ValueError(f"unknown face renderer style: {style}")
        self.style = style
        self.skin_tone = skin_tone if skin_tone in {"light", "medium", "dark"} else "light"
        self.hair_color = hair_color

        self._root: Any = None
        self._canvas: Any = None
        self._running: bool = False
        self._delay_ms = max(10, int(1000 / self.fps_limit))
        self._last_rendered_expression: str | None = None
        self._portrait_assets: dict[str, Any] = {}
        self._portrait_asset_error: str | None = None

    @property
    def available_expressions(self) -> tuple[str, ...]:
        return FACE_EXPRESSIONS

    @property
    def conversational_expressions(self) -> tuple[str, ...]:
        return CONVERSATIONAL_EXPRESSIONS

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

    def is_display_active(self) -> bool:
        """Return whether the Tk window is currently active."""
        return self._running and self._root is not None

    def start_window(self, interactive_keys: bool = False) -> None:
        """Initialize Tkinter window and start rendering loop."""
        import tkinter as tk

        self._root = tk.Tk()
        self._root.title("AILEN — 128-Bit Portrait Face")
        self._root.geometry(f"{self.width}x{self.height}")
        self._root.configure(bg="#030712")
        self._root.protocol("WM_DELETE_WINDOW", self.close)

        if self.fullscreen:
            self._root.attributes("-fullscreen", True)

        self._canvas = tk.Canvas(
            self._root,
            width=self.width,
            height=self.height,
            bg="#030712",
            highlightthickness=0,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)

        if self.style == "portrait":
            self._load_portrait_assets(tk)

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

        w = float(self._canvas.winfo_width() or self.width)
        h = float(self._canvas.winfo_height() or self.height)
        cx = w / 2.0
        cy = h / 2.0

        if self.style == "portrait" and self._portrait_assets:
            self._draw_portrait_face(pose=pose, width=w, height=h)
            return

        # Color scheme based on state and expression
        # Base colors (can be customized)
        if self.skin_tone == "light":
            skin_base = "#f5e6d3"
            skin_shadow = "#d4b896"
            skin_highlight = "#fff0e0"
        elif self.skin_tone == "medium":
            skin_base = "#c68a5e"
            skin_shadow = "#9a6b44"
            skin_highlight = "#e0b08a"
        else:  # dark
            skin_base = "#8a5a3b"
            skin_shadow = "#5c3a24"
            skin_highlight = "#a87850"

        # Hair color mapping
        hair_colors = {
            "blue": {"base": "#1a3a5c", "highlight": "#2d5a8a", "shadow": "#0d2138", "shine": "#4a8ab5"},
            "black": {"base": "#1a1a1a", "highlight": "#3a3a3a", "shadow": "#0a0a0a", "shine": "#5a5a5a"},
            "brown": {"base": "#5c3a24", "highlight": "#7a5240", "shadow": "#3a2414", "shine": "#a07050"},
            "pink": {"base": "#b85c7a", "highlight": "#d47a9a", "shadow": "#8a3a5c", "shine": "#f0a0b8"},
            "green": {"base": "#2a5c3a", "highlight": "#3a7a52", "shadow": "#1a3a24", "shine": "#5a9a70"},
        }
        hc = hair_colors.get(self.hair_color, hair_colors["blue"])

        # State-specific eye and mouth colors
        eye_color = "#38bdf8"       # Sky blue
        highlight_color = "#bae6fd" # Ice blue
        shadow_color = "#0284c7"    # Deep cyan
        pupil_color = "#020617"     # Void core
        mouth_color = "#c96f82"     # Natural rose lip tone
        if pose.expression == "error":
            eye_color = "#f43f5e"   # Rose/Red
            highlight_color = "#fecdd3"
            shadow_color = "#be123c"
            pupil_color = "#4c0519"
            mouth_color = "#be123c"
        elif pose.expression == "degraded":
            eye_color = "#fbbf24"   # Amber
            highlight_color = "#fef3c7"
            shadow_color = "#d97706"
            pupil_color = "#451a03"
            mouth_color = "#d97706"

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
                skin_base=skin_base,
                skin_shadow=skin_shadow,
                skin_highlight=skin_highlight,
                hair_colors=hc,
            )
            return

        # Vector fallback (simplified)
        eye_spacing = min(w, h) * 0.28
        eye_rx = min(w, h) * 0.14
        eye_ry = min(w, h) * 0.18
        left_cx = cx - eye_spacing
        right_cx = cx + eye_spacing
        eye_cy = cy - min(w, h) * 0.08

        self._draw_eye(left_cx, eye_cy, eye_rx, eye_ry, pose.left_eye_open, pose.gaze_x, pose.gaze_y, pose.pupil_size, eye_color, pupil_color)
        self._draw_eye(right_cx, eye_cy, eye_rx, eye_ry, pose.right_eye_open, pose.gaze_x, pose.gaze_y, pose.pupil_size, eye_color, pupil_color)

        mouth_cy = cy + min(w, h) * 0.22
        mouth_w = eye_spacing * (0.8 + pose.mouth_width * 0.4)
        mouth_h = max(2.0, min(w, h) * 0.12 * pose.mouth_open)

        if pose.mouth_open > 0.05:
            self._canvas.create_oval(
                cx - mouth_w / 2, mouth_cy - mouth_h / 2,
                cx + mouth_w / 2, mouth_cy + mouth_h / 2,
                fill=mouth_color, outline="",
            )
        else:
            self._canvas.create_line(
                cx - mouth_w / 2, mouth_cy,
                cx + mouth_w / 2, mouth_cy,
                fill=mouth_color, width=4, capstyle="round",
            )

    @staticmethod
    def _portrait_asset_dir() -> Path:
        """Return the packaged raster portrait asset directory."""
        return Path(__file__).resolve().parent / "assets" / "portrait"

    def _load_portrait_assets(self, tk: Any) -> None:
        """Load the generated AILEN portrait and small animation patches once."""
        asset_dir = self._portrait_asset_dir()
        filenames = {
            "base": "ailen_portrait_base.png",
            "eyes_left": "eyes_left.png",
            "eyes_right": "eyes_right.png",
            "eyes_up": "eyes_up.png",
            "eyes_down": "eyes_down.png",
            "eyes_blink": "eyes_blink.png",
            "eyes_blink_left": "eyes_blink_left.png",
            "eyes_blink_right": "eyes_blink_right.png",
            "mouth_small": "mouth_small.png",
            "mouth_open": "mouth_open.png",
        }
        loaded: dict[str, Any] = {}
        try:
            for key, filename in filenames.items():
                path = asset_dir / filename
                if not path.is_file():
                    raise FileNotFoundError(path)
                loaded[key] = tk.PhotoImage(file=str(path))
        except (OSError, tk.TclError) as exc:
            self._portrait_assets = {}
            self._portrait_asset_error = str(exc)
            logger.error(
                "portrait_assets stage=load result=unavailable error=%s",
                exc,
            )
            raise RuntimeError(f"portrait renderer assets are unavailable: {exc}") from exc

        self._portrait_assets = loaded
        self._portrait_asset_error = None
        logger.info(
            "portrait_assets stage=load result=ready count=%d path=%s",
            len(loaded),
            asset_dir,
        )

    def _draw_portrait_face(self, pose: FacePose, width: float, height: float) -> None:
        """Animate the generated portrait with raster eye/mouth patches and parallax."""
        if not self._canvas or not self._portrait_assets:
            return

        base = self._portrait_assets["base"]
        ref_w = float(base.width())
        ref_h = float(base.height())

        # The portrait itself remains untouched: animation is produced by moving the
        # raster layer and replacing only small eye/mouth regions with derived frames.
        motion_x = round(pose.gaze_x * 4.0 + pose.head_tilt * 3.0)
        motion_y = round(-pose.gaze_y * 2.0 + abs(pose.head_tilt) * 1.5)
        origin_x = (width - ref_w) / 2.0 + motion_x
        origin_y = (height - ref_h) / 2.0 + motion_y

        self._canvas.create_image(
            origin_x,
            origin_y,
            anchor="nw",
            image=base,
        )

        left_closed = pose.left_eye_open < 0.25
        right_closed = pose.right_eye_open < 0.25
        eye_patch: Any | None = None
        if left_closed and right_closed:
            eye_patch = self._portrait_assets["eyes_blink"]
        elif left_closed:
            eye_patch = self._portrait_assets["eyes_blink_left"]
        elif right_closed:
            eye_patch = self._portrait_assets["eyes_blink_right"]
        elif abs(pose.gaze_x) >= abs(pose.gaze_y) and abs(pose.gaze_x) > 0.18:
            eye_patch = self._portrait_assets[
                "eyes_right" if pose.gaze_x > 0.0 else "eyes_left"
            ]
        elif abs(pose.gaze_y) > 0.18:
            eye_patch = self._portrait_assets[
                "eyes_up" if pose.gaze_y > 0.0 else "eyes_down"
            ]

        if eye_patch is not None:
            self._canvas.create_image(
                origin_x + 320,
                origin_y + 120,
                anchor="nw",
                image=eye_patch,
            )

        mouth_patch: Any | None = None
        if pose.mouth_open > 0.46:
            mouth_patch = self._portrait_assets["mouth_open"]
        elif pose.mouth_open > 0.08:
            mouth_patch = self._portrait_assets["mouth_small"]

        if mouth_patch is not None:
            self._canvas.create_image(
                origin_x + 350,
                origin_y + 200,
                anchor="nw",
                image=mouth_patch,
            )

        # Lightweight state cue in the same visual language as the generated scene.
        if pose.expression in {"error", "degraded"}:
            state_color = "#f43f5e" if pose.expression == "error" else "#fbbf24"
            self._canvas.create_oval(
                origin_x + ref_w - 32,
                origin_y + 22,
                origin_x + ref_w - 20,
                origin_y + 34,
                fill=state_color,
                outline="",
            )

    @staticmethod
    def _pixel_block_size(scale: float) -> int:
        """Return resolution scale factor for responsive rendering."""
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
        skin_base: str = "#f5e6d3",
        skin_shadow: str = "#d4b896",
        skin_highlight: str = "#fff0e0",
        hair_colors: dict[str, str] | None = None,
    ) -> None:
        """Render a detailed bust portrait while preserving the lightweight FacePose contract."""
        if not self._canvas:
            return

        if hair_colors is None:
            hair_colors = {
                "base": "#1a3a5c",
                "highlight": "#2d5a8a",
                "shadow": "#0d2138",
                "shine": "#4a8ab5",
            }

        scale = min(width, height)
        cx = width / 2.0
        cy = height / 2.0

        # Sub-pixel 3D Parallax & Head Tilt Offsets across Z-planes
        tilt = pose.head_tilt * 12.0
        p_bg_x = pose.gaze_x * scale * 0.012
        p_bg_y = pose.gaze_y * scale * 0.008
        p_head_x = pose.gaze_x * scale * 0.025
        p_head_y = pose.gaze_y * scale * 0.018
        p_face_x = pose.gaze_x * scale * 0.045
        p_face_y = pose.gaze_y * scale * 0.030
        p_fore_x = pose.gaze_x * scale * 0.065

        # -------------------------------------------------------------
        # 0. Semi-dark environment — no circular portrait halo.
        # -------------------------------------------------------------
        self._canvas.create_rectangle(0, 0, width, height, fill="#030712", outline="")
        self._canvas.create_rectangle(
            width * 0.08 + p_bg_x, 0,
            width * 0.30 + p_bg_x, height,
            fill="#06101f", outline="",
        )
        self._canvas.create_rectangle(
            width * 0.72 + p_bg_x, 0,
            width * 0.92 + p_bg_x, height,
            fill="#071425", outline="",
        )
        self._canvas.create_polygon(
            [
                width * 0.02 + p_bg_x, height * 0.20 + p_bg_y,
                width * 0.20 + p_bg_x, height * 0.06 + p_bg_y,
                width * 0.38 + p_bg_x, height * 0.06 + p_bg_y,
                width * 0.28 + p_bg_x, height * 0.18 + p_bg_y,
            ],
            fill="#08182c", outline="",
        )
        self._canvas.create_polygon(
            [
                width * 0.98 + p_bg_x, height * 0.28 + p_bg_y,
                width * 0.84 + p_bg_x, height * 0.13 + p_bg_y,
                width * 0.66 + p_bg_x, height * 0.13 + p_bg_y,
                width * 0.76 + p_bg_x, height * 0.25 + p_bg_y,
            ],
            fill="#091a30", outline="",
        )
        tech_color = "#0d2a46"
        glow_color = "#164e75"
        for lane in (0.16, 0.84):
            lane_x = width * lane + p_bg_x
            self._canvas.create_line(
                lane_x, height * 0.10 + p_bg_y,
                lane_x, height * 0.86 + p_bg_y,
                fill=tech_color, width=1,
            )
        for y_ratio in (0.18, 0.72, 0.86):
            self._canvas.create_line(
                width * 0.04 + p_bg_x, height * y_ratio + p_bg_y,
                width * 0.26 + p_bg_x, height * y_ratio + p_bg_y,
                fill=tech_color, width=1,
            )
            self._canvas.create_line(
                width * 0.74 + p_bg_x, height * y_ratio + p_bg_y,
                width * 0.96 + p_bg_x, height * y_ratio + p_bg_y,
                fill=tech_color, width=1,
            )
        for x_ratio, y_ratio, radius in (
            (0.08, 0.34, 3.0),
            (0.14, 0.64, 2.0),
            (0.90, 0.22, 3.0),
            (0.86, 0.58, 2.0),
            (0.94, 0.78, 2.5),
        ):
            dot_x = width * x_ratio + p_bg_x
            dot_y = height * y_ratio + p_bg_y
            self._canvas.create_oval(
                dot_x - radius, dot_y - radius,
                dot_x + radius, dot_y + radius,
                fill=glow_color, outline="",
            )

        # -------------------------------------------------------------
        # 1. Back Hair Volume (Framing behind head) - more layered
        # -------------------------------------------------------------
        back_hair_x = cx + p_head_x
        back_hair_y = cy + p_head_y - scale * 0.12
        bh_rx = scale * 0.39
        bh_ry = scale * 0.46

        # Outer silhouette
        self._canvas.create_polygon(
            [
                back_hair_x - bh_rx * 0.80, back_hair_y - bh_ry * 0.60,
                back_hair_x - bh_rx, back_hair_y,
                back_hair_x - bh_rx * 0.95, back_hair_y + bh_ry * 0.65,
                back_hair_x - bh_rx * 0.50, back_hair_y + bh_ry * 0.85,
                back_hair_x + bh_rx * 0.50, back_hair_y + bh_ry * 0.85,
                back_hair_x + bh_rx * 0.95, back_hair_y + bh_ry * 0.65,
                back_hair_x + bh_rx, back_hair_y,
                back_hair_x + bh_rx * 0.80, back_hair_y - bh_ry * 0.60,
                back_hair_x, back_hair_y - bh_ry * 0.92,
            ],
            fill=hair_colors["shadow"], outline=hair_colors["highlight"], width=2, smooth=True,
        )
        # Inner hair mass
        self._canvas.create_polygon(
            [
                back_hair_x - bh_rx * 0.65, back_hair_y - bh_ry * 0.45,
                back_hair_x - bh_rx * 0.85, back_hair_y + bh_ry * 0.10,
                back_hair_x - bh_rx * 0.75, back_hair_y + bh_ry * 0.55,
                back_hair_x - bh_rx * 0.35, back_hair_y + bh_ry * 0.70,
                back_hair_x + bh_rx * 0.35, back_hair_y + bh_ry * 0.70,
                back_hair_x + bh_rx * 0.75, back_hair_y + bh_ry * 0.55,
                back_hair_x + bh_rx * 0.85, back_hair_y + bh_ry * 0.10,
                back_hair_x + bh_rx * 0.65, back_hair_y - bh_ry * 0.45,
                back_hair_x, back_hair_y - bh_ry * 0.75,
            ],
            fill=hair_colors["base"], outline="", smooth=True,
        )
        # Hair shine arcs
        for dx in (-0.4, 0, 0.4):
            self._canvas.create_line(
                back_hair_x + dx * bh_rx * 0.3, back_hair_y - bh_ry * 0.5,
                back_hair_x + dx * bh_rx * 0.3, back_hair_y + bh_ry * 0.6,
                fill=hair_colors["shine"], width=2, smooth=True,
            )

        # -------------------------------------------------------------
        # 2. Neck, shoulders and a normal crew-neck T-shirt.
        # -------------------------------------------------------------
        neck_x = cx + p_head_x * 0.6
        neck_y = cy + scale * 0.16
        neck_w = scale * 0.20
        neck_h = scale * 0.20

        # Neck skin base with gradient approximation (multiple polygons)
        self._canvas.create_polygon(
            [
                neck_x - neck_w * 0.50, neck_y,
                neck_x - neck_w * 0.65, neck_y + neck_h,
                neck_x + neck_w * 0.65, neck_y + neck_h,
                neck_x + neck_w * 0.50, neck_y,
            ],
            fill=skin_shadow, outline=skin_base, width=1, smooth=False,
        )
        # Mid tone
        self._canvas.create_polygon(
            [
                neck_x - neck_w * 0.40, neck_y,
                neck_x - neck_w * 0.45, neck_y + neck_h * 0.9,
                neck_x + neck_w * 0.45, neck_y + neck_h * 0.9,
                neck_x + neck_w * 0.40, neck_y,
            ],
            fill=skin_base, outline="", smooth=False,
        )
        # Highlight on neck front
        self._canvas.create_polygon(
            [
                neck_x - neck_w * 0.15, neck_y,
                neck_x - neck_w * 0.10, neck_y + neck_h * 0.7,
                neck_x + neck_w * 0.10, neck_y + neck_h * 0.7,
                neck_x + neck_w * 0.15, neck_y,
            ],
            fill=skin_highlight, outline="", smooth=True,
        )

        # Shadow under chin cast on neck
        self._canvas.create_polygon(
            [
                neck_x - neck_w * 0.45, neck_y,
                neck_x, neck_y + scale * 0.08,
                neck_x + neck_w * 0.45, neck_y,
            ],
            fill="#050a14", outline="", smooth=True,
        )

        collar_y = neck_y + neck_h * 0.62
        shirt_base = "#cbd5e1"
        shirt_shadow = "#94a3b8"
        shirt_highlight = "#e2e8f0"
        self._canvas.create_polygon(
            [
                cx - scale * 0.66, height,
                cx - scale * 0.60, collar_y + scale * 0.10,
                cx - scale * 0.40, collar_y - scale * 0.015,
                neck_x - neck_w * 0.56, collar_y + scale * 0.025,
                cx, collar_y + scale * 0.105,
                neck_x + neck_w * 0.56, collar_y + scale * 0.025,
                cx + scale * 0.40, collar_y - scale * 0.015,
                cx + scale * 0.60, collar_y + scale * 0.10,
                cx + scale * 0.66, height,
            ],
            fill=shirt_base, outline="#64748b", width=2, smooth=True,
        )
        self._canvas.create_polygon(
            [
                cx - scale * 0.66, height,
                cx - scale * 0.60, collar_y + scale * 0.10,
                cx - scale * 0.42, collar_y + scale * 0.02,
                cx - scale * 0.34, height,
            ],
            fill=shirt_shadow, outline="", smooth=True,
        )
        self._canvas.create_polygon(
            [
                cx + scale * 0.34, height,
                cx + scale * 0.42, collar_y + scale * 0.02,
                cx + scale * 0.60, collar_y + scale * 0.10,
                cx + scale * 0.66, height,
            ],
            fill=shirt_shadow, outline="", smooth=True,
        )
        self._canvas.create_line(
            neck_x - neck_w * 0.56, collar_y + scale * 0.025,
            cx, collar_y + scale * 0.105,
            neck_x + neck_w * 0.56, collar_y + scale * 0.025,
            fill=shirt_highlight, width=3, smooth=True,
        )
        self._canvas.create_line(
            cx - scale * 0.52, collar_y + scale * 0.09,
            cx - scale * 0.60, height * 0.94,
            fill="#aab6c7", width=1,
        )
        self._canvas.create_line(
            cx + scale * 0.52, collar_y + scale * 0.09,
            cx + scale * 0.60, height * 0.94,
            fill="#aab6c7", width=1,
        )

        # -------------------------------------------------------------
        # 3. Organic Head Silhouette & Porcelain Skin Tones (multi-layer)
        # -------------------------------------------------------------
        head_cx = cx + p_head_x
        head_cy = cy + p_head_y - scale * 0.105
        h_rx = scale * 0.30
        h_ry_top = scale * 0.31
        h_ry_bot = scale * 0.35

        # Outer silhouette (edge with ambient occlusion)
        face_pts = [
            head_cx - h_rx * 0.85, head_cy - h_ry_top * 0.70,
            head_cx - h_rx * 0.98, head_cy - h_ry_top * 0.15,
            head_cx - h_rx * 0.94, head_cy + h_ry_bot * 0.32,
            head_cx - h_rx * 0.68, head_cy + h_ry_bot * 0.72,
            head_cx - h_rx * 0.30, head_cy + h_ry_bot * 0.95,
            head_cx, head_cy + h_ry_bot * 1.02,
            head_cx + h_rx * 0.30, head_cy + h_ry_bot * 0.95,
            head_cx + h_rx * 0.68, head_cy + h_ry_bot * 0.72,
            head_cx + h_rx * 0.94, head_cy + h_ry_bot * 0.32,
            head_cx + h_rx * 0.98, head_cy - h_ry_top * 0.15,
            head_cx + h_rx * 0.85, head_cy - h_ry_top * 0.70,
            head_cx, head_cy - h_ry_top * 0.98,
        ]
        self._canvas.create_polygon(
            face_pts,
            fill=skin_shadow,
            outline="#a77f6f",
            width=2,
            smooth=True,
        )

        # Inner skin base layer (slightly smaller)
        inner_pts = [
            head_cx - h_rx * 0.78, head_cy - h_ry_top * 0.60,
            head_cx - h_rx * 0.88, head_cy - h_ry_top * 0.10,
            head_cx - h_rx * 0.84, head_cy + h_ry_bot * 0.28,
            head_cx - h_rx * 0.58, head_cy + h_ry_bot * 0.65,
            head_cx - h_rx * 0.25, head_cy + h_ry_bot * 0.88,
            head_cx, head_cy + h_ry_bot * 0.94,
            head_cx + h_rx * 0.25, head_cy + h_ry_bot * 0.88,
            head_cx + h_rx * 0.58, head_cy + h_ry_bot * 0.65,
            head_cx + h_rx * 0.84, head_cy + h_ry_bot * 0.28,
            head_cx + h_rx * 0.88, head_cy - h_ry_top * 0.10,
            head_cx + h_rx * 0.78, head_cy - h_ry_top * 0.60,
            head_cx, head_cy - h_ry_top * 0.85,
        ]
        self._canvas.create_polygon(inner_pts, fill=skin_base, outline="", smooth=True)

        # Highlight areas (forehead, cheeks, chin)
        highlight_pts = [
            head_cx - h_rx * 0.45, head_cy - h_ry_top * 0.60,
            head_cx - h_rx * 0.50, head_cy - h_ry_top * 0.15,
            head_cx - h_rx * 0.35, head_cy + h_ry_bot * 0.10,
            head_cx, head_cy + h_ry_bot * 0.25,
            head_cx + h_rx * 0.35, head_cy + h_ry_bot * 0.10,
            head_cx + h_rx * 0.50, head_cy - h_ry_top * 0.15,
            head_cx + h_rx * 0.45, head_cy - h_ry_top * 0.60,
            head_cx, head_cy - h_ry_top * 0.75,
        ]
        self._canvas.create_polygon(highlight_pts, fill=skin_highlight, outline="", smooth=True, stipple="gray50")

        # Subtle cheek shadows
        for side_sign in (-1, 1):
            shadow_pts = [
                head_cx + side_sign * h_rx * 0.55, head_cy + h_ry_bot * 0.05,
                head_cx + side_sign * h_rx * 0.75, head_cy + h_ry_bot * 0.25,
                head_cx + side_sign * h_rx * 0.65, head_cy + h_ry_bot * 0.50,
                head_cx + side_sign * h_rx * 0.40, head_cy + h_ry_bot * 0.35,
            ]
            self._canvas.create_polygon(shadow_pts, fill=skin_shadow, outline="", smooth=True)

        # Cyber Comm Ears & Glowing Audio Cuffs (more detailed)
        for side_sign in (-1, 1):
            ear_x = head_cx + side_sign * (h_rx * 0.96)
            ear_y = head_cy + scale * 0.02
            # Ear cartilage (outer)
            self._canvas.create_polygon(
                [
                    ear_x, ear_y - scale * 0.08,
                    ear_x + side_sign * scale * 0.08, ear_y - scale * 0.02,
                    ear_x + side_sign * scale * 0.07, ear_y + scale * 0.06,
                    ear_x, ear_y + scale * 0.08,
                ],
                fill=skin_shadow, outline=skin_base, width=2, smooth=True,
            )
            # Inner ear shadow
            self._canvas.create_polygon(
                [
                    ear_x + side_sign * scale * 0.02, ear_y - scale * 0.04,
                    ear_x + side_sign * scale * 0.05, ear_y - scale * 0.01,
                    ear_x + side_sign * scale * 0.04, ear_y + scale * 0.03,
                    ear_x + side_sign * scale * 0.01, ear_y + scale * 0.04,
                ],
                fill="#9f7467", outline="", smooth=True,
            )
            # Glowing cyber cuff (Pulses with speech or state)
            cuff_glow = highlight_color if pose.mouth_open > 0.1 else shadow_color
            # Outer ring
            self._canvas.create_oval(
                ear_x + side_sign * scale * 0.04 - scale * 0.02, ear_y - scale * 0.02,
                ear_x + side_sign * scale * 0.04 + scale * 0.02, ear_y + scale * 0.02,
                fill="#020612", outline="#ffffff", width=1,
            )
            # Inner glow
            self._canvas.create_oval(
                ear_x + side_sign * scale * 0.04 - scale * 0.01, ear_y - scale * 0.01,
                ear_x + side_sign * scale * 0.04 + scale * 0.01, ear_y + scale * 0.01,
                fill=cuff_glow, outline="",
            )

        # -------------------------------------------------------------
        # 4. Natural cheek color and soft facial volume.
        # -------------------------------------------------------------
        cheek_spacing = scale * 0.19
        cheek_y = head_cy + scale * 0.105
        is_happy = pose.expression in ("happy", "excited", "playful", "wink")
        blush_color = "#d68a93" if is_happy else "#c78d89"
        blush_highlight = "#efb1ad" if is_happy else "#dfa6a0"

        for side_sign in (-1, 1):
            ch_x = head_cx + side_sign * cheek_spacing
            self._canvas.create_oval(
                ch_x - scale * 0.075, cheek_y - scale * 0.038,
                ch_x + scale * 0.075, cheek_y + scale * 0.038,
                fill=blush_color, outline="", stipple="gray50",
            )
            self._canvas.create_oval(
                ch_x - scale * 0.035, cheek_y - scale * 0.018,
                ch_x + scale * 0.035, cheek_y + scale * 0.018,
                fill=blush_highlight, outline="", stipple="gray75",
            )

        # -------------------------------------------------------------
        # 5. Stylized Anatomical Nose (with shading and specular)
        # -------------------------------------------------------------
        nose_cx = cx + p_face_x
        nose_cy = head_cy + p_face_y * 0.35 + scale * 0.068
        # Soft bridge shadow
        self._canvas.create_line(
            nose_cx - scale * 0.008, nose_cy - scale * 0.07,
            nose_cx - scale * 0.012, nose_cy,
            nose_cx + scale * 0.008, nose_cy + scale * 0.015,
            fill=skin_shadow, width=4, capstyle="round", smooth=True,
        )
        # Bridge highlight
        self._canvas.create_line(
            nose_cx - scale * 0.002, nose_cy - scale * 0.06,
            nose_cx - scale * 0.005, nose_cy,
            nose_cx + scale * 0.003, nose_cy + scale * 0.012,
            fill=skin_highlight, width=2, capstyle="round", smooth=True,
        )
        # Nostril shadows
        for side_sign in (-1, 1):
            self._canvas.create_oval(
                nose_cx + side_sign * scale * 0.018 - scale * 0.008, nose_cy + scale * 0.005 - scale * 0.005,
                nose_cx + side_sign * scale * 0.018 + scale * 0.008, nose_cy + scale * 0.005 + scale * 0.005,
                fill=skin_shadow, outline="",
            )
        # Nose tip specular glint
        self._canvas.create_rectangle(
            nose_cx - scale * 0.005, nose_cy - scale * 0.005,
            nose_cx + scale * 0.005, nose_cy + scale * 0.005,
            fill=skin_highlight, outline="",
        )

        # -------------------------------------------------------------
        # 6. High-Definition 32-Bit Articulated Eyebrows (with individual hairs)
        # -------------------------------------------------------------
        brow_spacing = scale * 0.20
        brow_base_y = head_cy + p_face_y * 0.35 - scale * 0.14

        for is_left, side_sign in ((True, -1), (False, 1)):
            brow_cx = cx + p_fore_x + (side_sign * brow_spacing)
            brow_y_off = -tilt if is_left else tilt

            mid_dy = 0.0
            inner_dy = 0.0
            outer_dy = 0.0

            # Expression-based brow positioning
            if pose.expression in ("happy", "excited"):
                mid_dy = -scale * 0.025
                inner_dy = -scale * 0.015
            elif pose.expression in ("surprised", "curious"):
                mid_dy = -scale * 0.060
                inner_dy = -scale * 0.045
                outer_dy = -scale * 0.035
            elif pose.expression in ("thinking", "working", "focused"):
                inner_dy = scale * 0.035
                mid_dy = scale * 0.015
                outer_dy = -scale * 0.015
            elif pose.expression in ("error", "sad"):
                inner_dy = -scale * 0.035
                outer_dy = scale * 0.025
            elif pose.expression == "skeptical":
                if is_left:
                    mid_dy = -scale * 0.050
                    inner_dy = -scale * 0.035
                else:
                    inner_dy = scale * 0.025

            b_in_x = brow_cx - side_sign * (scale * 0.09)
            b_mid_x = brow_cx
            b_out_x = brow_cx + side_sign * (scale * 0.09)
            b_in_y = brow_base_y + brow_y_off + inner_dy
            b_mid_y = brow_base_y + brow_y_off + mid_dy - scale * 0.015
            b_out_y = brow_base_y + brow_y_off + outer_dy

            # Eyebrow shadow underlay
            self._canvas.create_line(
                b_in_x, b_in_y + 2,
                b_mid_x, b_mid_y + 2,
                b_out_x, b_out_y + 2,
                fill="#020612", width=6, capstyle="round", smooth=True,
            )
            # Main eyebrow arch (use hair color for natural look)
            self._canvas.create_line(
                b_in_x, b_in_y,
                b_mid_x, b_mid_y,
                b_out_x, b_out_y,
                fill=hair_colors["base"], width=4.5, capstyle="round", smooth=True,
            )
            # Top specular sheen
            self._canvas.create_line(
                b_in_x + side_sign * 2, b_in_y - 1.5,
                b_mid_x, b_mid_y - 1.5,
                b_out_x - side_sign * 2, b_out_y - 1.5,
                fill=hair_colors["shine"], width=2, capstyle="round", smooth=True,
            )
            # Add individual hair strokes
            for t in range(5):
                fraction = t / 4
                hx = b_in_x + fraction * (b_out_x - b_in_x)
                hy = b_in_y + fraction * (b_out_y - b_in_y)
                self._canvas.create_line(
                    hx - 1, hy - 1,
                    hx + 1, hy + 1,
                    fill=hair_colors["highlight"], width=1,
                )

        # -------------------------------------------------------------
        # 7. Detailed bright eyes with responsive gaze.
        # -------------------------------------------------------------
        eye_spacing = scale * 0.20
        eye_base_y = head_cy + p_face_y * 0.35 - scale * 0.025
        eye_rx = scale * 0.125
        eye_ry = scale * 0.095

        for is_left, side_sign, openness in (
            (True, -1, pose.left_eye_open),
            (False, 1, pose.right_eye_open),
        ):
            eye_cx = cx + p_face_x + (side_sign * eye_spacing)
            eye_y_off = -tilt if is_left else tilt
            eye_y = eye_base_y + eye_y_off

            curr_ry = max(scale * 0.008, eye_ry * openness)

            # Double Eyelid Crease (Fold above eye) - more defined
            crease_y = eye_y - eye_ry * 1.35
            self._canvas.create_line(
                eye_cx - eye_rx * 0.70, crease_y + scale * 0.015,
                eye_cx, crease_y,
                eye_cx + eye_rx * 0.70, crease_y + scale * 0.015,
                fill="#162642", width=2.5, smooth=True,
            )
            # Add subtle shadow under crease
            self._canvas.create_line(
                eye_cx - eye_rx * 0.60, crease_y + scale * 0.025,
                eye_cx, crease_y + scale * 0.010,
                eye_cx + eye_rx * 0.60, crease_y + scale * 0.025,
                fill="#0a1426", width=1.5, smooth=True,
            )

            # Closed / Blinking Eyelash Wing
            if openness < 0.12:
                y_closed = eye_y
                # Outer lash shadow
                self._canvas.create_line(
                    eye_cx - eye_rx * 1.05, y_closed,
                    eye_cx, y_closed + scale * 0.025,
                    eye_cx + eye_rx * 1.15 * (1 if side_sign < 0 else -1), y_closed - scale * 0.020,
                    fill="#020612", width=7, capstyle="round", smooth=True,
                )
                # Upper eyeliner curve with winged corner
                self._canvas.create_line(
                    eye_cx - eye_rx * 1.05, y_closed,
                    eye_cx, y_closed + scale * 0.020,
                    eye_cx + eye_rx * 1.15 * (1 if side_sign < 0 else -1), y_closed - scale * 0.022,
                    fill=shadow_color, width=5, capstyle="round", smooth=True,
                )
                # Wing specular glint
                self._canvas.create_oval(
                    eye_cx + (eye_rx * 0.70 if side_sign < 0 else -eye_rx * 0.70) - 3, y_closed - 3,
                    eye_cx + (eye_rx * 0.70 if side_sign < 0 else -eye_rx * 0.70) + 3, y_closed + 3,
                    fill=highlight_color, outline="",
                )
                continue

            # 1. Curved Sclera (Eyeball white contour) - more natural color
            sclera_pts = [
                eye_cx - eye_rx * 1.05, eye_y,
                eye_cx - eye_rx * 0.50, eye_y - curr_ry * 1.05,
                eye_cx, eye_y - curr_ry * 1.15,
                eye_cx + eye_rx * 0.50, eye_y - curr_ry * 1.05,
                eye_cx + eye_rx * 1.05, eye_y,
                eye_cx + eye_rx * 0.50, eye_y + curr_ry * 1.05,
                eye_cx, eye_y + curr_ry * 1.15,
                eye_cx - eye_rx * 0.50, eye_y + curr_ry * 1.05,
            ]
            # Deep socket shadow
            self._canvas.create_polygon(
                [pt + 2.0 for pt in sclera_pts],
                fill="#030714", outline="", smooth=True,
            )
            # Sclera base (slightly warm white)
            self._canvas.create_polygon(sclera_pts, fill="#e8e0d8", outline="#c0b0a0", width=2, smooth=True)
            # Add subtle blood vessels (tiny red lines)
            for t in range(3):
                vx = eye_cx + (t - 1) * eye_rx * 0.2
                vy = eye_y + curr_ry * 0.5
                self._canvas.create_line(
                    vx - eye_rx * 0.05, vy,
                    vx + eye_rx * 0.05, vy + curr_ry * 0.1,
                    fill="#c0a090", width=0.5,
                )

            # Top eyelid shadow cast over upper sclera
            self._canvas.create_polygon(
                [
                    eye_cx - eye_rx * 0.95, eye_y - curr_ry * 0.20,
                    eye_cx, eye_y - curr_ry * 1.00,
                    eye_cx + eye_rx * 0.95, eye_y - curr_ry * 0.20,
                    eye_cx, eye_y - curr_ry * 0.40,
                ],
                fill="#070f1e", outline="", smooth=True,
            )

            # 2. 8-Tone Radiant 32-Bit Iris (more tones and reflections)
            iris_rx = min(eye_rx * 0.68, curr_ry * 0.94)
            iris_ry = curr_ry * 0.92
            iris_cx = eye_cx + pose.gaze_x * eye_rx * 0.38
            iris_cy = eye_y - pose.gaze_y * curr_ry * 0.32

            # Limbal outer ring (Deep void navy)
            self._canvas.create_oval(
                iris_cx - iris_rx, iris_cy - iris_ry,
                iris_cx + iris_rx, iris_cy + iris_ry,
                fill="#011b2e", outline="",
            )

            # Deep dark upper iris shade
            self._canvas.create_oval(
                iris_cx - iris_rx * 0.92, iris_cy - iris_ry * 0.92,
                iris_cx + iris_rx * 0.92, iris_cy + iris_ry * 0.92,
                fill="#023b61", outline="",
            )

            # Vibrant azure midtone iris crescent
            self._canvas.create_oval(
                iris_cx - iris_rx * 0.82, iris_cy - iris_ry * 0.50,
                iris_cx + iris_rx * 0.82, iris_cy + iris_ry * 0.85,
                fill=shadow_color, outline="",
            )

            # Radiant glowing cyan inner iris arc
            self._canvas.create_oval(
                iris_cx - iris_rx * 0.65, iris_cy + iris_ry * 0.05,
                iris_cx + iris_rx * 0.65, iris_cy + iris_ry * 0.82,
                fill=eye_color, outline="",
            )

            # Pure electric bottom reflection arc
            self._canvas.create_oval(
                iris_cx - iris_rx * 0.45, iris_cy + iris_ry * 0.35,
                iris_cx + iris_rx * 0.45, iris_cy + iris_ry * 0.80,
                fill="#7dd3fc", outline="",
            )

            # Add radial fiber lines (subtle iris texture)
            for angle in range(0, 360, 30):
                import math
                rad = math.radians(angle)
                x1 = iris_cx + math.cos(rad) * iris_rx * 0.4
                y1 = iris_cy + math.sin(rad) * iris_ry * 0.4
                x2 = iris_cx + math.cos(rad) * iris_rx * 0.8
                y2 = iris_cy + math.sin(rad) * iris_ry * 0.8
                self._canvas.create_line(x1, y1, x2, y2, fill="#a0c0e0", width=0.5)

            # 3. Dynamic Responsive Pupil Core
            p_rx = iris_rx * (0.32 + pose.pupil_size * 0.25)
            p_ry = iris_ry * (0.32 + pose.pupil_size * 0.25)
            self._canvas.create_oval(
                iris_cx - p_rx, iris_cy - p_ry,
                iris_cx + p_rx, iris_cy + p_ry,
                fill=pupil_color, outline="",
            )
            # Pupil reflection (tiny)
            self._canvas.create_oval(
                iris_cx - p_rx * 0.3, iris_cy - p_ry * 0.3,
                iris_cx + p_rx * 0.1, iris_cy + p_ry * 0.1,
                fill="#808080", outline="",
            )

            # 4. Triple 32-Bit Specular Catchlights (Lively Glass Shines)
            # Primary large starburst diamond shine (Top-Left)
            sp1_x = iris_cx - iris_rx * 0.32
            sp1_y = iris_cy - iris_ry * 0.32
            sp1_r = max(4.0, iris_rx * 0.28)
            self._canvas.create_polygon(
                [
                    sp1_x, sp1_y - sp1_r,
                    sp1_x + sp1_r * 0.6, sp1_y - sp1_r * 0.6,
                    sp1_x + sp1_r, sp1_y,
                    sp1_x + sp1_r * 0.6, sp1_y + sp1_r * 0.6,
                    sp1_x, sp1_y + sp1_r,
                    sp1_x - sp1_r * 0.6, sp1_y + sp1_r * 0.6,
                    sp1_x - sp1_r, sp1_y,
                    sp1_x - sp1_r * 0.6, sp1_y - sp1_r * 0.6,
                ],
                fill="#ffffff", outline="", smooth=True,
            )
            # Secondary twinkle sparkle shine (Top-Right)
            sp2_x = iris_cx + iris_rx * 0.38
            sp2_y = iris_cy - iris_ry * 0.15
            self._canvas.create_oval(
                sp2_x - 3.5, sp2_y - 3.5,
                sp2_x + 3.5, sp2_y + 3.5,
                fill=highlight_color, outline="",
            )
            # Tertiary soft bottom twinkle (Bottom-Right)
            sp3_x = iris_cx + iris_rx * 0.28
            sp3_y = iris_cy + iris_ry * 0.40
            self._canvas.create_rectangle(
                sp3_x - 2.5, sp3_y - 2.5,
                sp3_x + 2.5, sp3_y + 2.5,
                fill="#ffffff", outline="",
            )
            # Add tiny extra glint near pupil
            sp4_x = iris_cx - iris_rx * 0.05
            sp4_y = iris_cy - iris_ry * 0.05
            self._canvas.create_oval(
                sp4_x - 1.5, sp4_y - 1.5,
                sp4_x + 1.5, sp4_y + 1.5,
                fill="#ffffff", outline="",
            )

            # 5. Upper Eyeliner, Winged Lash & Eyelash Spikes (more detailed)
            outer_sign = 1 if side_sign > 0 else -1
            self._canvas.create_line(
                eye_cx - eye_rx * 1.08, eye_y,
                eye_cx - eye_rx * 0.50, eye_y - curr_ry * 1.05,
                eye_cx, eye_y - curr_ry * 1.18,
                eye_cx + eye_rx * 0.50, eye_y - curr_ry * 1.05,
                eye_cx + eye_rx * 1.12 + (outer_sign * scale * 0.025), eye_y - (scale * 0.015 if outer_sign > 0 else 0),
                fill=shadow_color, width=6, capstyle="round", smooth=True,
            )
            # Upper lash highlight sheen
            self._canvas.create_line(
                eye_cx - eye_rx * 0.80, eye_y - curr_ry * 0.95,
                eye_cx, eye_y - curr_ry * 1.18,
                eye_cx + eye_rx * 0.80, eye_y - curr_ry * 0.95,
                fill=highlight_color, width=2.5, capstyle="round", smooth=True,
            )
            # Lower delicate lash line
            self._canvas.create_line(
                eye_cx - eye_rx * 0.60, eye_y + curr_ry * 1.05,
                eye_cx, eye_y + curr_ry * 1.15,
                eye_cx + eye_rx * 0.60, eye_y + curr_ry * 1.05,
                fill="#1a2e4c", width=2.5, capstyle="round", smooth=True,
            )
            # Add individual eyelash strokes
            for lash_t in range(6):
                lx = eye_cx - eye_rx * 0.8 + lash_t * eye_rx * 0.3
                ly = eye_y - curr_ry * 1.05
                self._canvas.create_line(
                    lx - 1, ly - 2,
                    lx + 1, ly + 3,
                    fill="#020612", width=1.5,
                )
            for lash_t in range(4):
                lx = eye_cx + eye_rx * 0.3 + lash_t * eye_rx * 0.2
                ly = eye_y - curr_ry * 1.1
                self._canvas.create_line(
                    lx - 1, ly - 2,
                    lx + 1, ly + 3,
                    fill="#020612", width=1.5,
                )

        # -------------------------------------------------------------
        # 8. Loose center-parted hair that keeps both eyes unobstructed.
        # -------------------------------------------------------------
        hair_cx = head_cx
        hair_top_y = head_cy - h_ry_top * 0.95

        # Side locks stay outside the iris area and fall naturally toward shoulders.
        left_lock_outer = [
            hair_cx - h_rx * 0.78, hair_top_y + scale * 0.11,
            hair_cx - h_rx * 1.12, head_cy - scale * 0.05,
            hair_cx - h_rx * 1.12, head_cy + scale * 0.27,
            hair_cx - h_rx * 0.88, head_cy + scale * 0.38,
            hair_cx - h_rx * 0.94, head_cy + scale * 0.12,
            hair_cx - h_rx * 0.90, head_cy - scale * 0.08,
        ]
        self._canvas.create_polygon(
            left_lock_outer,
            fill=hair_colors["shadow"],
            outline=hair_colors["highlight"],
            width=2,
            smooth=True,
        )
        left_lock_inner = [
            hair_cx - h_rx * 0.82, hair_top_y + scale * 0.12,
            hair_cx - h_rx * 1.03, head_cy - scale * 0.03,
            hair_cx - h_rx * 1.02, head_cy + scale * 0.24,
            hair_cx - h_rx * 0.91, head_cy + scale * 0.32,
            hair_cx - h_rx * 0.98, head_cy + scale * 0.10,
            hair_cx - h_rx * 0.94, head_cy - scale * 0.06,
        ]
        self._canvas.create_polygon(
            left_lock_inner,
            fill=hair_colors["base"],
            outline="",
            smooth=True,
        )
        self._canvas.create_line(
            hair_cx - h_rx * 0.88, hair_top_y + scale * 0.14,
            hair_cx - h_rx * 1.00, head_cy + scale * 0.03,
            hair_cx - h_rx * 0.95, head_cy + scale * 0.28,
            fill=hair_colors["shine"],
            width=3,
            smooth=True,
        )

        right_lock_outer = [
            hair_cx + h_rx * 0.78, hair_top_y + scale * 0.11,
            hair_cx + h_rx * 1.12, head_cy - scale * 0.05,
            hair_cx + h_rx * 1.12, head_cy + scale * 0.27,
            hair_cx + h_rx * 0.88, head_cy + scale * 0.38,
            hair_cx + h_rx * 0.94, head_cy + scale * 0.12,
            hair_cx + h_rx * 0.90, head_cy - scale * 0.08,
        ]
        self._canvas.create_polygon(
            right_lock_outer,
            fill=hair_colors["shadow"],
            outline=hair_colors["highlight"],
            width=2,
            smooth=True,
        )
        right_lock_inner = [
            hair_cx + h_rx * 0.82, hair_top_y + scale * 0.12,
            hair_cx + h_rx * 1.03, head_cy - scale * 0.03,
            hair_cx + h_rx * 1.02, head_cy + scale * 0.24,
            hair_cx + h_rx * 0.91, head_cy + scale * 0.32,
            hair_cx + h_rx * 0.98, head_cy + scale * 0.10,
            hair_cx + h_rx * 0.94, head_cy - scale * 0.06,
        ]
        self._canvas.create_polygon(
            right_lock_inner,
            fill=hair_colors["base"],
            outline="",
            smooth=True,
        )
        self._canvas.create_line(
            hair_cx + h_rx * 0.88, hair_top_y + scale * 0.14,
            hair_cx + h_rx * 1.00, head_cy + scale * 0.03,
            hair_cx + h_rx * 0.95, head_cy + scale * 0.28,
            fill=hair_colors["shine"],
            width=3,
            smooth=True,
        )

        # Two crown panels create a visible center part instead of a heavy fringe.
        left_crown = [
            hair_cx - h_rx * 0.02, hair_top_y - scale * 0.025,
            hair_cx - h_rx * 0.34, hair_top_y - scale * 0.005,
            hair_cx - h_rx * 0.72, head_cy - scale * 0.18,
            hair_cx - h_rx * 0.62, head_cy - scale * 0.13,
            hair_cx - h_rx * 0.28, head_cy - scale * 0.20,
            hair_cx - h_rx * 0.06, hair_top_y + scale * 0.025,
        ]
        right_crown = [
            hair_cx + h_rx * 0.02, hair_top_y - scale * 0.025,
            hair_cx + h_rx * 0.34, hair_top_y - scale * 0.005,
            hair_cx + h_rx * 0.72, head_cy - scale * 0.18,
            hair_cx + h_rx * 0.62, head_cy - scale * 0.13,
            hair_cx + h_rx * 0.28, head_cy - scale * 0.20,
            hair_cx + h_rx * 0.06, hair_top_y + scale * 0.025,
        ]
        for crown in (left_crown, right_crown):
            self._canvas.create_polygon(
                crown,
                fill=hair_colors["base"],
                outline=hair_colors["highlight"],
                width=2,
                smooth=True,
            )

        self._canvas.create_line(
            hair_cx, hair_top_y - scale * 0.02,
            hair_cx, hair_top_y + scale * 0.105,
            fill=hair_colors["shadow"],
            width=2,
            smooth=True,
        )
        self._canvas.create_line(
            hair_cx - h_rx * 0.07, hair_top_y + scale * 0.005,
            hair_cx - h_rx * 0.38, hair_top_y + scale * 0.035,
            hair_cx - h_rx * 0.62, head_cy - scale * 0.16,
            fill=hair_colors["shine"],
            width=3,
            smooth=True,
        )
        self._canvas.create_line(
            hair_cx + h_rx * 0.07, hair_top_y + scale * 0.005,
            hair_cx + h_rx * 0.38, hair_top_y + scale * 0.035,
            hair_cx + h_rx * 0.62, head_cy - scale * 0.16,
            fill=hair_colors["shine"],
            width=3,
            smooth=True,
        )

        # -------------------------------------------------------------
        # 9. Natural Contoured Lips & Speech Visemes (more realistic)
        # -------------------------------------------------------------
        mouth_cx = cx + p_face_x
        mouth_cy = head_cy + p_face_y * 0.35 + scale * 0.25
        mouth_w = scale * (0.16 + pose.mouth_width * 0.12)
        mouth_h = max(3.0, scale * 0.16 * pose.mouth_open)

        # Expressive smile lift
        smile_dy = (
            -scale * 0.022 if pose.expression in ("happy", "excited", "playful", "wink")
            else (scale * 0.018 if pose.expression in ("error", "sad") else 0.0)
        )

        m_left = mouth_cx - mouth_w / 2
        m_right = mouth_cx + mouth_w / 2

        # Lip colors (natural)
        lip_upper = mouth_color
        lip_lower = "#b85c3a"  # slightly darker
        lip_gloss = "#e8a080"

        if pose.mouth_open > 0.08:
            m_top = mouth_cy - mouth_h / 2
            m_bot = m_top + mouth_h

            # Deep oral cavity interior (with gradient illusion)
            cavity_pts = [
                m_left, m_top + smile_dy,
                mouth_cx - mouth_w * 0.25, m_top - mouth_h * 0.35,
                mouth_cx, m_top - mouth_h * 0.45,
                mouth_cx + mouth_w * 0.25, m_top - mouth_h * 0.35,
                m_right, m_top + smile_dy,
                mouth_cx + mouth_w * 0.25, m_bot + mouth_h * 0.40,
                mouth_cx, m_bot + mouth_h * 0.50,
                mouth_cx - mouth_w * 0.25, m_bot + mouth_h * 0.40,
            ]
            self._canvas.create_polygon(cavity_pts, fill="#03060f", outline="", smooth=True)
            # Inner shadow at top
            self._canvas.create_polygon(
                [
                    m_left, m_top + smile_dy,
                    mouth_cx - mouth_w * 0.25, m_top - mouth_h * 0.35,
                    mouth_cx, m_top - mouth_h * 0.45,
                    mouth_cx + mouth_w * 0.25, m_top - mouth_h * 0.35,
                    m_right, m_top + smile_dy,
                    mouth_cx, m_top - mouth_h * 0.1,
                ],
                fill="#050a14", outline="", smooth=True,
            )

            # Upper dental enamel arch (more teeth detail)
            if mouth_h >= scale * 0.04:
                teeth_color = "#f8fafc"
                # Upper teeth
                self._canvas.create_line(
                    mouth_cx - mouth_w * 0.28, m_top - mouth_h * 0.10,
                    mouth_cx + mouth_w * 0.28, m_top - mouth_h * 0.10,
                    fill=teeth_color, width=4, capstyle="round",
                )
                # Add vertical separations for teeth
                for tooth_x in range(4):
                    tx = mouth_cx - mouth_w * 0.2 + tooth_x * mouth_w * 0.1
                    self._canvas.create_line(
                        tx, m_top - mouth_h * 0.12,
                        tx, m_top - mouth_h * 0.02,
                        fill="#c0c0c0", width=1,
                    )

            # Upper lip contour with Cupid's bow
            self._canvas.create_line(
                m_left, m_top + smile_dy,
                mouth_cx - mouth_w * 0.22, m_top - mouth_h * 0.35,
                mouth_cx, m_top - mouth_h * 0.25,
                mouth_cx + mouth_w * 0.22, m_top - mouth_h * 0.35,
                m_right, m_top + smile_dy,
                fill=lip_upper, width=4, capstyle="round", smooth=True,
            )
            # Upper lip highlight
            self._canvas.create_line(
                m_left + scale * 0.01, m_top + smile_dy - scale * 0.005,
                mouth_cx - mouth_w * 0.15, m_top - mouth_h * 0.25,
                mouth_cx, m_top - mouth_h * 0.18,
                mouth_cx + mouth_w * 0.15, m_top - mouth_h * 0.25,
                m_right - scale * 0.01, m_top + smile_dy - scale * 0.005,
                fill=lip_gloss, width=2, capstyle="round", smooth=True,
            )
            # Lower lip contour
            self._canvas.create_line(
                m_left, m_top + smile_dy,
                mouth_cx - mouth_w * 0.25, m_bot + mouth_h * 0.40,
                mouth_cx, m_bot + mouth_h * 0.50,
                mouth_cx + mouth_w * 0.25, m_bot + mouth_h * 0.40,
                m_right, m_top + smile_dy,
                fill=lip_lower, width=3.5, capstyle="round", smooth=True,
            )
            # Lower lip gloss
            self._canvas.create_oval(
                mouth_cx - mouth_w * 0.15, m_bot + mouth_h * 0.2,
                mouth_cx + mouth_w * 0.15, m_bot + mouth_h * 0.35,
                fill=lip_gloss, outline="", stipple="gray50",
            )
        else:
            # Closed lip with contoured Cupid's bow and lip gloss volume
            lip_y = mouth_cy
            # Upper lip contour with Cupid's bow dip
            self._canvas.create_line(
                m_left, lip_y + smile_dy,
                mouth_cx - mouth_w * 0.22, lip_y + smile_dy - scale * 0.010,
                mouth_cx, lip_y + smile_dy - scale * 0.003,
                mouth_cx + mouth_w * 0.22, lip_y + smile_dy - scale * 0.010,
                m_right, lip_y + smile_dy,
                fill=lip_upper, width=4, capstyle="round", smooth=True,
            )
            # Upper lip highlight
            self._canvas.create_line(
                m_left + scale * 0.01, lip_y + smile_dy - scale * 0.002,
                mouth_cx - mouth_w * 0.15, lip_y + smile_dy - scale * 0.008,
                mouth_cx, lip_y + smile_dy - scale * 0.002,
                mouth_cx + mouth_w * 0.15, lip_y + smile_dy - scale * 0.008,
                m_right - scale * 0.01, lip_y + smile_dy - scale * 0.002,
                fill=lip_gloss, width=2, capstyle="round", smooth=True,
            )
            # Lower lip fullness curve
            self._canvas.create_line(
                m_left + scale * 0.015, lip_y + smile_dy + scale * 0.008,
                mouth_cx, lip_y + smile_dy + scale * 0.016,
                m_right - scale * 0.015, lip_y + smile_dy + scale * 0.008,
                fill=lip_lower, width=3, capstyle="round", smooth=True,
            )
            # Lower lip gloss
            self._canvas.create_oval(
                mouth_cx - scale * 0.02, lip_y + smile_dy + scale * 0.005,
                mouth_cx + scale * 0.02, lip_y + smile_dy + scale * 0.015,
                fill=lip_gloss, outline="", stipple="gray50",
            )
            # Lip center gloss highlight
            self._canvas.create_oval(
                mouth_cx - scale * 0.015, lip_y + smile_dy - scale * 0.006,
                mouth_cx + scale * 0.015, lip_y + smile_dy + scale * 0.002,
                fill=skin_highlight, outline="",
            )

    def _draw_eye(
        self,
        cx: float,
        cy: float,
        rx: float,
        ry: float,
        openness: float,
        gaze_x: float,
        gaze_y: float,
        pupil_size: float,
        eye_color: str,
        pupil_color: str,
    ) -> None:
        """Vector eye fallback renderer (simplified)."""
        curr_ry = max(1.0, ry * openness)

        if openness < 0.1:
            self._canvas.create_line(
                cx - rx, cy,
                cx + rx, cy,
                fill=eye_color,
                width=4,
                capstyle="round",
            )
            return

        self._canvas.create_oval(
            cx - rx, cy - curr_ry,
            cx + rx, cy + curr_ry,
            fill=eye_color, outline="",
        )

        iris_r = min(rx * 0.7, curr_ry * 0.9)
        max_shift_x = rx * 0.4
        max_shift_y = curr_ry * 0.35
        iris_cx = cx + gaze_x * max_shift_x
        iris_cy = cy + gaze_y * max_shift_y

        p_factor = 0.4 + pupil_size * 0.3
        p_r = iris_r * p_factor
        self._canvas.create_oval(
            iris_cx - p_r, iris_cy - p_r,
            iris_cx + p_r, iris_cy + p_r,
            fill=pupil_color, outline="",
        )

        spec_r = iris_r * 0.25
        spec_x = iris_cx - iris_r * 0.3
        spec_y = iris_cy - iris_r * 0.3
        self._canvas.create_oval(
            spec_x - spec_r, spec_y - spec_r,
            spec_x + spec_r, spec_y + spec_r,
            fill="#ffffff", outline="",
        )

    def set_state(self, state: AssistantState) -> None:
        self.animator.set_state(state)

    def set_gaze(self, x: float, y: float) -> None:
        self.animator.set_gaze(x, y)

    def set_speech_level(self, level: float) -> None:
        self.animator.set_speech_level(level)

    def set_expression(self, expression: str, duration_seconds: float = 0.0) -> None:
        logger.info(
            "face_expression stage=requested expression=%s duration_seconds=%.2f style=%s",
            expression,
            duration_seconds,
            self.style,
        )
        self.animator.set_expression(expression, duration_seconds)

    def sleep(self) -> None:
        self.animator.sleep()

    def wake(self) -> None:
        self.animator.wake()

    def get_current_pose(self) -> FacePose:
        """Return the current normalized pose without exposing renderer internals."""
        return self.animator.step()

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

    def capabilities(self) -> list[CapabilityDescriptor]:
        """Expose the legacy capability-provider API used by Core."""
        return [
            CapabilityDescriptor(
                key="face.display",
                description="mostrar un rostro 2D animado de AILEN",
                available=self._running,
                source="face",
            ),
            CapabilityDescriptor(
                key="face.expression",
                description="cambiar la expresión entre gestos permitidos",
                available=self._running,
                source="face",
            ),
        ]

    def mainloop(self) -> None:
        if self._root:
            self._root.mainloop()

    def schedule_close(self, delay_ms: int = 1000) -> None:
        if self._root:
            self._root.after(delay_ms, self.close)

    def close(self) -> None:
        self._running = False
        if self._root:
            try:
                self._root.destroy()
            except (RuntimeError, OSError) as err:
                logger.debug("Error cerrando ventana Tk: %s", err)
            except Exception as err:  # noqa: BLE001
                logger.debug("Error cerrando ventana Tk: %s", err)
            self._root = None
            self._canvas = None

    def describe_capabilities(self) -> list[CapabilityDescriptor]:
        """Human-facing renderer description for diagnostics/admin surfaces."""
        return [
            CapabilityDescriptor(
                key="face_controller",
                description=(
                    "animated raster portrait renderer (Tkinter), using the packaged AILEN "
                    "portrait with gaze, blink, speech frames and subtle parallax."
                ),
                available=self.is_available(),
                source="gui",
            )
        ]
