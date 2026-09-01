"""Versioned binary FacePack writer and structural validator.

This module is build tooling, not part of the runtime renderer.  It deliberately
uses only the Python standard library so tests can build small synthetic packs
without FFmpeg, OpenCV, or the native engine.
"""

from __future__ import annotations

import binascii
import math
import struct
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from itertools import pairwise
from pathlib import Path
from typing import Final

MAGIC: Final[bytes] = b"AILENFP\0"
FORMAT_MAJOR: Final[int] = 1
FORMAT_MINOR: Final[int] = 6
REQUIRED_ABI_MAJOR: Final[int] = 1
PIXEL_FORMAT_RGB24: Final[int] = 1

MAX_PACK_BYTES: Final[int] = 512 * 1024 * 1024
MAX_DIMENSION: Final[int] = 4096
MAX_SEQUENCES: Final[int] = 4096
MAX_FRAMES: Final[int] = 200_000
MAX_STATES: Final[int] = 256
MAX_STATE_ACTIONS: Final[int] = 8192
MAX_WEIGHT: Final[float] = 1000.0

# FacePack 1.4 uses the previously reserved per-frame flags word to carry a
# small similarity transform for composable ROI layers. Full-frame animation
# keeps its authored head/body motion; mouth/eye layers follow that motion at
# runtime without requiring landmarks or OpenCV in the product process.
FACE_TRANSFORM_MARKER: Final[int] = 1 << 31
FACE_TRANSFORM_RESERVED: Final[int] = 1 << 30

HEADER_STRUCT: Final[struct.Struct] = struct.Struct("<8sHHHH8I13Q2I4I")
SEQUENCE_STRUCT: Final[struct.Struct] = struct.Struct("<4I3Ii2f18I")
FRAME_STRUCT: Final[struct.Struct] = struct.Struct("<6IQ4I")
STATE_STRUCT: Final[struct.Struct] = struct.Struct("<12I")
STATE_ACTION_STRUCT: Final[struct.Struct] = struct.Struct("<4I")

assert HEADER_STRUCT.size == 176
assert SEQUENCE_STRUCT.size == 112
assert FRAME_STRUCT.size == 48
assert STATE_STRUCT.size == 48
assert STATE_ACTION_STRUCT.size == 16


class FacePackError(ValueError):
    """Raised when an artifact violates the FacePack v1 contract."""


class SequenceCategory(IntEnum):
    """Semantic role of a sequence; speech is intentionally not an emotion."""

    STATE = 1
    MICROACTION = 2
    EMOTION = 3
    INTENSE_EMOTION = 4
    SPEECH = 5


class SequenceLayer(IntEnum):
    """Compositing layer used by a sequence."""

    FULL_FRAME = 1
    MOUTH_ROI = 2
    UPPER_FACE_ROI = 3


class SequenceFlags(IntFlag):
    """Stable sequence behavior flags persisted in the pack."""

    LOOPABLE = 1 << 0
    INTERRUPTIBLE = 1 << 1
    SPEECH_COMPATIBLE = 1 << 2
    GAZE_COMPATIBLE = 1 << 3
    RETURNS_TO_BASE = 1 << 4
    CONVERSATIONAL = 1 << 5
    EXPLICIT_ONLY = 1 << 6
    STATE_CONTROLLED = 1 << 7
    GAZE_LEFT = 1 << 8
    GAZE_RIGHT = 1 << 9
    GAZE_UP = 1 << 10
    GAZE_DOWN = 1 << 11
    DELTA_BLEND = 1 << 12


EXPRESSION_POLICY_FLAGS: Final[SequenceFlags] = (
    SequenceFlags.CONVERSATIONAL
    | SequenceFlags.EXPLICIT_ONLY
    | SequenceFlags.STATE_CONTROLLED
)


class SpeechStyle(IntEnum):
    """Pack-declared mouth style; this is not phonemic viseme metadata."""

    AUTOMATIC = 0
    SOFT = 1
    NORMAL = 2
    EXPRESSIVE = 3
    HAPPY = 4
    SERIOUS = 5


class FrameEncoding(IntEnum):
    """Payload encodings supported by FacePack v1."""

    JPEG_RGB = 1


@dataclass(frozen=True)
class EncodedFrame:
    """One already-compressed frame supplied to the pack writer."""

    jpeg: bytes
    width: int
    height: int
    timestamp_ms: int
    flags: int = 0


def _pack_signed(value: int, bits: int) -> int:
    minimum = -(1 << (bits - 1))
    maximum = (1 << (bits - 1)) - 1
    if not minimum <= value <= maximum:
        raise FacePackError(
            f"face transform component {value} is outside signed {bits}-bit range"
        )
    return value & ((1 << bits) - 1)


def _unpack_signed(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return value - (1 << bits) if value & sign else value


def encode_face_transform(
    translate_x: float,
    translate_y: float,
    angle_degrees: float,
    scale: float,
) -> int:
    """Encode a bounded canonical-to-base similarity transform.

    Translation has one-pixel precision, angle half-degree precision, and
    scale 1/128 precision. These ranges cover the audited H3 corpus while
    keeping the v1 frame record fixed at 48 bytes.
    """

    values = (translate_x, translate_y, angle_degrees, scale)
    if not all(math.isfinite(value) for value in values) or scale <= 0.0:
        raise FacePackError("face transform contains a non-finite/invalid value")
    dx = round(translate_x)
    dy = round(translate_y)
    angle = round(angle_degrees * 2.0)
    scale_delta = round((scale - 1.0) * 128.0)
    return (
        FACE_TRANSFORM_MARKER
        | _pack_signed(dx, 8)
        | (_pack_signed(dy, 8) << 8)
        | (_pack_signed(angle, 7) << 16)
        | (_pack_signed(scale_delta, 7) << 23)
    )


def decode_face_transform(flags: int) -> tuple[float, float, float, float] | None:
    """Decode FacePack 1.4 frame placement metadata, or ``None`` if absent."""

    if flags == 0:
        return None
    if flags & FACE_TRANSFORM_MARKER == 0 or flags & FACE_TRANSFORM_RESERVED:
        raise FacePackError("frame has invalid face transform flags")
    dx = _unpack_signed(flags & 0xFF, 8)
    dy = _unpack_signed((flags >> 8) & 0xFF, 8)
    angle = _unpack_signed((flags >> 16) & 0x7F, 7) / 2.0
    scale = 1.0 + _unpack_signed((flags >> 23) & 0x7F, 7) / 128.0
    if scale <= 0.0:
        raise FacePackError("frame face transform has an invalid scale")
    return float(dx), float(dy), angle, scale


@dataclass(frozen=True)
class SequenceSpec:
    """A named animation sequence and its curated encoded frames."""

    id: str
    category: SequenceCategory
    layer: SequenceLayer
    frames: tuple[EncodedFrame, ...]
    fps_num: int
    fps_den: int = 1
    flags: SequenceFlags = SequenceFlags.INTERRUPTIBLE
    priority: int = 0
    intensity: float = 0.5
    random_weight: float = 1.0
    return_state: str = "idle"
    entry_anchor: int = 0
    onset_anchor: int = 0
    peak_anchor: int = 0
    hold_start_anchor: int = 0
    hold_end_anchor: int = 0
    exit_anchor: int = 0
    roi: tuple[int, int, int, int] = (0, 0, 0, 0)
    transition_in_ms: int = 0
    transition_out_ms: int = 0
    cooldown_ms: int = 0
    speech_style: SpeechStyle = SpeechStyle.AUTOMATIC


@dataclass(frozen=True)
class StateActionSpec:
    """Weighted microaction available while a persistent state is active."""

    sequence_id: str
    weight: float = 1.0
    cooldown_ms: int = 0
    flags: int = 0


@dataclass(frozen=True)
class StateSpec:
    """Persistent state built from a base frame plus non-periodic actions."""

    id: str
    base_sequence_id: str
    actions: tuple[StateActionSpec, ...] = field(default_factory=tuple)
    wait_min_ms: int = 2500
    wait_max_ms: int = 6000
    flags: int = 0


@dataclass(frozen=True)
class FacePackSpec:
    """Complete logical input to the FacePack writer."""

    pack_id: str
    pack_version: str
    width: int
    height: int
    sequences: tuple[SequenceSpec, ...]
    states: tuple[StateSpec, ...]
    flags: int = 0


@dataclass(frozen=True)
class FacePackSummary:
    """Validated structural summary returned by :func:`inspect_facepack`."""

    pack_id: str
    pack_version: str
    width: int
    height: int
    sequence_count: int
    frame_count: int
    state_count: int
    state_action_count: int
    payload_bytes: int
    file_bytes: int


class _StringTable:
    def __init__(self) -> None:
        self._data = bytearray()
        self._offsets: dict[str, tuple[int, int]] = {}

    def add(self, value: str) -> tuple[int, int]:
        clean = value.strip()
        if not clean or "\x00" in clean:
            raise FacePackError("FacePack identifiers must be non-empty UTF-8 strings")
        encoded = clean.encode("utf-8")
        if len(encoded) > 255:
            raise FacePackError(f"FacePack identifier is too long: {clean[:40]!r}")
        existing = self._offsets.get(clean)
        if existing is not None:
            return existing
        result = (len(self._data), len(encoded))
        self._data.extend(encoded)
        self._offsets[clean] = result
        return result

    def bytes(self) -> bytes:
        return bytes(self._data)


def _align(value: int, alignment: int = 8) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def _validate_spec(spec: FacePackSpec) -> None:
    if not (1 <= spec.width <= MAX_DIMENSION and 1 <= spec.height <= MAX_DIMENSION):
        raise FacePackError("FacePack dimensions are outside the supported range")
    if not spec.sequences or len(spec.sequences) > MAX_SEQUENCES:
        raise FacePackError("FacePack must contain 1..4096 sequences")
    if not spec.states or len(spec.states) > MAX_STATES:
        raise FacePackError("FacePack must contain 1..256 states")

    ids = [sequence.id for sequence in spec.sequences]
    if len(ids) != len(set(ids)):
        raise FacePackError("FacePack sequence identifiers must be unique")
    state_ids = [state.id for state in spec.states]
    if len(state_ids) != len(set(state_ids)):
        raise FacePackError("FacePack state identifiers must be unique")

    sequence_ids = set(ids)
    sequence_by_id = {sequence.id: sequence for sequence in spec.sequences}
    state_id_set = set(state_ids)
    frame_count = 0
    for sequence in spec.sequences:
        if not sequence.frames:
            raise FacePackError(f"sequence {sequence.id!r} has no frames")
        if sequence.fps_num <= 0 or sequence.fps_den <= 0:
            raise FacePackError(f"sequence {sequence.id!r} has an invalid FPS")
        if not 0.0 <= sequence.intensity <= 1.0:
            raise FacePackError(f"sequence {sequence.id!r} intensity is outside 0..1")
        if not math.isfinite(sequence.random_weight) or not (
            0.0 <= sequence.random_weight <= MAX_WEIGHT
        ):
            raise FacePackError(
                f"sequence {sequence.id!r} weight is outside 0..{MAX_WEIGHT:g}"
            )
        if sequence.category == SequenceCategory.SPEECH:
            if sequence.layer not in {
                SequenceLayer.FULL_FRAME,
                SequenceLayer.MOUTH_ROI,
            }:
                raise FacePackError(
                    f"speech sequence {sequence.id!r} must use full-frame or mouth ROI"
                )
        elif sequence.category == SequenceCategory.MICROACTION:
            if sequence.layer not in {
                SequenceLayer.FULL_FRAME,
                SequenceLayer.UPPER_FACE_ROI,
            }:
                raise FacePackError(
                    f"microaction {sequence.id!r} must use full-frame or upper-face ROI"
                )
        elif sequence.layer != SequenceLayer.FULL_FRAME:
            raise FacePackError(
                f"state/emotion sequence {sequence.id!r} must use the full-frame layer"
            )
        policy_flags = sequence.flags & EXPRESSION_POLICY_FLAGS
        is_expression = sequence.category in {
            SequenceCategory.EMOTION,
            SequenceCategory.INTENSE_EMOTION,
        }
        if is_expression and int(policy_flags).bit_count() != 1:
            raise FacePackError(
                f"expression {sequence.id!r} must declare exactly one affect policy"
            )
        if not is_expression and policy_flags:
            raise FacePackError(
                f"non-expression sequence {sequence.id!r} cannot declare an affect policy"
            )
        gaze_direction_flags = sequence.flags & (
            SequenceFlags.GAZE_LEFT
            | SequenceFlags.GAZE_RIGHT
            | SequenceFlags.GAZE_UP
            | SequenceFlags.GAZE_DOWN
        )
        if gaze_direction_flags and (
            sequence.category != SequenceCategory.MICROACTION
            or sequence.layer != SequenceLayer.UPPER_FACE_ROI
            or int(gaze_direction_flags).bit_count() != 1
        ):
            raise FacePackError(
                f"sequence {sequence.id!r} has invalid pack-declared gaze direction"
            )
        if sequence.flags & SequenceFlags.DELTA_BLEND and sequence.layer not in {
            SequenceLayer.MOUTH_ROI,
            SequenceLayer.UPPER_FACE_ROI,
        }:
            raise FacePackError(
                f"sequence {sequence.id!r} uses delta blend outside an ROI layer"
            )
        if sequence.category == SequenceCategory.MICROACTION and (
            sequence.speech_style != SpeechStyle.AUTOMATIC
        ):
            raise FacePackError(
                f"microaction {sequence.id!r} cannot declare a speech style"
            )
        if sequence.return_state not in state_id_set:
            raise FacePackError(
                f"sequence {sequence.id!r} refers to an unknown return state"
            )
        last_timestamp = -1
        for frame in sequence.frames:
            if not frame.jpeg.startswith(b"\xff\xd8") or not frame.jpeg.endswith(b"\xff\xd9"):
                raise FacePackError(f"sequence {sequence.id!r} contains a non-JPEG payload")
            expected_size = (
                sequence.roi[2:]
                if sequence.layer
                in {SequenceLayer.MOUTH_ROI, SequenceLayer.UPPER_FACE_ROI}
                else (spec.width, spec.height)
            )
            if (frame.width, frame.height) != expected_size:
                raise FacePackError(
                    f"sequence {sequence.id!r} frame dimensions do not match its layer"
                )
            if frame.timestamp_ms < last_timestamp:
                raise FacePackError(f"sequence {sequence.id!r} timestamps are not monotonic")
            if frame.flags:
                if sequence.layer != SequenceLayer.FULL_FRAME:
                    raise FacePackError(
                        f"sequence {sequence.id!r} has face placement metadata on an ROI frame"
                    )
                decode_face_transform(frame.flags)
            last_timestamp = frame.timestamp_ms
        anchors = (
            sequence.entry_anchor,
            sequence.onset_anchor,
            sequence.peak_anchor,
            sequence.hold_start_anchor,
            sequence.hold_end_anchor,
            sequence.exit_anchor,
        )
        if any(anchor < 0 or anchor >= len(sequence.frames) for anchor in anchors):
            raise FacePackError(f"sequence {sequence.id!r} has an out-of-range anchor")
        if tuple(anchors) != tuple(sorted(anchors)):
            raise FacePackError(f"sequence {sequence.id!r} anchors are not monotonic")
        x, y, width, height = sequence.roi
        if sequence.layer in {SequenceLayer.MOUTH_ROI, SequenceLayer.UPPER_FACE_ROI}:
            if width <= 0 or height <= 0 or x < 0 or y < 0:
                raise FacePackError(f"sequence {sequence.id!r} has an invalid ROI")
            if x + width > spec.width or y + height > spec.height:
                raise FacePackError(f"sequence {sequence.id!r} ROI exceeds the frame")
        frame_count += len(sequence.frames)

    if frame_count > MAX_FRAMES:
        raise FacePackError("FacePack frame count exceeds the v1 safety limit")
    action_count = sum(len(state.actions) for state in spec.states)
    if action_count > MAX_STATE_ACTIONS:
        raise FacePackError("FacePack state-action count exceeds the v1 safety limit")
    for state in spec.states:
        if state.base_sequence_id not in sequence_ids:
            raise FacePackError(f"state {state.id!r} refers to an unknown base sequence")
        if sequence_by_id[state.base_sequence_id].category != SequenceCategory.STATE:
            raise FacePackError(f"state {state.id!r} base is not a state sequence")
        if state.wait_min_ms < 0 or state.wait_max_ms < state.wait_min_ms:
            raise FacePackError(f"state {state.id!r} has an invalid scheduler interval")
        for action in state.actions:
            if action.sequence_id not in sequence_ids:
                raise FacePackError(f"state {state.id!r} refers to an unknown action")
            if sequence_by_id[action.sequence_id].category != SequenceCategory.MICROACTION:
                raise FacePackError(f"state {state.id!r} action is not a microaction")
            if not math.isfinite(action.weight) or not 0.0 <= action.weight <= MAX_WEIGHT:
                raise FacePackError(
                    f"state {state.id!r} action weight is outside 0..{MAX_WEIGHT:g}"
                )


def build_facepack(spec: FacePackSpec, destination: str | Path) -> FacePackSummary:
    """Build one deterministic, checksummed FacePack v1 artifact."""

    _validate_spec(spec)
    strings = _StringTable()
    pack_id_ref = strings.add(spec.pack_id)
    pack_version_ref = strings.add(spec.pack_version)
    sequence_refs = [(strings.add(item.id), strings.add(item.return_state)) for item in spec.sequences]
    state_refs = [strings.add(item.id) for item in spec.states]

    sequence_index = {sequence.id: index for index, sequence in enumerate(spec.sequences)}
    sequence_table_offset = HEADER_STRUCT.size
    sequence_table_size = len(spec.sequences) * SEQUENCE_STRUCT.size
    frame_table_offset = sequence_table_offset + sequence_table_size
    frame_count = sum(len(sequence.frames) for sequence in spec.sequences)
    frame_table_size = frame_count * FRAME_STRUCT.size
    state_table_offset = frame_table_offset + frame_table_size
    state_table_size = len(spec.states) * STATE_STRUCT.size
    state_action_count = sum(len(state.actions) for state in spec.states)
    state_action_table_offset = state_table_offset + state_table_size
    state_action_table_size = state_action_count * STATE_ACTION_STRUCT.size
    string_table_offset = state_action_table_offset + state_action_table_size
    string_data = strings.bytes()
    string_table_size = len(string_data)
    payload_offset = _align(string_table_offset + string_table_size)

    payload = bytearray()
    payload_offsets: dict[bytes, int] = {}
    frame_rows: list[bytes] = []
    sequence_rows: list[bytes] = []
    first_frame = 0
    for index, sequence in enumerate(spec.sequences):
        id_ref, return_ref = sequence_refs[index]
        x, y, roi_width, roi_height = sequence.roi
        sequence_rows.append(
            SEQUENCE_STRUCT.pack(
                id_ref[0],
                id_ref[1],
                return_ref[0],
                return_ref[1],
                int(sequence.category),
                int(sequence.layer),
                int(sequence.flags),
                sequence.priority,
                sequence.intensity,
                sequence.random_weight,
                sequence.fps_num,
                sequence.fps_den,
                first_frame,
                len(sequence.frames),
                sequence.entry_anchor,
                sequence.onset_anchor,
                sequence.peak_anchor,
                sequence.hold_start_anchor,
                sequence.hold_end_anchor,
                sequence.exit_anchor,
                x,
                y,
                roi_width,
                roi_height,
                sequence.transition_in_ms,
                sequence.transition_out_ms,
                sequence.cooldown_ms,
                int(sequence.speech_style),
            )
        )
        for local_index, frame in enumerate(sequence.frames):
            relative_payload_offset = payload_offsets.get(frame.jpeg)
            if relative_payload_offset is None:
                relative_payload_offset = len(payload)
                payload_offsets[frame.jpeg] = relative_payload_offset
                payload.extend(frame.jpeg)
            absolute_payload_offset = payload_offset + relative_payload_offset
            frame_rows.append(
                FRAME_STRUCT.pack(
                    index,
                    local_index,
                    frame.timestamp_ms,
                    int(FrameEncoding.JPEG_RGB),
                    frame.width,
                    frame.height,
                    absolute_payload_offset,
                    len(frame.jpeg),
                    frame.width * frame.height * 3,
                    binascii.crc32(frame.jpeg) & 0xFFFFFFFF,
                    frame.flags,
                )
            )
        first_frame += len(sequence.frames)

    state_rows: list[bytes] = []
    action_rows: list[bytes] = []
    first_action = 0
    for index, state in enumerate(spec.states):
        state_ref = state_refs[index]
        state_rows.append(
            STATE_STRUCT.pack(
                state_ref[0],
                state_ref[1],
                sequence_index[state.base_sequence_id],
                first_action,
                len(state.actions),
                state.wait_min_ms,
                state.wait_max_ms,
                state.flags,
                0,
                0,
                0,
                0,
            )
        )
        for action in state.actions:
            action_rows.append(
                STATE_ACTION_STRUCT.pack(
                    sequence_index[action.sequence_id],
                    round(action.weight * 1000.0),
                    action.cooldown_ms,
                    action.flags,
                )
            )
        first_action += len(state.actions)

    metadata = b"".join(sequence_rows + frame_rows + state_rows + action_rows) + string_data
    metadata += b"\x00" * (payload_offset - (string_table_offset + string_table_size))
    payload_bytes = bytes(payload)
    file_size = payload_offset + len(payload_bytes)
    if file_size > MAX_PACK_BYTES:
        raise FacePackError("FacePack exceeds the 512 MiB v1 safety limit")

    header = HEADER_STRUCT.pack(
        MAGIC,
        FORMAT_MAJOR,
        FORMAT_MINOR,
        HEADER_STRUCT.size,
        REQUIRED_ABI_MAJOR,
        spec.flags,
        spec.width,
        spec.height,
        PIXEL_FORMAT_RGB24,
        len(spec.sequences),
        frame_count,
        len(spec.states),
        state_action_count,
        sequence_table_offset,
        sequence_table_size,
        frame_table_offset,
        frame_table_size,
        state_table_offset,
        state_table_size,
        state_action_table_offset,
        state_action_table_size,
        string_table_offset,
        string_table_size,
        payload_offset,
        len(payload_bytes),
        file_size,
        binascii.crc32(metadata) & 0xFFFFFFFF,
        binascii.crc32(payload_bytes) & 0xFFFFFFFF,
        pack_id_ref[0],
        pack_id_ref[1],
        pack_version_ref[0],
        pack_version_ref[1],
    )
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(header + metadata + payload_bytes)
    temporary.replace(target)
    return inspect_facepack(target, verify_payload=True)


def _checked_span(offset: int, size: int, file_size: int, label: str) -> tuple[int, int]:
    if offset < HEADER_STRUCT.size or size < 0 or offset > file_size or size > file_size - offset:
        raise FacePackError(f"{label} range is outside the FacePack")
    return offset, offset + size


def _read_string(table: bytes, offset: int, length: int, label: str) -> str:
    if length <= 0 or offset > len(table) or length > len(table) - offset:
        raise FacePackError(f"{label} string range is invalid")
    try:
        return table[offset : offset + length].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FacePackError(f"{label} is not valid UTF-8") from exc


def inspect_facepack(path: str | Path, *, verify_payload: bool = True) -> FacePackSummary:
    """Validate a FacePack without loading image payloads into memory at once."""

    source = Path(path)
    file_size = source.stat().st_size
    if file_size < HEADER_STRUCT.size or file_size > MAX_PACK_BYTES:
        raise FacePackError("FacePack file size is outside the supported range")
    with source.open("rb") as handle:
        header_data = handle.read(HEADER_STRUCT.size)
        if len(header_data) != HEADER_STRUCT.size:
            raise FacePackError("FacePack header is truncated")
        values = HEADER_STRUCT.unpack(header_data)
        (
            magic,
            format_major,
            format_minor,
            header_size,
            required_abi,
            _flags,
            width,
            height,
            pixel_format,
            sequence_count,
            frame_count,
            state_count,
            state_action_count,
            sequence_offset,
            sequence_size,
            frame_offset,
            frame_size,
            state_offset,
            state_size,
            action_offset,
            action_size,
            string_offset,
            string_size,
            payload_offset,
            payload_size,
            declared_file_size,
            metadata_crc,
            payload_crc,
            pack_id_offset,
            pack_id_length,
            pack_version_offset,
            pack_version_length,
        ) = values
        if magic != MAGIC:
            raise FacePackError("FacePack magic is invalid")
        if (
            format_major != FORMAT_MAJOR
            or format_minor > FORMAT_MINOR
            or required_abi != REQUIRED_ABI_MAJOR
        ):
            raise FacePackError("FacePack format or ABI is incompatible")
        if header_size != HEADER_STRUCT.size or declared_file_size != file_size:
            raise FacePackError("FacePack header/file size mismatch")
        if pixel_format != PIXEL_FORMAT_RGB24:
            raise FacePackError("FacePack pixel format is unsupported")
        if not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION):
            raise FacePackError("FacePack dimensions are outside the supported range")
        if not (1 <= sequence_count <= MAX_SEQUENCES and frame_count <= MAX_FRAMES):
            raise FacePackError("FacePack sequence/frame count exceeds safety limits")
        if not (1 <= state_count <= MAX_STATES and state_action_count <= MAX_STATE_ACTIONS):
            raise FacePackError("FacePack state/action count exceeds safety limits")
        if sequence_size != sequence_count * SEQUENCE_STRUCT.size:
            raise FacePackError("FacePack sequence table size is inconsistent")
        if frame_size != frame_count * FRAME_STRUCT.size:
            raise FacePackError("FacePack frame table size is inconsistent")
        if state_size != state_count * STATE_STRUCT.size:
            raise FacePackError("FacePack state table size is inconsistent")
        if action_size != state_action_count * STATE_ACTION_STRUCT.size:
            raise FacePackError("FacePack state-action table size is inconsistent")

        spans = [
            _checked_span(sequence_offset, sequence_size, file_size, "sequence table"),
            _checked_span(frame_offset, frame_size, file_size, "frame table"),
            _checked_span(state_offset, state_size, file_size, "state table"),
            _checked_span(action_offset, action_size, file_size, "state-action table"),
            _checked_span(string_offset, string_size, file_size, "string table"),
            _checked_span(payload_offset, payload_size, file_size, "payload"),
        ]
        if spans != sorted(spans) or any(left[1] > right[0] for left, right in pairwise(spans)):
            raise FacePackError("FacePack sections overlap or are out of order")
        if payload_offset + payload_size != file_size:
            raise FacePackError("FacePack payload does not end at the declared file size")

        handle.seek(sequence_offset)
        metadata = handle.read(payload_offset - sequence_offset)
        if len(metadata) != payload_offset - sequence_offset:
            raise FacePackError("FacePack metadata is truncated")
        if binascii.crc32(metadata) & 0xFFFFFFFF != metadata_crc:
            raise FacePackError("FacePack metadata checksum does not match")

        relative_string_offset = string_offset - sequence_offset
        strings = metadata[relative_string_offset : relative_string_offset + string_size]
        pack_id = _read_string(strings, pack_id_offset, pack_id_length, "pack id")
        pack_version = _read_string(
            strings, pack_version_offset, pack_version_length, "pack version"
        )

        sequence_bytes = metadata[:sequence_size]
        sequence_frame_ranges: list[tuple[int, int]] = []
        sequence_categories: list[int] = []
        sequence_layers: list[int] = []
        sequence_rois: list[tuple[int, int, int, int]] = []
        return_states: list[str] = []
        sequence_ids: set[str] = set()
        for index in range(sequence_count):
            row = SEQUENCE_STRUCT.unpack_from(sequence_bytes, index * SEQUENCE_STRUCT.size)
            sequence_id = _read_string(strings, row[0], row[1], "sequence id")
            return_state = _read_string(strings, row[2], row[3], "return state")
            if sequence_id in sequence_ids:
                raise FacePackError("FacePack contains duplicate sequence ids")
            sequence_ids.add(sequence_id)
            category, layer = row[4], row[5]
            if category not in {int(value) for value in SequenceCategory}:
                raise FacePackError(f"sequence {sequence_id!r} has an invalid category")
            if layer not in {int(value) for value in SequenceLayer}:
                raise FacePackError(f"sequence {sequence_id!r} has an invalid layer")
            speech_category = category == int(SequenceCategory.SPEECH)
            mouth_layer = layer == int(SequenceLayer.MOUTH_ROI)
            full_frame_layer = layer == int(SequenceLayer.FULL_FRAME)
            upper_layer = layer == int(SequenceLayer.UPPER_FACE_ROI)
            if (
                (speech_category and not mouth_layer and not full_frame_layer)
                or (not speech_category and mouth_layer)
                or (speech_category and full_frame_layer and format_minor < 6)
            ):
                raise FacePackError(
                    f"sequence {sequence_id!r} violates speech/layer separation"
                )
            if upper_layer and category != int(SequenceCategory.MICROACTION):
                raise FacePackError(
                    f"sequence {sequence_id!r} violates upper-face layer separation"
                )
            if not math.isfinite(row[8]) or not 0.0 <= row[8] <= 1.0:
                raise FacePackError(f"sequence {sequence_id!r} has invalid intensity")
            if not math.isfinite(row[9]) or row[9] < 0.0 or row[10] <= 0 or row[11] <= 0:
                raise FacePackError(f"sequence {sequence_id!r} has invalid weight/FPS")
            first, count = row[12], row[13]
            if count <= 0 or first > frame_count or count > frame_count - first:
                raise FacePackError(f"sequence {sequence_id!r} has an invalid frame range")
            anchors = row[14:20]
            if any(anchor >= count for anchor in anchors):
                raise FacePackError(f"sequence {sequence_id!r} has an invalid anchor")
            if tuple(anchors) != tuple(sorted(anchors)):
                raise FacePackError(f"sequence {sequence_id!r} anchors are not monotonic")
            roi = (row[20], row[21], row[22], row[23])
            if layer in {
                int(SequenceLayer.MOUTH_ROI),
                int(SequenceLayer.UPPER_FACE_ROI),
            }:
                x, y, roi_width, roi_height = roi
                if (
                    roi_width <= 0
                    or roi_height <= 0
                    or x > width
                    or y > height
                    or roi_width > width - x
                    or roi_height > height - y
                ):
                    raise FacePackError(f"sequence {sequence_id!r} has an invalid ROI")
            speech_style = row[27]
            if speech_style not in {int(value) for value in SpeechStyle}:
                raise FacePackError(f"sequence {sequence_id!r} has an invalid speech style")
            if format_minor == 0 and speech_style != int(SpeechStyle.AUTOMATIC):
                raise FacePackError("FacePack 1.0 cannot declare speech styles")
            if (
                category == int(SequenceCategory.MICROACTION)
                and speech_style != int(SpeechStyle.AUTOMATIC)
            ):
                raise FacePackError(
                    f"microaction {sequence_id!r} cannot declare a speech style"
                )
            gaze_direction_flags = row[6] & int(
                SequenceFlags.GAZE_LEFT
                | SequenceFlags.GAZE_RIGHT
                | SequenceFlags.GAZE_UP
                | SequenceFlags.GAZE_DOWN
            )
            if gaze_direction_flags and (
                not upper_layer
                or category != int(SequenceCategory.MICROACTION)
                or gaze_direction_flags.bit_count() != 1
            ):
                raise FacePackError(
                    f"sequence {sequence_id!r} has invalid gaze direction metadata"
                )
            if row[6] & int(SequenceFlags.DELTA_BLEND) and not (
                mouth_layer or upper_layer
            ):
                raise FacePackError(
                    f"sequence {sequence_id!r} uses delta blend outside an ROI layer"
                )
            if format_minor < 2 and row[6] & int(SequenceFlags.DELTA_BLEND):
                raise FacePackError("FacePack before 1.2 cannot declare delta ROI blending")
            policy_flags = row[6] & int(EXPRESSION_POLICY_FLAGS)
            is_expression = category in {
                int(SequenceCategory.EMOTION),
                int(SequenceCategory.INTENSE_EMOTION),
            }
            if format_minor < 3 and policy_flags:
                raise FacePackError("FacePack before 1.3 cannot declare affect policy flags")
            if format_minor >= 3 and (
                (is_expression and policy_flags.bit_count() != 1)
                or (not is_expression and policy_flags != 0)
            ):
                raise FacePackError(
                    f"sequence {sequence_id!r} has invalid affect policy metadata"
                )
            sequence_frame_ranges.append((first, count))
            sequence_categories.append(category)
            sequence_layers.append(layer)
            sequence_rois.append(roi)
            return_states.append(return_state)

        frame_start = frame_offset - sequence_offset
        frame_bytes = metadata[frame_start : frame_start + frame_size]
        for index in range(frame_count):
            row = FRAME_STRUCT.unpack_from(frame_bytes, index * FRAME_STRUCT.size)
            sequence_index, local_index = row[0], row[1]
            if sequence_index >= sequence_count:
                raise FacePackError("FacePack frame refers to an unknown sequence")
            first, count = sequence_frame_ranges[sequence_index]
            layer = sequence_layers[sequence_index]
            roi = sequence_rois[sequence_index]
            roi_layer = layer in {
                int(SequenceLayer.MOUTH_ROI),
                int(SequenceLayer.UPPER_FACE_ROI),
            }
            expected_width = roi[2] if roi_layer else width
            expected_height = roi[3] if roi_layer else height
            if (
                index != first + local_index
                or local_index >= count
                or row[3] != int(FrameEncoding.JPEG_RGB)
                or row[4] != expected_width
                or row[5] != expected_height
                or row[8] != expected_width * expected_height * 3
            ):
                raise FacePackError("FacePack frame ordering is inconsistent")
            frame_flags = row[10]
            if frame_flags:
                if format_minor < 4:
                    raise FacePackError(
                        "FacePack before 1.4 cannot declare face placement metadata"
                    )
                if roi_layer:
                    raise FacePackError("FacePack ROI frame has face placement metadata")
                decode_face_transform(frame_flags)
            frame_payload_offset, frame_payload_size = row[6], row[7]
            if (
                frame_payload_offset < payload_offset
                or frame_payload_offset > file_size
                or frame_payload_size > file_size - frame_payload_offset
                or frame_payload_offset + frame_payload_size > payload_offset + payload_size
            ):
                raise FacePackError("FacePack frame payload is outside the payload section")

        action_start = action_offset - sequence_offset
        action_bytes = metadata[action_start : action_start + action_size]
        for index in range(state_action_count):
            row = STATE_ACTION_STRUCT.unpack_from(
                action_bytes, index * STATE_ACTION_STRUCT.size
            )
            if (
                row[0] >= sequence_count
                or sequence_categories[row[0]] != int(SequenceCategory.MICROACTION)
            ):
                raise FacePackError("FacePack state action is not a valid microaction")

        state_start = state_offset - sequence_offset
        state_bytes = metadata[state_start : state_start + state_size]
        state_ids: set[str] = set()
        for index in range(state_count):
            row = STATE_STRUCT.unpack_from(state_bytes, index * STATE_STRUCT.size)
            state_id = _read_string(strings, row[0], row[1], "state id")
            if state_id in state_ids:
                raise FacePackError("FacePack contains duplicate state ids")
            state_ids.add(state_id)
            if (
                row[2] >= sequence_count
                or sequence_categories[row[2]] != int(SequenceCategory.STATE)
                or row[3] > state_action_count
            ):
                raise FacePackError(f"state {state_id!r} contains an invalid reference")
            if row[4] > state_action_count - row[3] or row[6] < row[5]:
                raise FacePackError(f"state {state_id!r} has invalid actions/timing")

        unknown_returns = sorted(set(return_states).difference(state_ids))
        if unknown_returns:
            raise FacePackError("FacePack sequence refers to an unknown return state")

        if verify_payload:
            handle.seek(payload_offset)
            checksum = 0
            remaining = payload_size
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise FacePackError("FacePack payload is truncated")
                checksum = binascii.crc32(chunk, checksum)
                remaining -= len(chunk)
            if checksum & 0xFFFFFFFF != payload_crc:
                raise FacePackError("FacePack payload checksum does not match")

    return FacePackSummary(
        pack_id=pack_id,
        pack_version=pack_version,
        width=width,
        height=height,
        sequence_count=sequence_count,
        frame_count=frame_count,
        state_count=state_count,
        state_action_count=state_action_count,
        payload_bytes=payload_size,
        file_bytes=file_size,
    )
