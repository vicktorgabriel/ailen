"""Tk display adapter for the external native FacePack engine."""

from __future__ import annotations

import logging
import time
from math import gcd
from pathlib import Path
from typing import Any

from ailen.core.capabilities import CapabilityDescriptor
from ailen.domain.enums import AssistantState
from ailen.face.contracts import bounded_expression_ids
from ailen.face.native_engine import (
    NativeFaceEngine,
    NativeFaceEngineError,
    NativeSequenceDescriptor,
)

logger = logging.getLogger("ailen.face.native_controller")


def presentation_size_for_scale(
    source_width: int,
    source_height: int,
    numerator: int,
    denominator: int,
) -> tuple[int, int]:
    """Return the exact Tk ``subsample``-then-``zoom`` output dimensions."""

    safe_numerator = max(1, numerator)
    safe_denominator = max(1, denominator)
    return (
        ((source_width + safe_denominator - 1) // safe_denominator) * safe_numerator,
        ((source_height + safe_denominator - 1) // safe_denominator) * safe_numerator,
    )


def fit_presentation_scale(
    source_width: int,
    source_height: int,
    canvas_width: int,
    canvas_height: int,
    *,
    max_denominator: int = 16,
    max_zoom: int = 16,
) -> tuple[int, int]:
    """Return the largest bounded Tk zoom/subsample ratio that fits the canvas."""

    if min(source_width, source_height, canvas_width, canvas_height) <= 0:
        return 1, 1
    if canvas_width * source_height <= canvas_height * source_width:
        limit_num, limit_den = canvas_width, source_width
    else:
        limit_num, limit_den = canvas_height, source_height
    best_num = 0
    best_den = 1
    for denominator in range(1, max(1, max_denominator) + 1):
        numerator = min(max_zoom, limit_num * denominator // limit_den)
        presented = presentation_size_for_scale(
            source_width,
            source_height,
            numerator,
            denominator,
        )
        if (
            numerator > 0
            and presented[0] <= canvas_width
            and presented[1] <= canvas_height
            and numerator * best_den > best_num * denominator
        ):
            best_num, best_den = numerator, denominator
    if best_num == 0:
        best_num = 1
        best_den = (limit_den + limit_num - 1) // limit_num
    divisor = gcd(best_num, best_den)
    return best_num // divisor, best_den // divisor

STATE_MAP = {
    AssistantState.BOOTING: "waiting",
    AssistantState.IDLE: "idle",
    AssistantState.ATTENTION: "attentive",
    AssistantState.LISTENING: "listening",
    AssistantState.PROCESSING: "processing",
    AssistantState.TOOL: "processing",
    AssistantState.SLEEP: "sleeping",
    AssistantState.ERROR: "waiting",
    AssistantState.DEGRADED: "waiting",
}


class NativeFaceController:
    """FaceController backed by a native engine and an external FacePack.

    ``SPEAKING`` is deliberately not a persistent face state: speech is a mouth
    layer over the current state/emotion and is driven by ``set_speech_level``.
    """

    def __init__(
        self,
        *,
        library_path: str | Path,
        facepack_path: str | Path,
        allowed_facepack_root: str | Path,
        width: int = 800,
        height: int = 480,
        fullscreen: bool = False,
        fps_limit: int = 30,
        engine: NativeFaceEngine | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.fullscreen = fullscreen
        self.fps_limit = fps_limit
        self.engine = engine or NativeFaceEngine(library_path)
        try:
            self.engine.load_pack(facepack_path, allowed_root=allowed_facepack_root)
        except Exception:
            if engine is None:
                self.engine.close()
            raise
        self._root: Any = None
        self._canvas: Any = None
        self._image_item: Any = None
        self._photo: Any = None
        self._presentation_ratio = (1, 1)
        self._presentation_size = (self.engine.width, self.engine.height)
        self._canvas_size = (width, height)
        self._running = False
        self._closed = False
        self._delay_ms = max(10, round(1000 / max(1, fps_limit)))
        self._last_frame_at = time.monotonic()
        self._last_frame_generation = -1
        self._state = AssistantState.IDLE
        self._fatal_error: NativeFaceEngineError | None = None

    @property
    def available_expressions(self) -> tuple[str, ...]:
        """Return the pack-defined bounded emotion list."""
        return bounded_expression_ids(("neutral", *self.engine.expressions))

    @property
    def conversational_expressions(self) -> tuple[str, ...]:
        """Project only pack-declared spontaneous affect ids."""

        return bounded_expression_ids(self.engine.conversational_expressions)

    @property
    def diagnostic_sequence_catalog(self) -> tuple[NativeSequenceDescriptor, ...]:
        """Expose pack metadata only to offline QA tooling."""

        return self.engine.sequence_catalog

    @property
    def diagnostic_states(self) -> tuple[str, ...]:
        return self.engine.states

    def trigger_diagnostic_microaction(self, microaction: str) -> None:
        self.engine.trigger_microaction(microaction)

    def set_diagnostic_speech_sequence(self, sequence: str | None) -> None:
        self.engine.set_viseme(sequence)

    def is_display_active(self) -> bool:
        return self._running and self._root is not None

    def start_window(self, interactive_keys: bool = False) -> None:
        """Create the product window; no expression keyboard POC is installed."""

        del interactive_keys
        import tkinter as tk

        if self._closed:
            raise NativeFaceEngineError("native face controller is already closed")
        self._root = tk.Tk()
        self._root.title("AILEN — Native FacePack")
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
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._running = True
        self._last_frame_at = time.monotonic()
        self._schedule_next_frame()
        logger.info(
            "native_face stage=window_ready pack=%s version=%s size=%sx%s expressions=%d",
            self.engine.pack_id,
            self.engine.pack_version,
            self.engine.width,
            self.engine.height,
            len(self.engine.expressions),
        )

    def _on_canvas_configure(self, event: Any) -> None:
        size = (max(1, int(event.width)), max(1, int(event.height)))
        if size != self._canvas_size:
            self._canvas_size = size
            self._last_frame_generation = -1

    @property
    def presentation_ratio(self) -> tuple[int, int]:
        return self._presentation_ratio

    @property
    def presentation_size(self) -> tuple[int, int]:
        return self._presentation_size

    def _schedule_next_frame(self) -> None:
        if not self._running or self._root is None:
            return
        self._render_frame()
        self._root.after(self._delay_ms, self._schedule_next_frame)

    def _render_frame(self) -> None:
        if self._canvas is None:
            return
        now = time.monotonic()
        delta_ms = max(0, min(1000, round((now - self._last_frame_at) * 1000.0)))
        self._last_frame_at = now
        try:
            self.engine.update(delta_ms)
            generation = self.engine.frame_generation
            if generation == self._last_frame_generation:
                return
        except NativeFaceEngineError as exc:
            logger.error("native_face stage=render_failed error=%s", exc)
            self._fatal_error = exc
            self.close()
            return
        canvas_width = int(self._canvas.winfo_width() or self.width)
        canvas_height = int(self._canvas.winfo_height() or self.height)
        ratio = fit_presentation_scale(
            self.engine.width,
            self.engine.height,
            canvas_width,
            canvas_height,
        )
        numerator, denominator = ratio
        presented_width, presented_height = presentation_size_for_scale(
            self.engine.width,
            self.engine.height,
            numerator,
            denominator,
        )
        try:
            rgb = self.engine.frame_rgb_scaled(presented_width, presented_height)
        except NativeFaceEngineError as exc:
            logger.error("native_face stage=presentation_scale_failed error=%s", exc)
            self._fatal_error = exc
            self.close()
            return
        header = f"P6\n{presented_width} {presented_height}\n255\n".encode("ascii")
        import tkinter as tk

        ppm = header + rgb
        if self._photo is None:
            self._photo = tk.PhotoImage(data=ppm, format="PPM")
        else:
            self._photo.configure(data=ppm, format="PPM")
        self._last_frame_generation = generation
        presented = self._photo
        self._presentation_ratio = ratio
        self._presentation_size = (presented_width, presented_height)
        if self._image_item is None:
            self._image_item = self._canvas.create_image(
                canvas_width // 2,
                canvas_height // 2,
                anchor="center",
                image=presented,
            )
        else:
            self._canvas.coords(self._image_item, canvas_width // 2, canvas_height // 2)
            self._canvas.itemconfigure(self._image_item, image=presented)

    def set_state(self, state: AssistantState) -> None:
        self._state = state
        if state == AssistantState.SPEAKING:
            return
        self.engine.set_state(STATE_MAP[state])

    def set_gaze(self, x: float, y: float) -> None:
        self.engine.set_gaze(x, y)

    def set_speech_level(self, level: float) -> None:
        self.engine.set_speech_level(level)

    def set_expression(self, expression: str, duration_seconds: float = 0.0) -> None:
        clean = expression.strip().lower()
        if clean == "neutral":
            self.engine.clear_expression()
            return
        self.engine.trigger_expression(clean, duration_seconds)
        logger.info(
            "face_expression stage=requested expression=%s duration_seconds=%.2f style=facepack",
            clean,
            duration_seconds,
        )

    def sleep(self) -> None:
        self.set_state(AssistantState.SLEEP)

    def wake(self) -> None:
        self.set_state(AssistantState.IDLE)

    def update(self) -> None:
        """Pump Tk and surface fatal native errors to the failover wrapper."""

        if self._fatal_error is not None:
            raise self._fatal_error
        if self._root is None or not self._running:
            return
        try:
            self._root.update_idletasks()
            self._root.update()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Native face Tk update stopped: %s", exc)
            self.close()
            return
        if self._fatal_error is not None:
            raise self._fatal_error

    def capabilities(self) -> list[CapabilityDescriptor]:
        return [
            CapabilityDescriptor(
                key="face.display",
                description="mostrar un rostro nativo animado desde FacePack",
                available=self.is_display_active(),
                source="face",
            ),
            CapabilityDescriptor(
                key="face.expression",
                description="cambiar entre emociones declaradas por el FacePack",
                available=self.is_display_active(),
                source="face",
            ),
        ]

    def describe_capabilities(self) -> list[CapabilityDescriptor]:
        return [
            CapabilityDescriptor(
                key="face_controller",
                description=(
                    "native C++ FacePack renderer with non-periodic state scheduling, "
                    "curated emotions, and an independent speech mouth layer"
                ),
                available=not self._closed,
                source="native_face_engine",
            )
        ]

    def close(self) -> None:
        if self._closed:
            return
        self._running = False
        if self._root is not None:
            try:
                self._root.destroy()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error closing native face window: %s", exc)
        self._root = None
        self._canvas = None
        self._image_item = None
        self._photo = None
        self._presented_photo = None
        self.engine.close()
        self._closed = True
