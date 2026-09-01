# ADR-012 — Native FacePack engine and external animation packs

**Status:** Accepted for R5B desktop laboratory implementation  
**Date:** 2026-08-30  
**Logical/config default:** `facepack`; failure degrades to headless, never to `portrait`

## Context

The H3 corpus contains realistic facial motion, but playing MP4 files in the
product would couple runtime quality, latency, codecs, looping seams, and facial
semantics to source videos. It would also make speaking a full-face clip instead
of an independent mouth signal and would require replacing/rebuilding code every
time an expression changes.

AILEN Core must remain the authority for state, permissions, and bounded
expression intent. A renderer may receive only normalized state, expression,
gaze, speech level, and later viseme commands. It must not access AI, memory,
tools, camera frames, audio buffers, or private configuration.

## Decision

1. The renderer is a C++17 shared library with a small C ABI:
   `libailen_face_engine.so` on Linux and `ailen_face_engine.dll` on Windows.
   C++ classes never cross the ABI.
2. Animations live in a separate, versioned `.facepack` artifact. Adding or
   replacing an expression rebuilds only the pack, not the engine or Core.
3. H3 MP4 and OpenCV/YuNet are compilation inputs only. Runtime never opens,
   seeks, or decodes MP4 and does not depend on FFmpeg/OpenCV.
4. FacePack v1 stores fixed tables plus individually checksummed JPEG frames.
   Runtime dependency is only libjpeg. The engine reads metadata once and seeks
   to the current compressed frame; it does not load the complete payload.
5. Persistent states are a static base plus bounded, weighted microactions with
   variable wait intervals and per-action cooldown. An optional deterministic
   xorshift seed makes schedules reproducible in tests. A complete five-second
   idle/listening clip is never looped.
6. FacePack keeps state, emotion, microaction and speech as distinct semantics.
   Formats 1.2–1.5 support tracked upper/mouth ROI, but physical QA proved the
   current H3 clips are not identity-compatible layers: eyes and lips deform
   when transplanted even with correct pose and feathering. Format 1.6 therefore
   also permits pack-selected full-frame speech. The current pack uses authored
   full frames for all eye/brow/gaze/talk motion, retains Core's affect while
   speech is visible, and resumes it when speech stops. ROI remains available
   only for future assets actually produced as composable layers.
7. Python uses a small `ctypes` wrapper. The native adapter implements the
   existing `FaceController`; Core is not rewritten around the library. Its
   bounded dynamic expression list feeds the controlled tool schema and
   conversational affect validation, so a new pack id needs no duplicate Core
   renderer list.
8. Pack/library failure is fail-clean: a missing, corrupt, incompatible, or
   unsafe-path FacePack degrades to headless face operation. Fatal native
   failures detected after startup also request failover through a stable wrapper so
   Core/Audio/Vision/Tools keep the same controller reference. `pixel` remains
   available for very constrained displays.
9. Renderer-native expression timing uses `duration_seconds=0`: FacePack follows its curated natural sequence length unless a caller explicitly requests a longer minimum hold. Legacy portrait maps 0 to its established default.
10. `facepack` is the configuration default. Missing/corrupt/incompatible native
   artifacts disable the graphical face and retain a stable headless controller.
   `portrait`, `vector`, and `pixel` are manual choices only. Neither the shared
   library nor generated FacePack is included in Python package data; release
   packaging remains a separate measured decision.
11. Transition durations retime curated anchors, priorities arbitrate transient
   replacement, speech styles select real mouth sequences, and pack-declared
   gaze compatibility controls composition. `return_state` may restart a matching
   visual base timeline but cannot change Core's semantic AssistantState.
12. ABI 1.4 exports are `noexcept`, translate all C++ exceptions to errors, and
   serialize handle operations. Text and legacy raw-frame getters return bounded
   thread-local snapshots. Copy/copy-scaled are the canonical frame APIs and the
   caller must stop all users of a handle before destroying it.
13. A transient whose source has no authored recovery may append the same curated
   real frames in reverse to reach its source entry. Identical JPEG payloads are
   shared in the pack. This avoids both an abrupt expressive-frame-to-neutral cut
   and a crossfade/double face; it does not claim newly generated recovery motion.

## Representation decision

On eight representative H3 clips at 384×384/12 FPS, the measured aggregate was:

| Representation | Bytes |
|---|---:|
| Raw RGB | 208,797,696 |
| zlib full frames | 124,101,639 |
| zlib XOR delta, keyframe interval 12 | 77,582,241 |
| PNG | 92,164,322 |
| RGB565 + zlib | 55,049,978 |
| JPEG quality 90 | 16,305,917 |

JPEG quality 90 measured approximately 36.95 dB average PSNR on the detailed
smile sample. It was chosen for v1 because it is substantially smaller, permits
random access and per-frame corruption isolation, and has a small mature runtime
decoder. Lossless delta chains were rejected for the desktop slice because they
were 4.8× larger and made random access/recovery dependent on earlier frames.

This does not prevent future pack profiles from using another declared encoding.
Such an encoding requires a format-minor/major decision and decoder support; it
must never be silently inferred.

## Integrity and safety

The engine validates magic, format/ABI major, file size, counts, table sizes,
ordered non-overlapping offsets, string ranges, frame/sequence/state references,
dimensions, metadata CRC32, payload CRC32, and per-frame CRC32. V1 bounds files
to 512 MiB, dimensions to 4096 pixels per axis, 4,096 sequences, 200,000 frames,
256 states, and 8,192 state actions.

The Python adapter resolves a `.facepack` under an explicit trusted root. A
symlink or `..` escape is rejected before native load. The path comes from local
configuration, never from an LLM/tool argument.

## Consequences

Positive:

- realistic H3 identity without runtime video playback;
- expressions and content can evolve independently from binaries;
- bounded RAM and low-millisecond frame decode/composition on ASRock;
- speech/emotion semantics remain separate even when the selected visual source
  is full-frame;
- deterministic scheduler and corrupt-pack behavior are testable.

Costs and limits:

- libjpeg and a native build/release artifact must be supplied per platform;
- Windows DLL compilation is designed but not yet physically verified;
- current Tk transport converts RGB to PPM; it remains cheap at idle but costs
  more during 30 FPS speech than the engine alone;
- speech selection is energy/style-driven, not phonemic viseme timing;
- current full-frame speech temporarily hides, but does not erase, the active
  visual emotion; truly simultaneous lips-over-emotion needs new layer-ready H3 assets;
- full-frame head gestures do not layer over a transient full-frame emotion;
- physical QA confirmed clean full-frame blink and speech; a full conversational
  session driven by real PCM and Vision still remains;
- reversed real-frame exits remove hard cuts but an authored non-reversing exit
  for some intense/sleep clips would still require new H3 footage;
- the desktop source is 480×480. Bilinear presentation avoids block pixels but
  cannot create high-frequency detail at 720/1080 output.

## Rejected alternatives

- MP4 playback at runtime: visible loop seams, codec dependency, weak random
  access, and incorrect speech/emotion coupling.
- Thousands of loose PNG files: poor packaging/update ergonomics and much larger
  metadata/filesystem overhead.
- Torch/OpenCV/FFmpeg in the runtime: too heavy for product tiers and unnecessary
  after offline compilation.
- Compiling assets into the DLL: forces a binary rebuild for every emotion and
  violates the engine/FacePack separation requirement.
- Unconditional crossfades or foreign-face ROI patches: they produce
  double-face/skin seams or identity deformation. Tracking and feathering alone
  did not make the H3 clips composable, so v1.6 uses their curated authored full
  frames and reserves ROI for purpose-built layer assets.
