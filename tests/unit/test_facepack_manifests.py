"""Traceability checks for the curated H3 corpus and desktop FacePack manifest."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from tools.facepack.compile_facepack import (
    _alignment_mode,
    _expand_source_frames,
    _relative_face_transform,
)
from tools.facepack.facepack_format import (
    SequenceLayer,
    decode_face_transform,
    encode_face_transform,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_ROOT = REPO_ROOT / "tools" / "facepack" / "manifests"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_h3_classification_is_complete_visual_and_traceable() -> None:
    classification = _json(MANIFEST_ROOT / "h3_classification.json")
    videos = classification["videos"]

    assert classification["classification_is_visual"] is True
    assert classification["source_video_count"] == 85
    assert [video["sequence"] for video in videos] == list(range(1, 86))
    assert Counter(video["decision"] for video in videos) == {
        "keep": 50,
        "trim": 28,
        "review": 3,
        "discard": 4,
    }
    for video in videos:
        assert video["canonical_id"]
        assert video["category"]
        assert video["quality_profile"] in classification["quality_profiles"]
        assert 0.0 <= video["intensity"] <= 1.0
        assert set(video["timing"]) == {"initial", "onset", "peak", "hold", "return"}
        assert video["notes"]


def test_desktop_pack_uses_only_classified_non_discarded_sources() -> None:
    classification = _json(MANIFEST_ROOT / "h3_classification.json")
    decision_by_source = {
        video["sequence"]: video["decision"] for video in classification["videos"]
    }
    desktop = _json(MANIFEST_ROOT / "ailen_default_desktop.json")
    referenced: set[int] = set()
    for sequence in desktop["sequences"]:
        default_source = sequence.get("source_sequence")
        if default_source is not None:
            referenced.add(int(default_source))
        for segment in sequence.get("segments", []):
            source = segment.get("source_sequence", default_source)
            assert source is not None
            referenced.add(int(source))

    assert referenced
    assert all(decision_by_source[source] in {"keep", "trim"} for source in referenced)
    assert not referenced.intersection({39, 83, 84, 85})
    assert not referenced.intersection({28, 64, 82})
    assert set(decision_by_source).difference(referenced) == {2, 27, 28, 39, 64, 82, 83, 84, 85}


def test_desktop_pack_is_a_broad_layered_library_not_a_vertical_slice() -> None:
    desktop = _json(MANIFEST_ROOT / "ailen_default_desktop.json")
    sequences = desktop["sequences"]
    by_id = {sequence["id"]: sequence for sequence in sequences}
    categories = Counter(sequence["category"] for sequence in sequences)
    layers = Counter(sequence.get("layer", "full_frame") for sequence in sequences)

    assert len(sequences) == 79
    assert categories == {
        "state": 2,
        "microaction": 28,
        "emotion": 30,
        "intense_emotion": 9,
        "speech": 10,
    }
    assert layers == {"full_frame": 79}
    assert len(desktop["states"]) == 6
    assert desktop["full_frame_alignment"] == "source_entry"
    assert _alignment_mode(SequenceLayer.FULL_FRAME, "source_entry") == "source_entry"
    assert _alignment_mode(SequenceLayer.MOUTH_ROI, "source_entry") == "per_frame"
    assert _alignment_mode(SequenceLayer.UPPER_FACE_ROI, "source_entry") == "per_frame"
    policies = desktop["expression_policies"]
    assert {name: len(values) for name, values in policies.items()} == {
        "conversational": 22,
        "explicit_only": 13,
        "state_controlled": 4,
    }
    declared_policy_ids = {
        expression_id for values in policies.values() for expression_id in values
    }
    expression_ids = {
        sequence["id"]
        for sequence in sequences
        if sequence["category"] in {"emotion", "intense_emotion"}
    }
    assert declared_policy_ids == expression_ids
    assert not set(policies["conversational"]).intersection(
        {"wink_left", "laugh_hard", "crying", "sleepy", "falling_asleep", "yawn"}
    )

    required = {
        "anger",
        "anger_moderate",
        "anger_strong",
        "worried",
        "relief",
        "sadness_soft",
        "sadness_strong",
        "surprised_soft",
        "surprised_strong",
        "joy",
        "laugh",
        "laugh_hard",
        "laugh_full",
        "crying",
        "crying_tears",
        "falling_asleep",
        "yawn",
        "wake_up",
        "blink_double",
        "eye_wink_left",
        "eye_wink_right",
        "brows_both_raise",
        "gaze_left_strong",
        "gaze_right_strong",
        "nod_yes",
        "shake_no",
        "acknowledge",
        "head_tilt_left",
        "head_tilt_right",
        "talk_soft",
        "talk_normal",
        "talk_expressive",
        "talk_happy",
        "talk_serious",
    }
    assert required <= by_id.keys()
    # The H3 eye/brow/gaze clips are clean as authored full frames, but their
    # identities are not registered tightly enough to composite over another
    # H3 expression. Keep the real motion instead of synthesizing doubled eyes.
    assert all(
        by_id[name].get("layer", "full_frame") == "full_frame"
        for name in ("blink_double", "brows_both_raise", "gaze_left_strong")
    )
    assert not any(
        item.get("layer") == "upper_face_roi" for item in by_id.values()
    )
    assert all(
        by_id[name].get("layer", "full_frame") == "full_frame"
        for name in ("talk_soft", "talk_normal", "talk_expressive", "talk_happy", "talk_serious")
    )
    assert all(
        "delta_blend" not in by_id[name]["flags"]
        for name in ("talk_soft", "talk_normal", "talk_expressive", "talk_happy", "talk_serious")
    )


def test_full_frame_motion_metadata_tracks_roi_without_locking_authored_motion() -> None:
    identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    current = ((1.0, 0.0, -10.0), (0.0, 1.0, 5.0))

    relative = _relative_face_transform(identity, current)
    assert relative == (10.0, -5.0, 0.0, 1.0)
    assert decode_face_transform(encode_face_transform(*relative)) == relative


def test_curated_return_paths_end_at_a_neutral_source_anchor() -> None:
    desktop = _json(MANIFEST_ROOT / "ailen_default_desktop.json")
    by_id = {sequence["id"]: sequence for sequence in desktop["sequences"]}
    reversed_returns = {
        "confused",
        "sad",
        "skeptical",
        "worried",
        "smile_soft",
        "displeased",
        "surprised_soft",
        "happy_soft",
        "smile_big",
        "anger_moderate",
        "sadness_soft",
        "surprised_strong",
        "displeased_strong",
        "wink_left_smile",
        "wink_right_smile",
    }
    for sequence_id in reversed_returns:
        references = _expand_source_frames(by_id[sequence_id])
        assert references[-1] == references[0]

    assert _expand_source_frames(by_id["excited"])[-1] == (49, 2)
    assert _expand_source_frames(by_id["laugh_hard"])[-1] == (49, 2)
