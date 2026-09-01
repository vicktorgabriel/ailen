"""Lightweight ctypes binding for the optional native AILEN face engine.

The native process receives only normalized graphical commands and a FacePack
path.  It has no access to Core memory, AI providers, tools, or permissions.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from dataclasses import dataclass
from enum import IntEnum, IntFlag
from pathlib import Path
from typing import Final, Self

ABI_MAJOR: Final[int] = 1
ABI_MINOR: Final[int] = 4
PIXEL_FORMAT_RGB24: Final[int] = 1
logger = logging.getLogger("ailen.face.native_engine")


class NativeFaceResult(IntEnum):
    OK = 0
    INVALID_ARGUMENT = 1
    IO_ERROR = 2
    INVALID_PACK = 3
    INCOMPATIBLE = 4
    NOT_FOUND = 5
    BUSY = 6
    DECODE_ERROR = 7
    NOT_READY = 8
    INTERNAL_ERROR = 9


class NativeSequenceCategory(IntEnum):
    STATE = 1
    MICROACTION = 2
    EMOTION = 3
    INTENSE_EMOTION = 4
    SPEECH = 5


class NativeSequenceLayer(IntEnum):
    FULL_FRAME = 1
    MOUTH_ROI = 2
    UPPER_FACE_ROI = 3


class NativeSequencePolicy(IntFlag):
    CONVERSATIONAL = 1 << 5
    EXPLICIT_ONLY = 1 << 6
    STATE_CONTROLLED = 1 << 7


@dataclass(frozen=True)
class NativeSequenceDescriptor:
    """Read-only metadata declared by the active FacePack."""

    id: str
    category: NativeSequenceCategory
    layer: NativeSequenceLayer
    flags: int
    duration_ms: int

    @property
    def affect_policy(self) -> NativeSequencePolicy:
        return NativeSequencePolicy(
            self.flags
            & int(
                NativeSequencePolicy.CONVERSATIONAL
                | NativeSequencePolicy.EXPLICIT_ONLY
                | NativeSequencePolicy.STATE_CONTROLLED
            )
        )


class NativeFaceEngineError(RuntimeError):
    """Native engine or FacePack operation failed cleanly."""

    def __init__(self, message: str, result: int | None = None) -> None:
        super().__init__(message)
        self.result = result


def native_library_filename() -> str:
    """Return the platform-native engine filename without probing the filesystem."""

    if sys.platform == "win32":
        return "ailen_face_engine.dll"
    if sys.platform == "darwin":
        return "libailen_face_engine.dylib"
    return "libailen_face_engine.so"


def resolve_facepack_path(path: str | Path, *, allowed_root: str | Path) -> Path:
    """Resolve one pack under an explicit trusted root, rejecting traversal/symlinks."""

    raw = Path(path).expanduser()
    root = Path(allowed_root).expanduser().resolve(strict=True)
    candidate = raw.resolve(strict=True)
    if candidate.suffix.lower() != ".facepack":
        raise NativeFaceEngineError("FacePack path must end in .facepack")
    if candidate != root and root not in candidate.parents:
        raise NativeFaceEngineError("FacePack path escapes its configured trusted root")
    if not candidate.is_file():
        raise NativeFaceEngineError(f"FacePack path is not a regular file: {candidate}")
    return candidate


class NativeFaceEngine:
    """Owned native engine handle with checked ABI and copy-safe RGB frames."""

    def __init__(self, library_path: str | Path) -> None:
        path = Path(library_path).expanduser().resolve(strict=True)
        expected_suffixes = {".so", ".dll", ".dylib"}
        if path.suffix.lower() not in expected_suffixes or not path.is_file():
            raise NativeFaceEngineError(f"invalid native face engine library: {path}")
        try:
            self._library = ctypes.CDLL(os.fspath(path))
        except OSError as exc:
            raise NativeFaceEngineError(f"could not load native face engine: {exc}") from exc
        self._library.ailen_face_get_abi_version.restype = ctypes.c_uint32
        abi = int(self._library.ailen_face_get_abi_version())
        abi_major = abi >> 16
        abi_minor = abi & 0xFFFF
        if abi_major != ABI_MAJOR or abi_minor < ABI_MINOR:
            raise NativeFaceEngineError(
                f"native face ABI {abi_major}.{abi_minor} is incompatible with "
                f"Python ABI {ABI_MAJOR}.{ABI_MINOR}",
                NativeFaceResult.INCOMPATIBLE,
            )
        self._configure_abi()
        handle = self._library.ailen_face_create()
        if not handle:
            raise NativeFaceEngineError("native face engine could not allocate a handle")
        self._handle: int | None = int(handle)
        self._frame_buffer: ctypes.Array[ctypes.c_ubyte] | None = None
        self._frame_size = 0
        self._scaled_frame_buffer: ctypes.Array[ctypes.c_ubyte] | None = None
        self._scaled_frame_shape = (0, 0)
        self._copy_lock = threading.Lock()

    def _configure_abi(self) -> None:
        lib = self._library
        handle = ctypes.c_void_p
        lib.ailen_face_get_abi_version.restype = ctypes.c_uint32
        lib.ailen_face_create.restype = handle
        lib.ailen_face_destroy.argtypes = [handle]
        lib.ailen_face_load_pack.argtypes = [handle, ctypes.c_char_p]
        lib.ailen_face_load_pack.restype = ctypes.c_int
        lib.ailen_face_unload_pack.argtypes = [handle]
        lib.ailen_face_get_pack_id.argtypes = [handle]
        lib.ailen_face_get_pack_id.restype = ctypes.c_char_p
        lib.ailen_face_get_pack_version.argtypes = [handle]
        lib.ailen_face_get_pack_version.restype = ctypes.c_char_p
        lib.ailen_face_get_expression_count.argtypes = [handle]
        lib.ailen_face_get_expression_count.restype = ctypes.c_size_t
        lib.ailen_face_get_expression.argtypes = [handle, ctypes.c_size_t]
        lib.ailen_face_get_expression.restype = ctypes.c_char_p
        lib.ailen_face_has_expression.argtypes = [handle, ctypes.c_char_p]
        lib.ailen_face_has_expression.restype = ctypes.c_int
        lib.ailen_face_get_sequence_count.argtypes = [handle]
        lib.ailen_face_get_sequence_count.restype = ctypes.c_size_t
        lib.ailen_face_get_sequence.argtypes = [handle, ctypes.c_size_t]
        lib.ailen_face_get_sequence.restype = ctypes.c_char_p
        lib.ailen_face_get_sequence_category.argtypes = [handle, ctypes.c_size_t]
        lib.ailen_face_get_sequence_category.restype = ctypes.c_uint32
        lib.ailen_face_get_sequence_layer.argtypes = [handle, ctypes.c_size_t]
        lib.ailen_face_get_sequence_layer.restype = ctypes.c_uint32
        lib.ailen_face_get_sequence_flags.argtypes = [handle, ctypes.c_size_t]
        lib.ailen_face_get_sequence_flags.restype = ctypes.c_uint32
        lib.ailen_face_get_sequence_duration_ms.argtypes = [handle, ctypes.c_size_t]
        lib.ailen_face_get_sequence_duration_ms.restype = ctypes.c_uint32
        lib.ailen_face_get_state_count.argtypes = [handle]
        lib.ailen_face_get_state_count.restype = ctypes.c_size_t
        lib.ailen_face_get_state.argtypes = [handle, ctypes.c_size_t]
        lib.ailen_face_get_state.restype = ctypes.c_char_p
        lib.ailen_face_set_state.argtypes = [handle, ctypes.c_char_p]
        lib.ailen_face_set_state.restype = ctypes.c_int
        lib.ailen_face_trigger_expression.argtypes = [
            handle,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        lib.ailen_face_trigger_expression.restype = ctypes.c_int
        lib.ailen_face_clear_expression.argtypes = [handle]
        lib.ailen_face_clear_expression.restype = ctypes.c_int
        lib.ailen_face_trigger_microaction.argtypes = [handle, ctypes.c_char_p]
        lib.ailen_face_trigger_microaction.restype = ctypes.c_int
        lib.ailen_face_set_intensity.argtypes = [handle, ctypes.c_float]
        lib.ailen_face_set_intensity.restype = ctypes.c_int
        lib.ailen_face_set_speech_level.argtypes = [handle, ctypes.c_float]
        lib.ailen_face_set_speech_level.restype = ctypes.c_int
        lib.ailen_face_set_viseme.argtypes = [handle, ctypes.c_char_p]
        lib.ailen_face_set_viseme.restype = ctypes.c_int
        lib.ailen_face_set_gaze.argtypes = [handle, ctypes.c_float, ctypes.c_float]
        lib.ailen_face_set_gaze.restype = ctypes.c_int
        lib.ailen_face_set_random_seed.argtypes = [handle, ctypes.c_uint64]
        lib.ailen_face_set_random_seed.restype = ctypes.c_int
        lib.ailen_face_update.argtypes = [handle, ctypes.c_uint32]
        lib.ailen_face_update.restype = ctypes.c_int
        lib.ailen_face_get_frame_size.argtypes = [handle]
        lib.ailen_face_get_frame_size.restype = ctypes.c_size_t
        lib.ailen_face_copy_frame.argtypes = [
            handle,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_size_t,
        ]
        lib.ailen_face_copy_frame.restype = ctypes.c_int
        lib.ailen_face_copy_frame_scaled.argtypes = [
            handle,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_size_t,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_size_t,
        ]
        lib.ailen_face_copy_frame_scaled.restype = ctypes.c_int
        lib.ailen_face_get_width.argtypes = [handle]
        lib.ailen_face_get_width.restype = ctypes.c_uint32
        lib.ailen_face_get_height.argtypes = [handle]
        lib.ailen_face_get_height.restype = ctypes.c_uint32
        lib.ailen_face_get_stride.argtypes = [handle]
        lib.ailen_face_get_stride.restype = ctypes.c_uint32
        lib.ailen_face_get_pixel_format.argtypes = [handle]
        lib.ailen_face_get_pixel_format.restype = ctypes.c_uint32
        lib.ailen_face_get_frame_generation.argtypes = [handle]
        lib.ailen_face_get_frame_generation.restype = ctypes.c_uint64
        lib.ailen_face_get_current_sequence.argtypes = [handle]
        lib.ailen_face_get_current_sequence.restype = ctypes.c_char_p
        lib.ailen_face_get_last_error.argtypes = [handle]
        lib.ailen_face_get_last_error.restype = ctypes.c_char_p

    @property
    def _native_handle(self) -> ctypes.c_void_p:
        if self._handle is None:
            raise NativeFaceEngineError("native face engine handle is closed")
        return ctypes.c_void_p(self._handle)

    def _decode(self, value: bytes | None) -> str:
        return value.decode("utf-8", errors="replace") if value else ""

    def _error_text(self) -> str:
        return self._decode(self._library.ailen_face_get_last_error(self._native_handle))

    def _check(self, result: int, operation: str) -> None:
        if result == NativeFaceResult.OK:
            return
        detail = self._error_text() or f"native result {result}"
        raise NativeFaceEngineError(f"{operation} failed: {detail}", result)

    def load_pack(self, path: str | Path, *, allowed_root: str | Path) -> None:
        pack = resolve_facepack_path(path, allowed_root=allowed_root)
        result = self._library.ailen_face_load_pack(
            self._native_handle,
            os.fsencode(pack),
        )
        self._check(result, "FacePack load")
        self._frame_size = int(self._library.ailen_face_get_frame_size(self._native_handle))
        if self._frame_size <= 0:
            raise NativeFaceEngineError("FacePack loaded without an RGB frame")
        self._frame_buffer = (ctypes.c_ubyte * self._frame_size)()
        self._scaled_frame_buffer = None
        self._scaled_frame_shape = (0, 0)

    def unload_pack(self) -> None:
        self._library.ailen_face_unload_pack(self._native_handle)
        self._frame_buffer = None
        self._frame_size = 0
        self._scaled_frame_buffer = None
        self._scaled_frame_shape = (0, 0)

    @property
    def pack_id(self) -> str:
        return self._decode(self._library.ailen_face_get_pack_id(self._native_handle))

    @property
    def pack_version(self) -> str:
        return self._decode(self._library.ailen_face_get_pack_version(self._native_handle))

    @property
    def width(self) -> int:
        return int(self._library.ailen_face_get_width(self._native_handle))

    @property
    def height(self) -> int:
        return int(self._library.ailen_face_get_height(self._native_handle))

    @property
    def stride(self) -> int:
        return int(self._library.ailen_face_get_stride(self._native_handle))

    @property
    def pixel_format(self) -> int:
        return int(self._library.ailen_face_get_pixel_format(self._native_handle))

    @property
    def frame_generation(self) -> int:
        """Monotonic counter that changes only when visible RGB output changes."""
        return int(self._library.ailen_face_get_frame_generation(self._native_handle))

    @property
    def expressions(self) -> tuple[str, ...]:
        count = int(self._library.ailen_face_get_expression_count(self._native_handle))
        return tuple(
            self._decode(self._library.ailen_face_get_expression(self._native_handle, index))
            for index in range(count)
        )

    @property
    def sequence_catalog(self) -> tuple[NativeSequenceDescriptor, ...]:
        count = int(self._library.ailen_face_get_sequence_count(self._native_handle))
        return tuple(
            NativeSequenceDescriptor(
                id=self._decode(
                    self._library.ailen_face_get_sequence(self._native_handle, index)
                ),
                category=NativeSequenceCategory(
                    self._library.ailen_face_get_sequence_category(
                        self._native_handle, index
                    )
                ),
                layer=NativeSequenceLayer(
                    self._library.ailen_face_get_sequence_layer(self._native_handle, index)
                ),
                flags=int(
                    self._library.ailen_face_get_sequence_flags(self._native_handle, index)
                ),
                duration_ms=int(
                    self._library.ailen_face_get_sequence_duration_ms(
                        self._native_handle, index
                    )
                ),
            )
            for index in range(count)
        )

    @property
    def states(self) -> tuple[str, ...]:
        count = int(self._library.ailen_face_get_state_count(self._native_handle))
        return tuple(
            self._decode(self._library.ailen_face_get_state(self._native_handle, index))
            for index in range(count)
        )

    @property
    def conversational_expressions(self) -> tuple[str, ...]:
        return tuple(
            sequence.id
            for sequence in self.sequence_catalog
            if sequence.category
            in {NativeSequenceCategory.EMOTION, NativeSequenceCategory.INTENSE_EMOTION}
            and sequence.affect_policy == NativeSequencePolicy.CONVERSATIONAL
        )

    @property
    def current_sequence(self) -> str:
        return self._decode(self._library.ailen_face_get_current_sequence(self._native_handle))

    def has_expression(self, expression: str) -> bool:
        return bool(
            self._library.ailen_face_has_expression(
                self._native_handle,
                expression.strip().lower().encode("utf-8"),
            )
        )

    def set_state(self, state: str) -> None:
        result = self._library.ailen_face_set_state(
            self._native_handle,
            state.strip().lower().encode("utf-8"),
        )
        self._check(result, "set state")

    def trigger_expression(self, expression: str, minimum_duration_seconds: float = 0.0) -> None:
        duration_ms = round(max(0.0, min(10.0, minimum_duration_seconds)) * 1000.0)
        result = self._library.ailen_face_trigger_expression(
            self._native_handle,
            expression.strip().lower().encode("utf-8"),
            duration_ms,
        )
        self._check(result, "trigger expression")

    def clear_expression(self) -> None:
        self._check(
            self._library.ailen_face_clear_expression(self._native_handle),
            "clear expression",
        )

    def trigger_microaction(self, microaction: str) -> None:
        result = self._library.ailen_face_trigger_microaction(
            self._native_handle,
            microaction.strip().lower().encode("utf-8"),
        )
        self._check(result, "trigger microaction")

    def set_intensity(self, intensity: float) -> None:
        result = self._library.ailen_face_set_intensity(
            self._native_handle,
            ctypes.c_float(intensity),
        )
        self._check(result, "set intensity")

    def set_speech_level(self, level: float) -> None:
        result = self._library.ailen_face_set_speech_level(
            self._native_handle,
            ctypes.c_float(level),
        )
        self._check(result, "set speech level")

    def set_viseme(self, viseme: str | None) -> None:
        encoded = viseme.strip().lower().encode("utf-8") if viseme else None
        result = self._library.ailen_face_set_viseme(self._native_handle, encoded)
        self._check(result, "set viseme")

    def set_gaze(self, x: float, y: float) -> None:
        result = self._library.ailen_face_set_gaze(
            self._native_handle,
            ctypes.c_float(x),
            ctypes.c_float(y),
        )
        self._check(result, "set gaze")

    def set_random_seed(self, seed: int) -> None:
        result = self._library.ailen_face_set_random_seed(
            self._native_handle,
            ctypes.c_uint64(seed),
        )
        self._check(result, "set random seed")

    def update(self, delta_ms: int) -> None:
        bounded = max(0, min(int(delta_ms), 60_000))
        self._check(
            self._library.ailen_face_update(self._native_handle, bounded),
            "face update",
        )

    def frame_rgb(self) -> bytes:
        with self._copy_lock:
            if self._frame_buffer is None or self._frame_size <= 0:
                raise NativeFaceEngineError("no FacePack frame is available")
            result = self._library.ailen_face_copy_frame(
                self._native_handle,
                self._frame_buffer,
                self._frame_size,
            )
            self._check(result, "copy frame")
            return bytes(self._frame_buffer)

    def frame_rgb_scaled(self, width: int, height: int) -> bytes:
        """Copy one native bilinear RGB24 presentation frame."""

        if not 1 <= width <= 4096 or not 1 <= height <= 4096:
            raise NativeFaceEngineError("scaled frame dimensions are outside 1..4096")
        if width == self.width and height == self.height:
            return self.frame_rgb()
        frame_size = width * height * 3
        with self._copy_lock:
            if (
                self._scaled_frame_buffer is None
                or self._scaled_frame_shape != (width, height)
            ):
                self._scaled_frame_buffer = (ctypes.c_ubyte * frame_size)()
                self._scaled_frame_shape = (width, height)
            result = self._library.ailen_face_copy_frame_scaled(
                self._native_handle,
                self._scaled_frame_buffer,
                frame_size,
                width,
                height,
                width * 3,
            )
            self._check(result, "copy scaled frame")
            return bytes(self._scaled_frame_buffer)

    def close(self) -> None:
        """Destroy the handle after callers have quiesced every worker using it."""
        if self._handle is None:
            return
        handle = ctypes.c_void_p(self._handle)
        self._handle = None
        self._frame_buffer = None
        self._frame_size = 0
        self._scaled_frame_buffer = None
        self._scaled_frame_shape = (0, 0)
        self._library.ailen_face_destroy(handle)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Native face handle finalization failed: %s", exc)
