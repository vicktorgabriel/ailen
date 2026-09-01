# ASRock native FacePack benchmark — 2026-08-31

Scope: current ASRock laboratory only. These values do not claim performance on
Banghó, SF20BA, Raspberry Pi, Windows, or an appliance image. The Trading Bot and
other host workloads were not stopped, reniced, or assigned affinity.

## Artifact

- engine: 117,400 bytes, Linux x86-64 shared library, ABI 1.4;
- engine SHA-256: `fbcd48f172fdcf3048d766ec0180a6ea2456f4ef90a3e7f55bd83d807763fe67`;
- pack: 90,247,218 bytes, format 1.6, version 0.7.0;
- pack SHA-256: `71d1787ed02cfb18322790af0dc9fb28af50be0f46db98813e12b6b0a016a909`;
- 480×480 RGB24, 79 sequences, 2,888 logical JPEG Q90 frames, 6 states;
- 39 expressions, 28 microactions and 10 speech sequences;
- identical JPEG payloads in curated reverse paths share storage;
- runtime payload path: JPEG/libjpeg only; MP4/FFmpeg/OpenCV are not used.

## Results

The run used two-second real-time windows and observed load average
13.13 / 14.28 / 13.57 on a 12-logical-CPU host.

| Metric | Result |
|---|---:|
| Shared-library load | 1.267 ms |
| FacePack load + full integrity validation | 181.368 ms |
| RSS delta after pack load | 3,973,120 bytes (3.79 MiB) |
| Idle update + copy average / p95 | 0.261 / 0.364 ms |
| Pack-selected full-frame speech average / p95 | 0.920 / 1.485 ms |
| Expression change + first update | 0.989 ms |
| Frame copy average / p95 | 0.035 / 0.046 ms |
| Tight speech loop | 1,119 FPS synthetic ceiling |
| Engine CPU at real-time idle | 0.841% of one core |
| Engine CPU during speech | 2.560% of one core |

## Presentation scaling

The pack remains 480×480. ABI 1.4 performs bilinear presentation scaling before
Tk uploads the PPM frame; aspect ratio is preserved and the image is centered.

| Window / presented face | Idle CPU | Animation + speech CPU |
|---|---:|---:|
| 800×480 / 480×480 | 3.121% of one core | 16.482% of one core |
| 1280×720 / 720×720 | 3.461% of one core | 27.217% of one core |
| 1920×1080 / 1080×1080 | 3.155% of one core | 42.506% of one core |

On this 12-thread machine those animation figures correspond approximately to
1.42%, 2.28%, and 3.53% of total logical CPU capacity if the scheduler can use
the remaining cores. The one-core scale is the canonical process measurement.
Upscaling removes nearest-neighbour blocks; it cannot recreate detail absent
from the 480×480 source. A genuinely sharper 1080 presentation needs a separate
higher-resolution source/profile and its own hardware benchmark.

Full-frame clips use a fixed source-entry normalization so authored head/body
motion remains real. The current H3 pack intentionally has no ROI layers:
physical QA found cross-clip identity deformation despite correct tracking.
Reverse exits reuse actual frame payloads rather than crossfading or generating
images. An independent rebuild was byte-identical at SHA-256
`71d1787ed02cfb18322790af0dc9fb28af50be0f46db98813e12b6b0a016a909`.

The source JSON is generated locally at
`runtime/facepacks/asrock_facepack_benchmark.json` and is intentionally ignored.
Reproduce with:

```bash
.venv/bin/python -m tools.facepack.benchmark_face_engine \
  --library runtime/native/libailen_face_engine.so \
  --pack runtime/facepacks/ailen_default.facepack \
  --duration-seconds 2 --with-tk \
  --output runtime/facepacks/asrock_facepack_benchmark.json
```
