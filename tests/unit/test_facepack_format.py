"""FacePack v1 writer/validator tests independent from H3 and OpenCV."""

from __future__ import annotations

import base64
import binascii
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from tools.facepack.facepack_format import (
    HEADER_STRUCT,
    MAX_PACK_BYTES,
    EncodedFrame,
    FacePackError,
    FacePackSpec,
    SequenceCategory,
    SequenceFlags,
    SequenceLayer,
    SequenceSpec,
    SpeechStyle,
    StateActionSpec,
    StateSpec,
    build_facepack,
    decode_face_transform,
    encode_face_transform,
    inspect_facepack,
)

JPEG_4X4 = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoH"
    "BwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQME"
    "BAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQU"
    "FBQUFBQUFBQUFBQUFBT/wAARCAAEAAQDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEA"
    "AAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIh"
    "MUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6"
    "Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZ"
    "mqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx"
    "8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAV"
    "YnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hp"
    "anN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPE"
    "xcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD5"
    "Uooor5w+gP/Z"
)


def downgrade_pack_policy_metadata(pack: Path, minor: int) -> None:
    """Model a genuine pre-1.3 pack by clearing then-undefined policy bits."""

    data = bytearray(pack.read_bytes())
    header = list(HEADER_STRUCT.unpack_from(data))
    sequence_count = int(header[9])
    sequence_offset = int(header[13])
    payload_offset = int(header[23])
    policy_mask = int(
        SequenceFlags.CONVERSATIONAL
        | SequenceFlags.EXPLICIT_ONLY
        | SequenceFlags.STATE_CONTROLLED
    )
    for index in range(sequence_count):
        flags_offset = sequence_offset + index * 112 + 24
        flags = struct.unpack_from("<I", data, flags_offset)[0]
        struct.pack_into("<I", data, flags_offset, flags & ~policy_mask)
    struct.pack_into("<H", data, 10, minor)
    header = list(HEADER_STRUCT.unpack_from(data))
    header[26] = binascii.crc32(data[sequence_offset:payload_offset]) & 0xFFFFFFFF
    data[: HEADER_STRUCT.size] = HEADER_STRUCT.pack(*header)
    pack.write_bytes(data)


def make_pack_spec(*, extra_expression: str | None = None) -> FacePackSpec:
    frame = EncodedFrame(JPEG_4X4, width=4, height=4, timestamp_ms=0)
    sequences = [
        SequenceSpec(
            id="neutral",
            category=SequenceCategory.STATE,
            layer=SequenceLayer.FULL_FRAME,
            frames=(frame,),
            fps_num=1,
            flags=SequenceFlags.INTERRUPTIBLE | SequenceFlags.SPEECH_COMPATIBLE,
        ),
        SequenceSpec(
            id="blink",
            category=SequenceCategory.MICROACTION,
            layer=SequenceLayer.FULL_FRAME,
            frames=(frame, frame, frame),
            fps_num=10,
            flags=SequenceFlags.INTERRUPTIBLE | SequenceFlags.RETURNS_TO_BASE,
            peak_anchor=1,
            hold_start_anchor=1,
            hold_end_anchor=1,
            exit_anchor=2,
        ),
        SequenceSpec(
            id="happy",
            category=SequenceCategory.EMOTION,
            layer=SequenceLayer.FULL_FRAME,
            frames=(frame, frame, frame),
            fps_num=10,
            flags=(
                SequenceFlags.INTERRUPTIBLE
                | SequenceFlags.SPEECH_COMPATIBLE
                | SequenceFlags.CONVERSATIONAL
            ),
            peak_anchor=1,
            hold_start_anchor=1,
            hold_end_anchor=1,
            exit_anchor=2,
        ),
    ]
    if extra_expression:
        sequences.append(
            SequenceSpec(
                id=extra_expression,
                category=SequenceCategory.EMOTION,
                layer=SequenceLayer.FULL_FRAME,
                frames=(frame,),
                fps_num=1,
                flags=(
                    SequenceFlags.INTERRUPTIBLE
                    | SequenceFlags.SPEECH_COMPATIBLE
                    | SequenceFlags.CONVERSATIONAL
                ),
            )
        )
    return FacePackSpec(
        pack_id="test.pack",
        pack_version="1.2.3",
        width=4,
        height=4,
        sequences=tuple(sequences),
        states=(
            StateSpec(
                id="idle",
                base_sequence_id="neutral",
                actions=(StateActionSpec("blink", weight=1.0, cooldown_ms=100),),
                wait_min_ms=50,
                wait_max_ms=100,
            ),
        ),
    )


def test_facepack_round_trip_has_versioned_tables_and_checksums(tmp_path: Path) -> None:
    pack = tmp_path / "test.facepack"
    built = build_facepack(make_pack_spec(), pack)
    inspected = inspect_facepack(pack)

    assert built == inspected
    assert inspected.pack_id == "test.pack"
    assert inspected.pack_version == "1.2.3"
    assert inspected.sequence_count == 3
    assert inspected.frame_count == 7
    assert inspected.state_action_count == 1
    assert inspected.payload_bytes == len(JPEG_4X4)


def test_facepack_1_4_round_trips_bounded_face_placement_metadata(tmp_path: Path) -> None:
    flags = encode_face_transform(119.0, -100.0, 26.0, 0.765625)
    decoded = decode_face_transform(flags)
    assert decoded == pytest.approx((119.0, -100.0, 26.0, 0.765625))

    spec = make_pack_spec()
    transformed = replace(
        spec.sequences[0],
        frames=(replace(spec.sequences[0].frames[0], flags=flags),),
    )
    pack = tmp_path / "tracked.facepack"
    build_facepack(replace(spec, sequences=(transformed, *spec.sequences[1:])), pack)
    assert inspect_facepack(pack).frame_count == 7


def test_facepack_rejects_face_placement_on_roi_or_pre_1_4_pack(tmp_path: Path) -> None:
    flags = encode_face_transform(4.0, -3.0, 2.0, 1.05)
    spec = make_pack_spec()
    roi_frame = replace(spec.sequences[0].frames[0], flags=flags)
    speech = SequenceSpec(
        id="tracked_talk",
        category=SequenceCategory.SPEECH,
        layer=SequenceLayer.MOUTH_ROI,
        frames=(roi_frame,),
        fps_num=12,
        roi=(0, 0, 4, 4),
    )
    with pytest.raises(FacePackError, match="ROI frame"):
        build_facepack(
            replace(spec, sequences=spec.sequences + (speech,)),
            tmp_path / "roi-transform.facepack",
        )

    transformed = replace(
        spec.sequences[0],
        frames=(replace(spec.sequences[0].frames[0], flags=flags),),
    )
    pack = tmp_path / "old-transform.facepack"
    build_facepack(replace(spec, sequences=(transformed, *spec.sequences[1:])), pack)
    data = bytearray(pack.read_bytes())
    header = list(HEADER_STRUCT.unpack_from(data))
    sequence_offset = int(header[13])
    payload_offset = int(header[23])
    struct.pack_into("<H", data, 10, 3)
    header = list(HEADER_STRUCT.unpack_from(data))
    header[26] = binascii.crc32(data[sequence_offset:payload_offset]) & 0xFFFFFFFF
    data[: HEADER_STRUCT.size] = HEADER_STRUCT.pack(*header)
    pack.write_bytes(data)
    with pytest.raises(FacePackError, match="before 1.4"):
        inspect_facepack(pack)


def test_facepack_rejects_corrupt_payload(tmp_path: Path) -> None:
    pack = tmp_path / "corrupt.facepack"
    build_facepack(make_pack_spec(), pack)
    data = bytearray(pack.read_bytes())
    data[-10] ^= 0xFF
    pack.write_bytes(data)

    with pytest.raises(FacePackError, match="payload checksum"):
        inspect_facepack(pack)


def test_facepack_rejects_out_of_range_frame_offset_even_with_valid_metadata_crc(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "offset.facepack"
    build_facepack(make_pack_spec(), pack)
    data = bytearray(pack.read_bytes())
    header = list(HEADER_STRUCT.unpack_from(data))
    sequence_offset = int(header[13])
    frame_offset = int(header[15])
    payload_offset = int(header[23])
    file_size = int(header[25])
    struct.pack_into("<Q", data, frame_offset + 24, file_size + 4096)
    header[26] = binascii.crc32(data[sequence_offset:payload_offset]) & 0xFFFFFFFF
    data[: HEADER_STRUCT.size] = HEADER_STRUCT.pack(*header)
    pack.write_bytes(data)

    with pytest.raises(FacePackError, match="frame payload"):
        inspect_facepack(pack)


def test_facepack_inspector_rejects_crossed_speech_layer_with_valid_crc(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "crossed-layer.facepack"
    build_facepack(make_pack_spec(), pack)
    data = bytearray(pack.read_bytes())
    header = list(HEADER_STRUCT.unpack_from(data))
    sequence_offset = int(header[13])
    payload_offset = int(header[23])
    happy_sequence_index = 2
    sequence_record_size = 112
    category_field_offset = 16
    layer_field_offset = 20
    struct.pack_into(
        "<I",
        data,
        sequence_offset + happy_sequence_index * sequence_record_size + category_field_offset,
        int(SequenceCategory.SPEECH),
    )
    struct.pack_into(
        "<I",
        data,
        sequence_offset + happy_sequence_index * sequence_record_size + layer_field_offset,
        int(SequenceLayer.UPPER_FACE_ROI),
    )
    header[26] = binascii.crc32(data[sequence_offset:payload_offset]) & 0xFFFFFFFF
    data[: HEADER_STRUCT.size] = HEADER_STRUCT.pack(*header)
    pack.write_bytes(data)

    with pytest.raises(FacePackError, match="speech/layer separation"):
        inspect_facepack(pack)


def test_facepack_rejects_incompatible_abi_and_dimension_limits(tmp_path: Path) -> None:
    pack = tmp_path / "incompatible.facepack"
    build_facepack(make_pack_spec(), pack)
    data = bytearray(pack.read_bytes())
    struct.pack_into("<H", data, 14, 99)
    pack.write_bytes(data)
    with pytest.raises(FacePackError, match="incompatible"):
        inspect_facepack(pack)

    with pytest.raises(FacePackError, match="dimensions"):
        build_facepack(
            FacePackSpec(
                **{**make_pack_spec().__dict__, "width": 4097},
            ),
            tmp_path / "too-wide.facepack",
        )


def test_facepack_rejects_duplicate_and_unknown_references(tmp_path: Path) -> None:
    spec = make_pack_spec()
    with pytest.raises(FacePackError, match="unknown action"):
        build_facepack(
            FacePackSpec(
                **{
                    **spec.__dict__,
                    "states": (
                        StateSpec(
                            id="idle",
                            base_sequence_id="neutral",
                            actions=(StateActionSpec("missing"),),
                        ),
                    ),
                }
            ),
            tmp_path / "unknown.facepack",
        )


def test_facepack_enforces_state_actions_and_supports_full_frame_speech(
    tmp_path: Path,
) -> None:
    spec = make_pack_spec()
    invalid_state = replace(
        spec,
        states=(replace(spec.states[0], base_sequence_id="happy"),),
    )
    with pytest.raises(FacePackError, match="base is not a state sequence"):
        build_facepack(invalid_state, tmp_path / "bad-state.facepack")

    invalid_action = replace(
        spec,
        states=(
            replace(
                spec.states[0],
                actions=(StateActionSpec("happy"),),
            ),
        ),
    )
    with pytest.raises(FacePackError, match="action is not a microaction"):
        build_facepack(invalid_action, tmp_path / "bad-action.facepack")

    speech_as_full_frame = SequenceSpec(
        id="talk_full",
        category=SequenceCategory.SPEECH,
        layer=SequenceLayer.FULL_FRAME,
        frames=spec.sequences[0].frames,
        fps_num=12,
        flags=SequenceFlags.LOOPABLE | SequenceFlags.INTERRUPTIBLE,
        speech_style=SpeechStyle.NORMAL,
    )
    speech_pack = tmp_path / "full-frame-speech.facepack"
    build_facepack(
        replace(spec, sequences=spec.sequences + (speech_as_full_frame,)),
        speech_pack,
    )
    assert inspect_facepack(speech_pack).sequence_count == 4

    legacy_bytes = bytearray(speech_pack.read_bytes())
    struct.pack_into("<H", legacy_bytes, 10, 5)
    legacy_pack = tmp_path / "pre-1.6-full-frame-speech.facepack"
    legacy_pack.write_bytes(legacy_bytes)
    with pytest.raises(FacePackError, match="speech/layer separation"):
        inspect_facepack(legacy_pack)


def test_facepack_round_trips_composable_upper_face_layer(tmp_path: Path) -> None:
    spec = make_pack_spec()
    upper = SequenceSpec(
        id="gaze_left",
        category=SequenceCategory.MICROACTION,
        layer=SequenceLayer.UPPER_FACE_ROI,
        frames=spec.sequences[0].frames * 2,
        fps_num=12,
        flags=(
            SequenceFlags.INTERRUPTIBLE
            | SequenceFlags.RETURNS_TO_BASE
            | SequenceFlags.GAZE_LEFT
            | SequenceFlags.DELTA_BLEND
        ),
        roi=(0, 0, 4, 4),
        peak_anchor=1,
        hold_start_anchor=1,
        hold_end_anchor=1,
        exit_anchor=1,
    )
    layered = replace(
        spec,
        sequences=spec.sequences + (upper,),
        states=(
            replace(
                spec.states[0],
                actions=spec.states[0].actions + (StateActionSpec("gaze_left"),),
            ),
        ),
    )
    pack = tmp_path / "upper.facepack"

    summary = build_facepack(layered, pack)

    assert inspect_facepack(pack) == summary
    assert summary.sequence_count == 4
    assert summary.state_action_count == 2

    downgrade_pack_policy_metadata(pack, 1)
    with pytest.raises(FacePackError, match="before 1.2"):
        inspect_facepack(pack)


def test_facepack_rejects_invalid_layer_metadata_and_unbounded_weights(
    tmp_path: Path,
) -> None:
    spec = make_pack_spec()
    invalid_style = replace(spec.sequences[1], speech_style=SpeechStyle.HAPPY)
    with pytest.raises(FacePackError, match="cannot declare a speech style"):
        build_facepack(
            replace(spec, sequences=(spec.sequences[0], invalid_style, *spec.sequences[2:])),
            tmp_path / "micro-style.facepack",
        )

    with pytest.raises(FacePackError, match="weight is outside"):
        build_facepack(
            replace(
                spec,
                sequences=(replace(spec.sequences[0], random_weight=1001.0), *spec.sequences[1:]),
            ),
            tmp_path / "huge-weight.facepack",
        )

    gaze = SequenceSpec(
        id="bad_gaze",
        category=SequenceCategory.MICROACTION,
        layer=SequenceLayer.UPPER_FACE_ROI,
        frames=spec.sequences[0].frames,
        fps_num=12,
        flags=SequenceFlags.GAZE_LEFT | SequenceFlags.GAZE_UP,
        roi=(0, 0, 4, 4),
    )
    with pytest.raises(FacePackError, match="invalid pack-declared gaze"):
        build_facepack(
            replace(spec, sequences=spec.sequences + (gaze,)),
            tmp_path / "ambiguous-gaze.facepack",
        )

    invalid_delta = replace(
        spec.sequences[2],
        flags=spec.sequences[2].flags | SequenceFlags.DELTA_BLEND,
    )
    with pytest.raises(FacePackError, match="delta blend outside"):
        build_facepack(
            replace(spec, sequences=(*spec.sequences[:2], invalid_delta)),
            tmp_path / "full-frame-delta.facepack",
        )


def test_format_1_0_pack_remains_compatible(tmp_path: Path) -> None:
    pack = tmp_path / "format-1-0.facepack"
    summary = build_facepack(make_pack_spec(), pack)
    downgrade_pack_policy_metadata(pack, 0)

    assert inspect_facepack(pack) == summary


def test_format_1_2_pack_remains_compatible_without_policy_metadata(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "format-1-2.facepack"
    summary = build_facepack(make_pack_spec(), pack)
    downgrade_pack_policy_metadata(pack, 2)

    assert inspect_facepack(pack) == summary


def test_facepack_rejects_files_above_memory_safety_bound(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.facepack"
    with oversized.open("wb") as handle:
        handle.truncate(MAX_PACK_BYTES + 1)
    with pytest.raises(FacePackError, match="file size"):
        inspect_facepack(oversized)
