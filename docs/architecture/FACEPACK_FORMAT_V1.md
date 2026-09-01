# FacePack v1 format and native ABI

This document is normative for format major `1`; the current artifact is format
`1.6` and native ABI `1.4`. All integers are little-endian. Runtime pixels are
RGB24. Generated `.facepack`, `.so`, and `.dll` artifacts stay outside the wheel
and Git working files by default.

## File layout

```text
176-byte header
sequence table        112 bytes/record
frame table            48 bytes/record
state table            48 bytes/record
state-action table     16 bytes/record
UTF-8 string table
8-byte alignment padding
JPEG payloads
```

The header contains `AILENFP\0`, format major/minor, required ABI major, output
dimensions/pixel format, record counts, offset+size for every section, declared
file size, metadata/payload CRC32, and string references for pack id/version.

Sequence records contain:

- dynamic id and return state;
- category: state, microaction, emotion, intense emotion, or speech;
- layer: full frame, mouth ROI, or upper-face ROI;
- loopable, interruptible, speech-compatible, gaze-compatible,
  returns-to-base, pack-declared gaze direction, and delta-blend flags;
- priority, intrinsic intensity, scheduler weight, rational FPS;
- frame range;
- entry/onset/peak/hold-start/hold-end/exit anchors;
- optional ROI;
- transition/cooldown metadata and bounded speech style.

Format 1.2 introduced the first legal compositing split: `speech` used `mouth
ROI`, eye/brow/gaze microactions could use `upper-face ROI`, and
state/emotion/intense emotion stayed full-frame. ROI payloads may carry deltas
centered at 128 instead of absolute skin pixels; runtime applies those signed
changes over the active base with a feather mask. Persistent state bases must be
`state` sequences and scheduler actions must be `microaction` sequences.

Format 1.3 added pack-owned conversational affect policy. Format 1.4 uses the
previously reserved frame flags to store a bounded canonical-to-authored-face
similarity transform for every full-frame frame: signed translation, half-degree
rotation and 1/128 scale steps. ROI layers remain canonical in the pack and the
engine maps them onto the actual head pose before feathered composition. This
prevents an optional layer from remaining at neutral coordinates while the
authored head moves. Format 1.5 broadens the feather of absolute replacement ROI
payloads to remove hard rectangular edges.

Format 1.6 allows `speech` to be either `mouth ROI` or `full frame`. Full-frame
speech exists for corpora such as the current H3 set, where the complete talk
clips are visually clean but their lips/teeth cannot be transplanted onto a
different generated identity without deformation. While speech level is nonzero
the engine renders the pack-selected talk sequence, retains Core's semantic
affect internally, and resumes that affect when speech stops. Speech remains a
distinct category and never becomes an emotion. Writer, standalone inspector
and native loader enforce this rule; pre-1.6 packs cannot declare full-frame
speech.

Compatibility is explicit: the current ABI 1.4 engine accepts packs 1.0 through 1.6; a newer
minor is rejected by an older engine. Pre-1.4 full-frame flags mean identity
placement. Packs before 1.2 cannot claim delta blending, and packs before 1.3
cannot declare conversational affect policy. Packs before 1.6 cannot use
full-frame speech. The writer/inspectors reject
placement metadata on ROI frames and reject reserved/overflowing flag bits.

State records refer to one static base sequence and a range of weighted
microactions. They also define a bounded min/max wait. This produces:

```text
base -> variable wait -> microaction -> base -> variable wait -> ...
```

It does not replay an idle/listening video loop.

A caller duration of `0` means **use the sequence natural timing**. Positive
durations are minimum holds, not replacements for pack FPS/anchors.

Every `return_state` string must name a state in the same pack. Core's currently
selected persistent state remains authoritative after a transient expression.
If the declared return matches that Core-selected state, the engine restarts its
visual state timeline at the base anchor; it never changes Core state on its own.
`transition_in_ms`/`transition_out_ms` retime entry/hold/exit anchors without
crossfade, expression priority blocks lower-priority replacement, and
`gaze_compatible` gates actual upper-face composition.

Speech styles are `automatic`, `soft`, `normal`, `expressive`, `happy`, and
`serious`. They select a real speech sequence using state/affect metadata and
energy. That sequence may be a composable mouth ROI in a compatible future pack
or a clean full-frame talk sequence in the current H3 pack. `set_viseme()`
currently accepts an exact speech-sequence id only; the corpus has no phoneme
ground truth, so the engine does not invent phonetic visemes. The current pack's
eye/brow/gaze actions are likewise full-frame because physical QA rejected
cross-clip upper-face composition; gaze over an arbitrary active emotion is not
claimed for this asset set.

Frame records contain sequence/local index, timestamp, encoding, dimensions,
absolute payload offset/size, decoded size, CRC32, and flags. Individual JPEGs
make a bad frame independently detectable and keep random access bounded.
Identical encoded JPEG payloads may intentionally share an offset; table records,
timing and transforms remain independent while reverse paths avoid duplicating
the same compressed bytes.

## ABI

The public header is
`native/face_engine/include/ailen_face_engine.h`. The stable operations are:

```text
ailen_face_get_abi_version
ailen_face_create / ailen_face_destroy
ailen_face_load_pack / ailen_face_unload_pack
ailen_face_get_pack_id / ailen_face_get_pack_version
ailen_face_get_expression_count / get_expression / has_expression
ailen_face_set_state
ailen_face_trigger_expression / clear_expression / set_intensity
ailen_face_set_speech_level / set_viseme
ailen_face_set_gaze / set_random_seed
ailen_face_update
ailen_face_get_frame / copy_frame / copy_frame_scaled
ailen_face_get_width / height / stride / pixel_format
ailen_face_get_frame_generation / get_current_sequence / get_last_error
```

All owned state is behind opaque `ailen_face_handle`. Every exported C++
function is `noexcept`; exceptions are caught and translated to a bounded error
code/text. Handles serialize operations with a mutex. Text getters copy into a
thread-local bounded buffer, so unloading cannot leave ctypes with a dangling
`std::string` pointer. `ailen_face_copy_frame()` is the canonical safe snapshot;
`ailen_face_copy_frame_scaled()` provides native bilinear presentation scaling
without a runtime image dependency. `ailen_face_get_frame()` remains only for
ABI compatibility and returns a thread-local snapshot valid until the next raw
getter call on that thread. Callers must quiesce every worker using a handle
before `ailen_face_destroy()`; destruction concurrent with any call is outside
the contract.

## Canonical build

Linux/macOS:

```bash
cmake -S native/face_engine -B build/face_engine -DCMAKE_BUILD_TYPE=Release
cmake --build build/face_engine --config Release
```

Windows uses the same CMake project with a C++17 compiler and libjpeg. The ASRock
lab did not have CMake installed, so validation compiled the identical source
directly with `c++ -std=c++17 -O2 -fPIC -shared ... -ljpeg`; this is evidence for
Linux source behavior, not Windows proof.

Build the current desktop pack:

```bash
.venv/bin/python -m tools.facepack.compile_facepack \
  --manifest tools/facepack/manifests/ailen_default_desktop.json \
  --output runtime/facepacks/ailen_default.facepack \
  --report runtime/facepacks/ailen_default.build.json
```

OpenCV and YuNet are needed only for this offline command. The compiler can use
a canonical eyes/nose anchor for optional composable frames and preserves
authored motion for full-frame sequences using one source-entry alignment. The
current desktop manifest emits only full-frame sequences after physical QA;
future compatible manifests may still request aligned ROI extraction.
The compiler trims/deduplicates and emits JPEG payloads.
Curated reverse exits reuse the actual encoded source frames; the runtime does
not crossfade or synthesize an intermediate face. H3 MP4 files remain source
material and are never opened by the native engine.

## Add an expression without rebuilding the engine

1. Inspect the new source visually and add/update its entry in
   `h3_classification.json`.
2. Add a curated sequence to `ailen_default_desktop.json`: source frames,
   category, flags, FPS, anchors, intensity, return state, and transitions.
3. Re-run the pack compiler to a new version/path.
4. Run `inspect_facepack()` and the native load/list tests.
5. Replace the external `.facepack` atomically during a stopped/reload-safe
   maintenance operation.
6. Do not rebuild `libailen_face_engine.so`/`ailen_face_engine.dll` unless the
   format/decoder/ABI itself changes.

The regression test builds Pack A, then Pack B with `embarrassed`, and loads both
through the same unchanged library. Only Pack B lists the new expression.
The native controller then projects that list into `FaceExpressionTool`'s enum;
the controlled Core path accepts `embarrassed` without rebuilding the engine or
editing a second renderer allowlist. Replacement remains a stopped/reload-safe
maintenance operation, not an in-place live mutation of a registered tool.

## Profiles

The logical format supports multiple independently compiled profiles. The
current measured artifact is `desktop-lab`, 480×480 JPEG Q90, 79 sequences and
2,888 logical frames (identical JPEG payloads are shared). A low profile may use lower resolution/quality only after target
hardware measurement. RGB565/JPEG derivatives for future microcontrollers are
not format-v1 runtime claims and need their own decoder and benchmark.
