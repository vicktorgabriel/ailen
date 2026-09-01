"""Compile curated H3 source frames into an external AILEN FacePack.

MP4, OpenCV, and YuNet are build-time inputs only.  The resulting artifact
contains checksummed JPEG frame payloads and can be decoded by the native
engine without FFmpeg or OpenCV at runtime.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tools.facepack.facepack_format import (
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
    encode_face_transform,
)

CATEGORY_BY_NAME = {
    "state": SequenceCategory.STATE,
    "microaction": SequenceCategory.MICROACTION,
    "emotion": SequenceCategory.EMOTION,
    "intense_emotion": SequenceCategory.INTENSE_EMOTION,
    "speech": SequenceCategory.SPEECH,
}
LAYER_BY_NAME = {
    "full_frame": SequenceLayer.FULL_FRAME,
    "mouth_roi": SequenceLayer.MOUTH_ROI,
    "upper_face_roi": SequenceLayer.UPPER_FACE_ROI,
}
FLAG_BY_NAME = {
    "loopable": SequenceFlags.LOOPABLE,
    "interruptible": SequenceFlags.INTERRUPTIBLE,
    "speech_compatible": SequenceFlags.SPEECH_COMPATIBLE,
    "gaze_compatible": SequenceFlags.GAZE_COMPATIBLE,
    "returns_to_base": SequenceFlags.RETURNS_TO_BASE,
    "conversational": SequenceFlags.CONVERSATIONAL,
    "explicit_only": SequenceFlags.EXPLICIT_ONLY,
    "state_controlled": SequenceFlags.STATE_CONTROLLED,
    "gaze_left": SequenceFlags.GAZE_LEFT,
    "gaze_right": SequenceFlags.GAZE_RIGHT,
    "gaze_up": SequenceFlags.GAZE_UP,
    "gaze_down": SequenceFlags.GAZE_DOWN,
    "delta_blend": SequenceFlags.DELTA_BLEND,
}
SPEECH_STYLE_BY_NAME = {
    "automatic": SpeechStyle.AUTOMATIC,
    "soft": SpeechStyle.SOFT,
    "normal": SpeechStyle.NORMAL,
    "expressive": SpeechStyle.EXPRESSIVE,
    "happy": SpeechStyle.HAPPY,
    "serious": SpeechStyle.SERIOUS,
}
EXPRESSION_POLICY_BY_NAME = {
    "conversational": SequenceFlags.CONVERSATIONAL,
    "explicit_only": SequenceFlags.EXPLICIT_ONLY,
    "state_controlled": SequenceFlags.STATE_CONTROLLED,
}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FacePackError(f"could not read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FacePackError(f"JSON root must be an object: {path}")
    return value


def _source_map(inventory_path: Path, source_dir: Path) -> dict[int, Path]:
    inventory = _load_json(inventory_path)
    videos = inventory.get("videos")
    if not isinstance(videos, list):
        raise FacePackError("source inventory has no videos array")
    root = source_dir.resolve()
    result: dict[int, Path] = {}
    for raw in videos:
        if not isinstance(raw, dict):
            continue
        sequence = int(raw.get("sequence", 0))
        filename = str(raw.get("filename", ""))
        candidate = (root / filename).resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise FacePackError(f"inventory source is missing or escapes source root: {filename}")
        result[sequence] = candidate
    return result


def _expand_source_frames(raw_sequence: dict[str, Any]) -> list[tuple[int, int]]:
    """Return ordered ``(source_sequence, source_frame)`` references."""

    references: list[tuple[int, int]] = []
    default_source = int(raw_sequence.get("source_sequence", 0))
    raw_indices = raw_sequence.get("frame_indices")
    if isinstance(raw_indices, list):
        references.extend((default_source, int(index)) for index in raw_indices)
    raw_segments = raw_sequence.get("segments")
    if isinstance(raw_segments, list):
        for raw_segment in raw_segments:
            if not isinstance(raw_segment, dict):
                raise FacePackError("sequence segment must be an object")
            source = int(raw_segment.get("source_sequence", default_source))
            if isinstance(raw_segment.get("indices"), list):
                references.extend((source, int(index)) for index in raw_segment["indices"])
                continue
            start = int(raw_segment["start"])
            end = int(raw_segment["end"])
            step = int(raw_segment.get("step", 1 if end >= start else -1))
            if step == 0 or (end - start) * step < 0:
                raise FacePackError("sequence segment has an invalid step")
            stop = end + (1 if step > 0 else -1)
            references.extend((source, index) for index in range(start, stop, step))
    if not references or any(source <= 0 or frame < 0 for source, frame in references):
        raise FacePackError(f"sequence {raw_sequence.get('id')!r} has no valid source frames")
    return references


def _read_selected_frames(cv2: Any, path: Path, indices: set[int]) -> dict[int, Any]:
    if not indices:
        return {}
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise FacePackError(f"OpenCV could not open source video: {path}")
    wanted = sorted(indices)
    result: dict[int, Any] = {}
    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, wanted[0])
        current = wanted[0]
        wanted_position = 0
        while wanted_position < len(wanted):
            ok, frame = capture.read()
            if not ok:
                break
            target = wanted[wanted_position]
            if current == target:
                result[target] = frame
                wanted_position += 1
            current += 1
    finally:
        capture.release()
    missing = indices.difference(result)
    if missing:
        sample = ", ".join(str(value) for value in sorted(missing)[:5])
        raise FacePackError(f"source {path.name} is missing requested frames: {sample}")
    return result


def _resize_frame(cv2: Any, frame: Any, width: int, height: int) -> Any:
    source_height, source_width = frame.shape[:2]
    target_ratio = width / height
    source_ratio = source_width / source_height
    if source_ratio > target_ratio:
        cropped_width = round(source_height * target_ratio)
        left = max(0, (source_width - cropped_width) // 2)
        frame = frame[:, left : left + cropped_width]
    elif source_ratio < target_ratio:
        cropped_height = round(source_width / target_ratio)
        top = max(0, (source_height - cropped_height) // 2)
        frame = frame[top : top + cropped_height, :]
    interpolation = cv2.INTER_AREA if frame.shape[1] > width else cv2.INTER_CUBIC
    return cv2.resize(frame, (width, height), interpolation=interpolation)


class _FaceAligner:
    """Derive fixed per-source similarity transforms with build-time YuNet."""

    def __init__(self, cv2: Any, model_path: Path, reference: Any) -> None:
        if not model_path.is_file():
            raise FacePackError(f"YuNet model is missing: {model_path}")
        self._cv2 = cv2
        height, width = reference.shape[:2]
        self._detector = cv2.FaceDetectorYN.create(
            str(model_path), "", (width, height), 0.8, 0.3, 5000
        )
        self._size = (width, height)
        self._reference_points = self._landmarks(reference)[:3]

    def _landmarks(self, frame: Any) -> Any:
        self._detector.setInputSize(self._size)
        _, faces = self._detector.detect(frame)
        if faces is None or len(faces) != 1:
            raise FacePackError("YuNet did not find exactly one face in a composable ROI frame")
        # YuNet: right eye, left eye, nose, right mouth corner, left mouth corner.
        return faces[0][4:14].reshape(5, 2).astype("float32")

    def transform(self, entry_frame: Any) -> Any:
        """Align eyes/nose once so expression and mouth motion are not cancelled."""

        points = self._landmarks(entry_frame)[:3]
        matrix, _ = self._cv2.estimateAffinePartial2D(
            points,
            self._reference_points,
            method=self._cv2.LMEDS,
        )
        if matrix is None:
            raise FacePackError("could not derive a stable source alignment")
        return matrix

    def apply(self, frame: Any, matrix: Any) -> Any:
        """Apply one source transform without reflecting duplicated edge content."""

        patch_size = max(4, min(frame.shape[0], frame.shape[1]) // 32)
        top_left = self._cv2.mean(frame[:patch_size, :patch_size])[:3]
        top_right = self._cv2.mean(frame[:patch_size, -patch_size:])[:3]
        background = tuple(
            (float(left) + float(right)) / 2.0
            for left, right in zip(top_left, top_right, strict=True)
        )

        return self._cv2.warpAffine(
            frame,
            matrix,
            self._size,
            flags=self._cv2.INTER_LINEAR,
            borderMode=self._cv2.BORDER_CONSTANT,
            borderValue=background,
        )

    def align(self, frame: Any) -> Any:
        """Normalize one composable frame to the canonical eyes/nose anchor."""

        return self.apply(frame, self.transform(frame))


def _anchor_index(raw_value: Any, frame_count: int) -> int:
    if isinstance(raw_value, float):
        if not 0.0 <= raw_value <= 1.0:
            raise FacePackError("normalized sequence anchor must be between 0 and 1")
        return min(frame_count - 1, round(raw_value * (frame_count - 1)))
    value = int(raw_value)
    if value < 0:
        value = frame_count + value
    return min(frame_count - 1, max(0, value))


def _sequence_flags(values: Any) -> SequenceFlags:
    if not isinstance(values, list):
        raise FacePackError("sequence flags must be an array")
    result = SequenceFlags(0)
    for value in values:
        try:
            result |= FLAG_BY_NAME[str(value)]
        except KeyError as exc:
            raise FacePackError(f"unknown sequence flag: {value}") from exc
    return result


def _alignment_mode(
    layer: SequenceLayer,
    full_frame_alignment: str,
) -> str:
    """Keep ROI overlays composable while preserving natural full-frame motion."""

    if layer in {SequenceLayer.MOUTH_ROI, SequenceLayer.UPPER_FACE_ROI}:
        return "per_frame"
    return full_frame_alignment


def _relative_face_transform(entry: Any, current: Any) -> tuple[float, float, float, float]:
    """Return the canonical-to-current-base similarity transform.

    Both inputs map their source frame into the canonical anchor. The full
    frame is rendered with ``entry`` so ``entry * inverse(current)`` maps a
    canonical ROI onto the authored head position in the rendered base frame.
    """

    a, b, entry_tx = (float(value) for value in entry[0])
    c, d, entry_ty = (float(value) for value in entry[1])
    p, q, current_tx = (float(value) for value in current[0])
    r, s, current_ty = (float(value) for value in current[1])
    determinant = p * s - q * r
    if abs(determinant) < 1e-8:
        raise FacePackError("source frame has a singular face alignment transform")
    inverse_p = s / determinant
    inverse_q = -q / determinant
    inverse_r = -r / determinant
    inverse_s = p / determinant
    inverse_tx = -(inverse_p * current_tx + inverse_q * current_ty)
    inverse_ty = -(inverse_r * current_tx + inverse_s * current_ty)
    out_a = a * inverse_p + b * inverse_r
    out_b = a * inverse_q + b * inverse_s
    out_c = c * inverse_p + d * inverse_r
    out_d = c * inverse_q + d * inverse_s
    out_tx = a * inverse_tx + b * inverse_ty + entry_tx
    out_ty = c * inverse_tx + d * inverse_ty + entry_ty
    scale = (out_a * out_a + out_c * out_c) ** 0.5
    angle_degrees = math.degrees(math.atan2(out_c, out_a))
    # estimateAffinePartial2D yields a similarity matrix. Reject unexpected
    # shear instead of silently encoding placement that would deform the ROI.
    if abs(out_b + out_c) > 0.02 or abs(out_d - out_a) > 0.02:
        raise FacePackError("source frame alignment is not a stable similarity transform")
    return out_tx, out_ty, angle_degrees, scale


def _expression_policy_map(manifest: dict[str, Any]) -> dict[str, SequenceFlags]:
    """Expand the manifest policy table into one trusted flag per expression id."""

    raw_policies = manifest.get("expression_policies")
    if not isinstance(raw_policies, dict):
        raise FacePackError("curation manifest has no expression_policies object")
    result: dict[str, SequenceFlags] = {}
    for policy_name, policy_flag in EXPRESSION_POLICY_BY_NAME.items():
        values = raw_policies.get(policy_name)
        if not isinstance(values, list):
            raise FacePackError(f"expression policy {policy_name!r} must be an array")
        for raw_id in values:
            sequence_id = str(raw_id).strip()
            if not sequence_id:
                raise FacePackError(f"expression policy {policy_name!r} contains an empty id")
            if sequence_id in result:
                raise FacePackError(
                    f"expression {sequence_id!r} has more than one affect policy"
                )
            result[sequence_id] = policy_flag
    unknown_policies = set(raw_policies) - set(EXPRESSION_POLICY_BY_NAME)
    if unknown_policies:
        raise FacePackError(
            "unknown expression policy keys: " + ", ".join(sorted(unknown_policies))
        )
    return result


def _encode_jpeg(cv2: Any, frame: Any, quality: int) -> bytes:
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise FacePackError("OpenCV could not encode a curated frame")
    return bytes(encoded)


def compile_manifest(
    manifest_path: Path,
    inventory_path: Path,
    source_dir: Path,
    output_path: Path,
    yunet_model_path: Path,
) -> dict[str, Any]:
    """Compile one curated manifest and return a machine-readable build report."""

    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise FacePackError("OpenCV is required only to compile an H3 FacePack") from exc

    started = time.perf_counter()
    manifest = _load_json(manifest_path)
    if int(manifest.get("schema_version", 0)) != 1:
        raise FacePackError("curation manifest schema_version must be 1")
    width = int(manifest.get("width", 0))
    height = int(manifest.get("height", 0))
    jpeg_quality = int(manifest.get("jpeg_quality", 90))
    normalize_sources = bool(manifest.get("normalize_sources", False))
    full_frame_alignment = str(
        manifest.get("full_frame_alignment", "source_entry")
    ).strip().lower()
    if full_frame_alignment not in {"source_entry", "none"}:
        raise FacePackError(
            "curation manifest full_frame_alignment must be source_entry or none"
        )
    if not 50 <= jpeg_quality <= 100:
        raise FacePackError("jpeg_quality must be between 50 and 100")
    sources = _source_map(inventory_path, source_dir)

    raw_sequences = manifest.get("sequences")
    if not isinstance(raw_sequences, list):
        raise FacePackError("curation manifest has no sequences array")
    expression_policies = _expression_policy_map(manifest)
    declared_sequence_ids = {
        str(raw.get("id", "")) for raw in raw_sequences if isinstance(raw, dict)
    }
    unknown_policy_ids = set(expression_policies) - declared_sequence_ids
    if unknown_policy_ids:
        raise FacePackError(
            "expression policies refer to unknown sequences: "
            + ", ".join(sorted(unknown_policy_ids))
        )

    references_by_sequence: dict[str, list[tuple[int, int]]] = {}
    all_requested: dict[int, set[int]] = defaultdict(set)
    for raw in raw_sequences:
        if not isinstance(raw, dict):
            raise FacePackError("curation sequence must be an object")
        references = _expand_source_frames(raw)
        sequence_id = str(raw.get("id", ""))
        references_by_sequence[sequence_id] = references
        for source_sequence, frame_index in references:
            if source_sequence not in sources:
                raise FacePackError(f"unknown source video sequence: {source_sequence}")
            all_requested[source_sequence].add(frame_index)

    alignment_reference = manifest.get("alignment_reference", {"source_sequence": 1, "frame": 0})
    reference_source = int(alignment_reference.get("source_sequence", 1))
    reference_index = int(alignment_reference.get("frame", 0))
    all_requested[reference_source].add(reference_index)
    if normalize_sources or any(
        raw.get("layer") in {"mouth_roi", "upper_face_roi"}
        for raw in raw_sequences
    ):
        for source_sequence in tuple(all_requested):
            all_requested[source_sequence].add(0)

    source_frames: dict[int, dict[int, Any]] = {}
    for source_sequence, indices in all_requested.items():
        decoded = _read_selected_frames(cv2, sources[source_sequence], indices)
        source_frames[source_sequence] = {
            frame_index: _resize_frame(cv2, frame, width, height)
            for frame_index, frame in decoded.items()
        }
    reference = source_frames[reference_source][reference_index]
    aligner: _FaceAligner | None = None
    if normalize_sources or any(
        raw.get("layer") in {"mouth_roi", "upper_face_roi"}
        for raw in raw_sequences
    ):
        aligner = _FaceAligner(cv2, yunet_model_path, reference)
    source_transforms = (
        {
            source_sequence: aligner.transform(frames[0])
            for source_sequence, frames in source_frames.items()
        }
        if aligner is not None
        else {}
    )
    aligned_entry_frames = (
        {
            source_sequence: aligner.align(frames[0])
            for source_sequence, frames in source_frames.items()
        }
        if aligner is not None
        else {}
    )

    sequences: list[SequenceSpec] = []
    report_sequences: list[dict[str, Any]] = []
    for raw in raw_sequences:
        sequence_id = str(raw["id"])
        try:
            category = CATEGORY_BY_NAME[str(raw["category"])]
            layer = LAYER_BY_NAME[str(raw.get("layer", "full_frame"))]
        except KeyError as exc:
            raise FacePackError(f"sequence {sequence_id!r} has an unknown category/layer") from exc
        fps_num = int(raw.get("fps_num", raw.get("fps", 12)))
        fps_den = int(raw.get("fps_den", 1))
        roi_raw = raw.get("roi", [0, 0, 0, 0])
        if not isinstance(roi_raw, list) or len(roi_raw) != 4:
            raise FacePackError(f"sequence {sequence_id!r} ROI must have four integers")
        roi = (
            int(roi_raw[0]),
            int(roi_raw[1]),
            int(roi_raw[2]),
            int(roi_raw[3]),
        )
        dedup_threshold = float(raw.get("deduplicate_mad", 0.0))
        sequence_flags = _sequence_flags(raw.get("flags", ["interruptible"]))
        sequence_flags |= expression_policies.get(sequence_id, SequenceFlags(0))
        delta_channels = str(raw.get("delta_channels", "color"))
        delta_deadzone = int(raw.get("delta_deadzone", 0))
        if delta_channels not in {"color", "luma"}:
            raise FacePackError(
                f"sequence {sequence_id!r} has unknown delta_channels {delta_channels!r}"
            )
        if delta_channels != "color" and not (
            sequence_flags & SequenceFlags.DELTA_BLEND
        ):
            raise FacePackError(
                f"sequence {sequence_id!r} declares delta channels without delta blend"
            )
        if not 0 <= delta_deadzone <= 64:
            raise FacePackError(
                f"sequence {sequence_id!r} delta_deadzone must be between 0 and 64"
            )
        if delta_deadzone and not (sequence_flags & SequenceFlags.DELTA_BLEND):
            raise FacePackError(
                f"sequence {sequence_id!r} declares a delta dead-zone without delta blend"
            )
        curated_frames: list[Any] = []
        curated_frame_flags: list[int] = []
        dropped_duplicates = 0
        previous: Any | None = None
        for source_sequence, frame_index in references_by_sequence[sequence_id]:
            frame = source_frames[source_sequence][frame_index]
            frame_flags = 0
            if aligner is not None:
                alignment_mode = _alignment_mode(layer, full_frame_alignment)
                if alignment_mode == "per_frame":
                    frame = aligner.align(frame)
                elif alignment_mode == "source_entry":
                    current_transform = aligner.transform(frame)
                    frame_flags = encode_face_transform(
                        *_relative_face_transform(
                            source_transforms[source_sequence],
                            current_transform,
                        )
                    )
                    frame = aligner.apply(frame, source_transforms[source_sequence])
            if layer in {SequenceLayer.MOUTH_ROI, SequenceLayer.UPPER_FACE_ROI}:
                if aligner is None:
                    raise FacePackError("composable ROI requested without a configured aligner")
                x, y, roi_width, roi_height = roi
                frame = frame[y : y + roi_height, x : x + roi_width]
                if sequence_flags & SequenceFlags.DELTA_BLEND:
                    baseline = aligned_entry_frames[source_sequence][
                        y : y + roi_height,
                        x : x + roi_width,
                    ]
                    difference = frame.astype("int16") - baseline.astype("int16")
                    if delta_deadzone:
                        unchanged = cv2.absdiff(frame, baseline) <= delta_deadzone
                        difference[unchanged] = 0
                    if delta_channels == "luma":
                        luminance = (
                            0.114 * difference[:, :, 0]
                            + 0.587 * difference[:, :, 1]
                            + 0.299 * difference[:, :, 2]
                            + 128
                        ).clip(0, 255).astype("uint8")
                        frame = cv2.merge((luminance, luminance, luminance))
                    else:
                        frame = (difference + 128).clip(0, 255).astype("uint8")
            if previous is not None and dedup_threshold > 0.0:
                difference = cv2.absdiff(previous, frame)
                mean_difference = float(difference.mean())
                if mean_difference < dedup_threshold:
                    dropped_duplicates += 1
                    continue
            curated_frames.append(frame)
            curated_frame_flags.append(frame_flags)
            previous = frame
        if not curated_frames:
            raise FacePackError(f"sequence {sequence_id!r} lost every frame during curation")

        encoded_frames = tuple(
            EncodedFrame(
                jpeg=_encode_jpeg(cv2, frame, jpeg_quality),
                width=frame.shape[1],
                height=frame.shape[0],
                timestamp_ms=round(index * 1000 * fps_den / fps_num),
                flags=curated_frame_flags[index],
            )
            for index, frame in enumerate(curated_frames)
        )
        anchors_raw = raw.get("anchors", {})
        if not isinstance(anchors_raw, dict):
            raise FacePackError(f"sequence {sequence_id!r} anchors must be an object")
        def anchor(
            name: str,
            default: float,
            *,
            raw_values: dict[str, Any] = anchors_raw,
            frame_count: int = len(encoded_frames),
        ) -> int:
            return _anchor_index(raw_values.get(name, default), frame_count)
        try:
            speech_style = SPEECH_STYLE_BY_NAME[
                str(raw.get("speech_style", "automatic"))
            ]
        except KeyError as exc:
            raise FacePackError(
                f"sequence {sequence_id!r} has an unknown speech style"
            ) from exc
        sequence = SequenceSpec(
            id=sequence_id,
            category=category,
            layer=layer,
            frames=encoded_frames,
            fps_num=fps_num,
            fps_den=fps_den,
            flags=sequence_flags,
            priority=int(raw.get("priority", 0)),
            intensity=float(raw.get("intensity", 0.5)),
            random_weight=float(raw.get("random_weight", 1.0)),
            return_state=str(raw.get("return_state", "idle")),
            entry_anchor=anchor("entry", 0),
            onset_anchor=anchor("onset", 0.2),
            peak_anchor=anchor("peak", 0.5),
            hold_start_anchor=anchor("hold_start", 0.5),
            hold_end_anchor=anchor("hold_end", 0.7),
            exit_anchor=anchor("exit", 1.0),
            roi=roi,
            transition_in_ms=int(raw.get("transition_in_ms", 0)),
            transition_out_ms=int(raw.get("transition_out_ms", 0)),
            cooldown_ms=int(raw.get("cooldown_ms", 0)),
            speech_style=speech_style,
        )
        sequences.append(sequence)
        report_sequences.append(
            {
                "id": sequence_id,
                "source_frames": len(references_by_sequence[sequence_id]),
                "packed_frames": len(encoded_frames),
                "deduplicated_frames": dropped_duplicates,
                "encoded_bytes": sum(len(frame.jpeg) for frame in encoded_frames),
                "category": str(raw["category"]),
                "layer": str(raw.get("layer", "full_frame")),
                "delta_channels": delta_channels,
                "delta_deadzone": delta_deadzone,
                "affect_policy": next(
                    (
                        name
                        for name, flag in EXPRESSION_POLICY_BY_NAME.items()
                        if sequence_flags & flag
                    ),
                    "none",
                ),
            }
        )

    raw_states = manifest.get("states")
    if not isinstance(raw_states, list):
        raise FacePackError("curation manifest has no states array")
    states: list[StateSpec] = []
    for raw in raw_states:
        if not isinstance(raw, dict):
            raise FacePackError("state entry must be an object")
        actions = tuple(
            StateActionSpec(
                sequence_id=str(action["sequence"]),
                weight=float(action.get("weight", 1.0)),
                cooldown_ms=int(action.get("cooldown_ms", 0)),
                flags=int(action.get("flags", 0)),
            )
            for action in raw.get("actions", [])
        )
        states.append(
            StateSpec(
                id=str(raw["id"]),
                base_sequence_id=str(raw["base_sequence"]),
                actions=actions,
                wait_min_ms=int(raw.get("wait_min_ms", 2500)),
                wait_max_ms=int(raw.get("wait_max_ms", 6000)),
                flags=int(raw.get("flags", 0)),
            )
        )

    summary = build_facepack(
        FacePackSpec(
            pack_id=str(manifest["pack_id"]),
            pack_version=str(manifest["pack_version"]),
            width=width,
            height=height,
            sequences=tuple(sequences),
            states=tuple(states),
        ),
        output_path,
    )
    return {
        "manifest": str(manifest_path),
        "output": str(output_path),
        "build_seconds": round(time.perf_counter() - started, 3),
        "jpeg_quality": jpeg_quality,
        "summary": asdict(summary),
        "sequences": report_sequences,
        "runtime_dependencies": ["libjpeg"],
        "runtime_uses_mp4": False,
        "normalization": (
            f"per_frame_roi_and_{full_frame_alignment}_full_frame_eyes_nose"
            if any(
                sequence.layer
                in {SequenceLayer.MOUTH_ROI, SequenceLayer.UPPER_FACE_ROI}
                for sequence in sequences
            )
            else f"{full_frame_alignment}_full_frame_eyes_nose"
            if aligner is not None
            else "none"
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("src/ailen/face/assets/raw_h3/source_inventory.json"),
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("src/ailen/face/assets/raw_h3/source_videos"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--yunet-model",
        type=Path,
        default=Path("runtime/lab/vision_models/face_detection_yunet_2023mar.onnx"),
    )
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = compile_manifest(
            args.manifest,
            args.inventory,
            args.source_dir,
            args.output,
            args.yunet_model,
        )
    except (FacePackError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"FacePack compile failed: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
