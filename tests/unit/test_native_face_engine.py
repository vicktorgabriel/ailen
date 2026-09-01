"""Native FacePack engine ABI, scheduling, composition, and hot-pack tests."""

from __future__ import annotations

import base64
import binascii
import concurrent.futures
import ctypes
import shutil
import struct
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ailen.ai.context import AiContextBuilder
from ailen.ai.fake import FakeAiBackend
from ailen.ai.orchestrator import AiOrchestrator
from ailen.ai.router import RuleBasedRouter
from ailen.audio.contracts import SpeechOutput, SpeechRequest
from ailen.audio.coordinator import AudioInteractionCoordinator
from ailen.audio.fake import FakeAudioOutputBackend
from ailen.core.config import AILENConfig
from ailen.core.conversation import ConversationCoordinator
from ailen.domain.enums import AssistantState, DeviceProfile
from ailen.face.native_controller import NativeFaceController
from ailen.face.native_engine import (
    NativeFaceEngine,
    NativeFaceEngineError,
    NativeFaceResult,
    NativeSequencePolicy,
    resolve_facepack_path,
)
from ailen.runtime.factory import LabComponentFactory
from ailen.tools.builtin.face_expression import FaceExpressionTool
from tools.facepack.facepack_format import (
    HEADER_STRUCT,
    EncodedFrame,
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

REPO_ROOT = Path(__file__).resolve().parents[2]
JPEG_DARK = base64.b64decode(
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
    "xcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD8"
    "/wCiiivMPQP/2Q=="
)
JPEG_LIGHT = base64.b64decode(
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
    "xcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDd"
    "ooor8nP3M//Z"
)
JPEG_MOUTH = base64.b64decode(
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
    "xcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDw"
    "Siiiv6zIP//Z"
)
JPEG_GRADIENT = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
    "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/2wBDAQEB"
    "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
    "AQEBAQEBAQEBAQEBAQEBAQH/wAARCAAEAAQDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQ"
    "EAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIh"
    "MUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0"
    "RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKj"
    "pKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09f"
    "b3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQD"
    "BAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNO"
    "El8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6"
    "goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1d"
    "bX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDuPgX/AMEvf2Ov+Fc6"
    "N/xbgHBcczWP/PKD/qGUUUV+l+DPiL4g/wDEJ/Dn/jO+Mv8AkjuH/wDmp87/AOhdhP"
    "8AqOPe4WzzOv8AVzI/+FjNP+RXgv8AmYYv/nxD/p8f/9k="
)


def _frame(jpeg: bytes, index: int = 0) -> EncodedFrame:
    return EncodedFrame(jpeg, 4, 4, index * 100)


def _spec(
    *,
    extra_expression: str | None = None,
    neutral_jpeg: bytes = JPEG_DARK,
) -> FacePackSpec:
    dark = _frame(neutral_jpeg)
    light = _frame(JPEG_LIGHT)
    sequences = [
        SequenceSpec(
            "neutral",
            SequenceCategory.STATE,
            SequenceLayer.FULL_FRAME,
            (dark,),
            1,
            flags=(
                SequenceFlags.INTERRUPTIBLE
                | SequenceFlags.SPEECH_COMPATIBLE
                | SequenceFlags.GAZE_COMPATIBLE
            ),
            speech_style=SpeechStyle.NORMAL,
        ),
        SequenceSpec(
            "blink",
            SequenceCategory.MICROACTION,
            SequenceLayer.FULL_FRAME,
            (dark, light, dark),
            10,
            flags=SequenceFlags.INTERRUPTIBLE | SequenceFlags.RETURNS_TO_BASE,
            peak_anchor=1,
            hold_start_anchor=1,
            hold_end_anchor=1,
            exit_anchor=2,
            cooldown_ms=200,
        ),
        SequenceSpec(
            "happy",
            SequenceCategory.EMOTION,
            SequenceLayer.FULL_FRAME,
            (dark, light, dark),
            10,
            flags=(
                SequenceFlags.INTERRUPTIBLE
                | SequenceFlags.SPEECH_COMPATIBLE
                | SequenceFlags.GAZE_COMPATIBLE
                | SequenceFlags.CONVERSATIONAL
            ),
            priority=20,
            peak_anchor=1,
            hold_start_anchor=1,
            hold_end_anchor=1,
            exit_anchor=2,
            speech_style=SpeechStyle.HAPPY,
        ),
        SequenceSpec(
            "locked",
            SequenceCategory.INTENSE_EMOTION,
            SequenceLayer.FULL_FRAME,
            (light, dark),
            10,
            flags=SequenceFlags.SPEECH_COMPATIBLE | SequenceFlags.EXPLICIT_ONLY,
            priority=30,
            peak_anchor=1,
            hold_start_anchor=1,
            hold_end_anchor=1,
            exit_anchor=1,
        ),
        SequenceSpec(
            "talk_soft",
            SequenceCategory.SPEECH,
            SequenceLayer.MOUTH_ROI,
            (_frame(JPEG_MOUTH),),
            12,
            flags=SequenceFlags.LOOPABLE | SequenceFlags.INTERRUPTIBLE,
            roi=(0, 0, 4, 4),
            speech_style=SpeechStyle.SOFT,
        ),
        SequenceSpec(
            "gaze_left",
            SequenceCategory.MICROACTION,
            SequenceLayer.UPPER_FACE_ROI,
            (_frame(JPEG_DARK), _frame(JPEG_LIGHT, 1)),
            10,
            flags=(
                SequenceFlags.INTERRUPTIBLE
                | SequenceFlags.RETURNS_TO_BASE
                | SequenceFlags.GAZE_LEFT
                | SequenceFlags.DELTA_BLEND
            ),
            intensity=0.8,
            roi=(0, 0, 4, 4),
            peak_anchor=1,
            hold_start_anchor=1,
            hold_end_anchor=1,
            exit_anchor=1,
        ),
        SequenceSpec(
            "talk_normal",
            SequenceCategory.SPEECH,
            SequenceLayer.MOUTH_ROI,
            (_frame(JPEG_DARK),),
            12,
            flags=SequenceFlags.LOOPABLE | SequenceFlags.INTERRUPTIBLE,
            roi=(0, 0, 4, 4),
            speech_style=SpeechStyle.NORMAL,
        ),
        SequenceSpec(
            "talk_happy",
            SequenceCategory.SPEECH,
            SequenceLayer.MOUTH_ROI,
            (_frame(JPEG_MOUTH),),
            12,
            flags=SequenceFlags.LOOPABLE | SequenceFlags.INTERRUPTIBLE,
            roi=(0, 0, 4, 4),
            speech_style=SpeechStyle.HAPPY,
        ),
        SequenceSpec(
            "timed",
            SequenceCategory.EMOTION,
            SequenceLayer.FULL_FRAME,
            (dark, light, dark),
            10,
            flags=(
                SequenceFlags.INTERRUPTIBLE
                | SequenceFlags.SPEECH_COMPATIBLE
                | SequenceFlags.CONVERSATIONAL
            ),
            priority=10,
            peak_anchor=1,
            hold_start_anchor=1,
            hold_end_anchor=1,
            exit_anchor=2,
            transition_in_ms=200,
            transition_out_ms=300,
            return_state="listening",
            speech_style=SpeechStyle.SERIOUS,
        ),
        SequenceSpec(
            "listening_base",
            SequenceCategory.STATE,
            SequenceLayer.FULL_FRAME,
            (light,),
            1,
            flags=(
                SequenceFlags.INTERRUPTIBLE
                | SequenceFlags.SPEECH_COMPATIBLE
                | SequenceFlags.GAZE_COMPATIBLE
            ),
            speech_style=SpeechStyle.NORMAL,
        ),
    ]
    if extra_expression:
        sequences.append(
            SequenceSpec(
                extra_expression,
                SequenceCategory.EMOTION,
                SequenceLayer.FULL_FRAME,
                (light,),
                1,
                flags=(
                    SequenceFlags.INTERRUPTIBLE
                    | SequenceFlags.SPEECH_COMPATIBLE
                    | SequenceFlags.CONVERSATIONAL
                ),
            )
        )
    return FacePackSpec(
        "native.test",
        "0.1",
        4,
        4,
        tuple(sequences),
        (
            StateSpec(
                "idle",
                "neutral",
                (StateActionSpec("blink", 1.0, 200),),
                wait_min_ms=50,
                wait_max_ms=120,
            ),
            StateSpec("listening", "listening_base", wait_min_ms=5000, wait_max_ms=5000),
        ),
    )


@pytest.fixture(scope="session")
def native_library(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if sys.platform != "linux" or shutil.which("c++") is None:
        pytest.skip("native Linux C++ compiler is unavailable")
    output = tmp_path_factory.mktemp("native-face") / "libailen_face_engine.so"
    command = [
        "c++",
        "-std=c++17",
        "-O0",
        "-fPIC",
        "-shared",
        f"-I{REPO_ROOT / 'native/face_engine/include'}",
        str(REPO_ROOT / "native/face_engine/src/face_engine.cpp"),
        "-ljpeg",
        "-o",
        str(output),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        pytest.skip(f"native face build unavailable: {completed.stderr[-500:]}")
    return output


def _build(tmp_path: Path, name: str = "pack.facepack", *, extra: str | None = None) -> Path:
    path = tmp_path / name
    build_facepack(_spec(extra_expression=extra), path)
    return path


def _downgrade_policy_metadata(pack: Path, minor: int) -> None:
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


class _VisibleNativeFace:
    """Visible test adapter that preserves the real native engine underneath."""

    def __init__(self, controller: NativeFaceController) -> None:
        self.controller = controller
        self.calls: list[tuple[object, ...]] = []

    @property
    def available_expressions(self) -> tuple[str, ...]:
        return self.controller.available_expressions

    @property
    def conversational_expressions(self) -> tuple[str, ...]:
        return self.controller.conversational_expressions

    def is_display_active(self) -> bool:
        return True

    def set_state(self, state: AssistantState) -> None:
        self.calls.append(("state", state))
        self.controller.set_state(state)

    def set_gaze(self, x: float, y: float) -> None:
        self.calls.append(("gaze", x, y))
        self.controller.set_gaze(x, y)

    def set_speech_level(self, level: float) -> None:
        self.calls.append(("speech", level))
        self.controller.set_speech_level(level)

    def set_expression(self, expression: str, duration_seconds: float = 0.0) -> None:
        self.calls.append(("expression", expression, duration_seconds))
        self.controller.set_expression(expression, duration_seconds)

    def sleep(self) -> None:
        self.set_state(AssistantState.SLEEP)

    def wake(self) -> None:
        self.set_state(AssistantState.IDLE)


class _ObservedTts:
    def __init__(self) -> None:
        self.requests: list[SpeechRequest] = []

    def synthesize(self, request: SpeechRequest) -> SpeechOutput:
        self.requests.append(request)
        sample = (5000).to_bytes(2, byteorder="little", signed=True)
        return SpeechOutput(
            audio_data=sample * 1600,
            sample_rate=16_000,
            channels=1,
            duration_ms=100.0,
            latency_ms=1.0,
        )


class _ObservedOutput(FakeAudioOutputBackend):
    def play(self, *args: object, **kwargs: object) -> None:
        time.sleep(0.04)
        super().play(*args, **kwargs)  # type: ignore[arg-type]


def test_native_engine_lists_pack_expressions_and_rejects_missing_ids(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path)
    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack, allowed_root=tmp_path)
        assert engine.pack_id == "native.test"
        assert engine.width == 4
        assert engine.expressions == ("happy", "locked", "timed")
        assert engine.conversational_expressions == ("happy", "timed")
        catalog = {sequence.id: sequence for sequence in engine.sequence_catalog}
        assert catalog["happy"].affect_policy == NativeSequencePolicy.CONVERSATIONAL
        assert catalog["locked"].affect_policy == NativeSequencePolicy.EXPLICIT_ONLY
        assert engine.states == ("idle", "listening")
        assert engine.has_expression("happy") is True
        assert engine.has_expression("missing") is False
        with pytest.raises(NativeFaceEngineError, match="unknown FacePack expression"):
            engine.trigger_expression("missing")
        with pytest.raises(NativeFaceEngineError, match="unknown FacePack state"):
            engine.set_state("missing")


def test_expression_transitions_back_and_noninterruptible_expression_blocks_replacement(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path)
    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack, allowed_root=tmp_path)
        engine.trigger_expression("happy")
        engine.update(100)
        assert engine.current_sequence == "happy"
        engine.update(250)
        assert engine.current_sequence == "neutral"

        engine.trigger_expression("locked")
        with pytest.raises(NativeFaceEngineError) as error:
            engine.trigger_expression("happy")
        assert error.value.result == NativeFaceResult.BUSY


def test_speech_layer_does_not_replace_active_emotion(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path)
    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack, allowed_root=tmp_path)
        engine.trigger_expression("happy", 1.0)
        engine.update(100)
        without_speech = engine.frame_rgb()
        engine.set_speech_level(1.0)
        engine.update(1)
        with_speech = engine.frame_rgb()

        assert engine.current_sequence == "happy"
        assert with_speech != without_speech


def test_facepack_1_4_tracks_mouth_roi_with_full_frame_motion(
    native_library: Path,
    tmp_path: Path,
) -> None:
    spec = _spec()
    transform = encode_face_transform(1.0, 0.0, 0.0, 1.0)
    tracked_neutral = replace(
        spec.sequences[0],
        frames=(replace(spec.sequences[0].frames[0], flags=transform),),
    )
    identity_pack = tmp_path / "identity.facepack"
    tracked_pack = tmp_path / "tracked.facepack"
    build_facepack(spec, identity_pack)
    build_facepack(
        replace(spec, sequences=(tracked_neutral, *spec.sequences[1:])),
        tracked_pack,
    )

    rendered: list[bytes] = []
    for pack in (identity_pack, tracked_pack):
        with NativeFaceEngine(native_library) as engine:
            engine.load_pack(pack, allowed_root=tmp_path)
            engine.set_state("idle")
            engine.set_viseme("talk_soft")
            engine.set_speech_level(1.0)
            engine.update(1)
            rendered.append(engine.frame_rgb())

    assert rendered[0] != rendered[1]


def test_facepack_1_5_softens_replacement_roi_across_the_short_axis(
    native_library: Path,
    tmp_path: Path,
) -> None:
    current_pack = tmp_path / "soft-replacement.facepack"
    legacy_pack = tmp_path / "narrow-replacement.facepack"
    build_facepack(_spec(), current_pack)
    legacy_bytes = bytearray(current_pack.read_bytes())
    struct.pack_into("<H", legacy_bytes, 10, 4)
    legacy_pack.write_bytes(legacy_bytes)

    rendered: list[bytes] = []
    for pack in (legacy_pack, current_pack):
        with NativeFaceEngine(native_library) as engine:
            engine.load_pack(pack, allowed_root=tmp_path)
            engine.set_state("idle")
            engine.set_viseme("talk_soft")
            engine.set_speech_level(1.0)
            engine.update(1)
            rendered.append(engine.frame_rgb())

    assert rendered[0] != rendered[1]


def test_upper_face_gaze_composes_over_compatible_emotion_only(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path)
    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack, allowed_root=tmp_path)
        engine.trigger_expression("happy", 1.0)
        engine.update(100)
        without_gaze = engine.frame_rgb()
        engine.set_gaze(-0.9, 0.0)
        engine.update(0)
        with_gaze = engine.frame_rgb()

        assert engine.current_sequence == "happy"
        assert with_gaze != without_gaze

        engine.trigger_expression("locked")
        engine.update(0)
        locked = engine.frame_rgb()
        engine.set_gaze(-0.9, 0.0)
        engine.update(0)
        assert engine.frame_rgb() == locked


def test_diagnostic_microaction_uses_real_upper_face_composition(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path)
    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack, allowed_root=tmp_path)
        engine.trigger_expression("happy", 1.0)
        engine.update(50)
        base = engine.frame_rgb()

        engine.trigger_microaction("gaze_left")
        engine.update(100)

        assert engine.current_sequence == "happy"
        assert engine.frame_rgb() != base


def test_pack_transition_metadata_controls_real_playback_duration(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path)
    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack, allowed_root=tmp_path)
        engine.trigger_expression("timed")
        engine.update(599)
        assert engine.current_sequence == "timed"
        engine.update(1)
        assert engine.current_sequence == "neutral"

        engine.set_state("listening")
        engine.trigger_expression("timed")
        engine.update(600)
        assert engine.current_sequence == "listening_base"


def test_expression_priority_blocks_lower_priority_replacement(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path)
    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack, allowed_root=tmp_path)
        engine.trigger_expression("happy")
        with pytest.raises(NativeFaceEngineError) as error:
            engine.trigger_expression("timed")
        assert error.value.result == NativeFaceResult.BUSY


def test_pack_declared_speech_style_selects_mouth_without_becoming_emotion(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path)
    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack, allowed_root=tmp_path)
        engine.trigger_expression("happy", 1.0)
        engine.update(100)
        engine.set_speech_level(0.8)
        engine.update(0)
        automatic_happy_mouth = engine.frame_rgb()
        engine.set_viseme("talk_normal")
        engine.update(0)
        explicit_normal_mouth = engine.frame_rgb()

        assert engine.current_sequence == "happy"
        assert automatic_happy_mouth != explicit_normal_mouth


def test_idle_scheduler_is_deterministic_with_seed(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path)
    traces: list[list[str]] = []
    for _ in range(2):
        with NativeFaceEngine(native_library) as engine:
            engine.load_pack(pack, allowed_root=tmp_path)
            engine.set_random_seed(123456)
            engine.set_state("idle")
            trace = []
            for delta in (20, 40, 40, 100, 100, 100, 200):
                engine.update(delta)
                trace.append(engine.current_sequence)
            traces.append(trace)
    assert traces[0] == traces[1]
    assert "blink" in traces[0]


def test_pack_can_be_loaded_unloaded_repeatedly(native_library: Path, tmp_path: Path) -> None:
    pack = _build(tmp_path)
    with NativeFaceEngine(native_library) as engine:
        for _ in range(5):
            engine.load_pack(pack, allowed_root=tmp_path)
            assert len(engine.frame_rgb()) == 4 * 4 * 3
            engine.unload_pack()


def test_native_handle_serializes_concurrent_updates(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path)
    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack, allowed_root=tmp_path)

        def exercise(worker: int) -> None:
            for step in range(50):
                engine.set_speech_level((step % 10) / 10.0)
                engine.set_gaze(-0.9 if (worker + step) % 2 else 0.0, 0.0)
                engine.update(1)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(exercise, worker) for worker in range(4)]
            for future in futures:
                future.result()

        assert len(engine.frame_rgb()) == 4 * 4 * 3


def test_legacy_raw_frame_pointer_is_a_stable_thread_local_snapshot(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path)
    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack, allowed_root=tmp_path)
        library = engine._library
        handle = engine._native_handle
        library.ailen_face_get_frame.argtypes = [ctypes.c_void_p]
        library.ailen_face_get_frame.restype = ctypes.POINTER(ctypes.c_ubyte)
        pointer = library.ailen_face_get_frame(handle)
        snapshot = ctypes.string_at(pointer, engine.width * engine.height * 3)

        engine.trigger_expression("happy")
        engine.update(100)

        assert ctypes.string_at(pointer, len(snapshot)) == snapshot
        assert engine.frame_rgb() != snapshot


def test_native_bilinear_presentation_copy_is_bounded_and_not_nearest_neighbor(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = tmp_path / "gradient.facepack"
    build_facepack(_spec(neutral_jpeg=JPEG_GRADIENT), pack)

    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack, allowed_root=tmp_path)
        source = engine.frame_rgb()
        scaled = engine.frame_rgb_scaled(9, 9)

        assert len(scaled) == 9 * 9 * 3
        assert len({scaled[index : index + 3] for index in range(0, len(scaled), 3)}) > len(
            {source[index : index + 3] for index in range(0, len(source), 3)}
        )
        with pytest.raises(NativeFaceEngineError, match="dimensions"):
            engine.frame_rgb_scaled(0, 9)

        tiny = (ctypes.c_ubyte * 1)()
        result = engine._library.ailen_face_copy_frame_scaled(
            engine._native_handle,
            tiny,
            1,
            9,
            9,
            27,
        )
        assert result == NativeFaceResult.INVALID_ARGUMENT


def test_scaled_frame_copy_serializes_python_buffers_across_threads(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path)
    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack, allowed_root=tmp_path)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            frames = list(pool.map(lambda _: engine.frame_rgb_scaled(32, 32), range(20)))

        assert all(frame == frames[0] for frame in frames)


def test_native_engine_loads_format_1_0_pack_with_same_binary(
    native_library: Path,
    tmp_path: Path,
) -> None:
    v10_spec = _spec()
    v10_spec = FacePackSpec(
        **{
            **v10_spec.__dict__,
            "sequences": tuple(
                SequenceSpec(
                    **{
                        **sequence.__dict__,
                        "speech_style": SpeechStyle.AUTOMATIC,
                        "flags": sequence.flags & ~SequenceFlags.DELTA_BLEND,
                    }
                )
                for sequence in v10_spec.sequences
            ),
        }
    )
    pack = tmp_path / "format-1-0.facepack"
    build_facepack(v10_spec, pack)
    data = bytearray(pack.read_bytes())
    struct.pack_into("<H", data, 10, 0)
    pack.write_bytes(data)
    _downgrade_policy_metadata(pack, 0)

    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack, allowed_root=tmp_path)
        assert engine.pack_id == "native.test"
        assert engine.conversational_expressions == ()


def test_native_engine_loads_format_1_2_pack_with_no_affect_policy(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path, "format-1-2.facepack")
    _downgrade_policy_metadata(pack, 2)

    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack, allowed_root=tmp_path)
        assert engine.expressions == ("happy", "locked", "timed")
        assert engine.conversational_expressions == ()


def test_malformed_jpeg_fails_cleanly_without_crossing_c_abi(
    native_library: Path,
    tmp_path: Path,
) -> None:
    spec = _spec()
    malformed = EncodedFrame(b"\xff\xd8broken-jpeg\xff\xd9", 4, 4, 0)
    broken_happy = SequenceSpec(
        **{
            **spec.sequences[2].__dict__,
            "frames": (malformed, malformed, malformed),
        }
    )
    broken_spec = FacePackSpec(
        **{
            **spec.__dict__,
            "sequences": (*spec.sequences[:2], broken_happy, *spec.sequences[3:]),
        }
    )
    pack = tmp_path / "malformed-jpeg.facepack"
    build_facepack(broken_spec, pack)

    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack, allowed_root=tmp_path)
        engine.trigger_expression("happy")
        with pytest.raises(NativeFaceEngineError) as error:
            engine.update(0)
        assert error.value.result == NativeFaceResult.DECODE_ERROR


def test_new_expression_appears_in_pack_b_without_recompiling_engine(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack_a = _build(tmp_path, "a.facepack")
    pack_b = _build(tmp_path, "b.facepack", extra="embarrassed")
    library_identity = (native_library.stat().st_mtime_ns, native_library.stat().st_size)

    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack_a, allowed_root=tmp_path)
        assert "embarrassed" not in engine.expressions
        assert "embarrassed" not in engine.conversational_expressions
        engine.load_pack(pack_b, allowed_root=tmp_path)
        assert "embarrassed" in engine.expressions
        assert "embarrassed" in engine.conversational_expressions
        assert engine.has_expression("embarrassed") is True

    assert (native_library.stat().st_mtime_ns, native_library.stat().st_size) == library_identity

    controller = NativeFaceController(
        library_path=native_library,
        facepack_path=pack_b,
        allowed_facepack_root=tmp_path,
    )
    try:
        tool = FaceExpressionTool(controller)
        assert "embarrassed" in tool.schema["properties"]["expression"]["enum"]
        face = _VisibleNativeFace(controller)
        backend = FakeAiBackend(canned_response="Una respuesta breve.")
        backend.generate = MagicMock(side_effect=backend.generate)
        audio = MagicMock()
        audio.last_speech_interrupted = False
        coordinator = ConversationCoordinator(
            context_builder=AiContextBuilder(),
            router=RuleBasedRouter(),
            orchestrator=AiOrchestrator(backends={"local": backend}),
            audio_coordinator=audio,
            face_controller=face,
            profile=DeviceProfile.LOCAL,
        )

        coordinator.handle_user_input("Contame algo breve")
        request = backend.generate.call_args.args[0]

        assert "embarrassed" in coordinator.conversational_expressions
        assert "embarrassed" in request.system_context
    finally:
        controller.close()


def test_conversation_uses_pack_policy_then_overlays_real_speech_without_erasing_affect(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path)
    controller = NativeFaceController(
        library_path=native_library,
        facepack_path=pack,
        allowed_facepack_root=tmp_path,
    )
    face = _VisibleNativeFace(controller)
    tts = _ObservedTts()
    audio = AudioInteractionCoordinator(
        tts=tts,
        audio_output=_ObservedOutput(),
        face_controller=face,
    )
    backend = FakeAiBackend(canned_response="[[face:happy]] Qué bueno.")
    backend.generate = MagicMock(side_effect=backend.generate)
    coordinator = ConversationCoordinator(
        context_builder=AiContextBuilder(),
        router=RuleBasedRouter(),
        orchestrator=AiOrchestrator(backends={"local": backend}),
        audio_coordinator=audio,
        face_controller=face,
        profile=DeviceProfile.LOCAL,
    )

    try:
        response, _plan = coordinator.handle_user_input("Contame algo lindo")
        request = backend.generate.call_args.args[0]
        controller.engine.update(1)

        assert coordinator.conversational_expressions == ("happy", "timed")
        assert "Permitidas: happy, timed" in request.system_context
        assert "locked" not in request.system_context
        assert response.text == "Qué bueno."
        assert tts.requests[-1].text == "Qué bueno."
        assert tts.requests[-1].emotion == "happy"
        assert ("expression", "happy", 0.0) in face.calls
        assert any(call[0] == "speech" and float(call[1]) > 0.0 for call in face.calls)
        assert controller.engine.current_sequence == "happy"

        controller.set_expression("neutral")
        face.calls.clear()
        backend._canned_response = "[[face:locked]] No corresponde."
        response, _plan = coordinator.handle_user_input("Probá una reacción bloqueada")

        assert response.text == "No corresponde."
        assert tts.requests[-1].text == "No corresponde."
        assert tts.requests[-1].emotion == "neutral"
        assert all(call[:2] != ("expression", "locked") for call in face.calls)
    finally:
        controller.close()


def test_facepack_path_cannot_escape_trusted_root(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = _build(tmp_path, "outside.facepack")
    with pytest.raises(NativeFaceEngineError, match="escapes"):
        resolve_facepack_path(outside, allowed_root=trusted)


def test_native_engine_rejects_corrupt_and_out_of_range_packs(
    native_library: Path,
    tmp_path: Path,
) -> None:
    corrupt = _build(tmp_path, "corrupt.facepack")
    corrupt_data = bytearray(corrupt.read_bytes())
    corrupt_data[-1] ^= 0x55
    corrupt.write_bytes(corrupt_data)

    offset_pack = _build(tmp_path, "offset.facepack")
    offset_data = bytearray(offset_pack.read_bytes())
    header = list(HEADER_STRUCT.unpack_from(offset_data))
    sequence_offset = int(header[13])
    frame_offset = int(header[15])
    payload_offset = int(header[23])
    file_size = int(header[25])
    struct.pack_into("<Q", offset_data, frame_offset + 24, file_size + 1)
    header[26] = binascii.crc32(offset_data[sequence_offset:payload_offset]) & 0xFFFFFFFF
    offset_data[: HEADER_STRUCT.size] = HEADER_STRUCT.pack(*header)
    offset_pack.write_bytes(offset_data)

    with NativeFaceEngine(native_library) as engine:
        with pytest.raises(NativeFaceEngineError) as corrupt_error:
            engine.load_pack(corrupt, allowed_root=tmp_path)
        assert corrupt_error.value.result == NativeFaceResult.INVALID_PACK
        with pytest.raises(NativeFaceEngineError) as offset_error:
            engine.load_pack(offset_pack, allowed_root=tmp_path)
        assert offset_error.value.result == NativeFaceResult.INVALID_PACK


def test_facepack_1_6_full_frame_speech_is_cleanly_selected_and_pre_1_6_rejected(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path, "full-frame-speech.facepack")
    data = bytearray(pack.read_bytes())
    header = list(HEADER_STRUCT.unpack_from(data))
    sequence_offset = int(header[13])
    payload_offset = int(header[23])
    talk_sequence_index = 4
    sequence_record_size = 112
    layer_field_offset = 20
    struct.pack_into(
        "<I",
        data,
        sequence_offset + talk_sequence_index * sequence_record_size + layer_field_offset,
        int(SequenceLayer.FULL_FRAME),
    )
    header[26] = binascii.crc32(data[sequence_offset:payload_offset]) & 0xFFFFFFFF
    data[: HEADER_STRUCT.size] = HEADER_STRUCT.pack(*header)
    pack.write_bytes(data)

    with NativeFaceEngine(native_library) as engine:
        engine.load_pack(pack, allowed_root=tmp_path)
        engine.set_state("idle")
        engine.trigger_expression("happy", 1.0)
        engine.set_viseme("talk_soft")
        engine.set_speech_level(1.0)
        engine.update(1)
        assert engine.current_sequence == "talk_soft"
        assert "talk_soft" not in engine.expressions
        engine.set_speech_level(0.0)
        engine.update(0)
        assert engine.current_sequence == "happy"

    legacy = tmp_path / "pre-1.6-full-frame-speech.facepack"
    legacy_data = bytearray(data)
    struct.pack_into("<H", legacy_data, 10, 5)
    legacy.write_bytes(legacy_data)
    with (
        NativeFaceEngine(native_library) as engine,
        pytest.raises(NativeFaceEngineError) as error,
    ):
        engine.load_pack(legacy, allowed_root=tmp_path)
    assert error.value.result == NativeFaceResult.INVALID_PACK


def test_native_controller_default_expression_duration_uses_pack_timing(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path)
    controller = NativeFaceController(
        library_path=native_library,
        facepack_path=pack,
        allowed_facepack_root=tmp_path,
        engine=NativeFaceEngine(native_library),
    )
    try:
        controller.set_expression("happy")
        controller.engine.update(100)
        assert controller.engine.current_sequence == "happy"
        controller.engine.update(250)
        assert controller.engine.current_sequence == "neutral"
    finally:
        controller.close()


def test_speaking_state_preserves_expression_in_native_controller(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path)
    controller = NativeFaceController(
        library_path=native_library,
        facepack_path=pack,
        allowed_facepack_root=tmp_path,
        engine=NativeFaceEngine(native_library),
    )
    try:
        assert controller.available_expressions[:2] == ("neutral", "happy")
        controller.set_expression("happy", 1.0)
        controller.engine.update(100)
        controller.set_state(AssistantState.SPEAKING)
        controller.set_speech_level(0.8)
        controller.engine.update(50)
        assert controller.engine.current_sequence == "happy"
    finally:
        controller.close()


def test_factory_disables_face_when_facepack_is_corrupt(
    native_library: Path,
    tmp_path: Path,
) -> None:
    pack = _build(tmp_path)
    data = bytearray(pack.read_bytes())
    data[-1] ^= 0x55
    pack.write_bytes(data)
    config = AILENConfig()
    config.display.face_style = "facepack"
    config.display.face_engine_library = str(native_library)
    config.display.facepack_path = str(pack)
    config.display.facepack_root = str(tmp_path)

    controller, status = LabComponentFactory(config).build_face()

    assert controller.__class__.__name__ == "NullFaceController"
    assert status.state == "DEGRADED"
    assert status.backend == "NullFaceController"
    assert "checksum" in status.detail
