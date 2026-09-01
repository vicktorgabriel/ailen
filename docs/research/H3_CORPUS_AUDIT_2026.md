# H3 corpus visual audit — 2026-08-30

## Scope and method

All 85 unique videos in `raw_h3/source_videos` were visually inspected. The
review used eight-frame and sixteen-frame contact sheets for every source, denser
sheets for ambiguous/intense/sleep clips, ffprobe metadata, and YuNet on sixteen
sampled frames per video. Classification was based on image content, not file
position. Temporary sheets were kept outside the repository.

The complete per-video result is the machine-readable manifest:

`tools/facepack/manifests/h3_classification.json`

It records canonical action, category, confidence, intensity, initial/onset/peak/
hold/return frames, neutral return, loopability, microaction suitability, speed,
quality profile, defects, drift, redundancy, and keep/trim/review/discard choice.
The sequence number joins it to `source_inventory.json`, which remains authority
for filename, original path, timestamp, SHA256, known previous label, and removed
duplicates.

## Inventory

- 001–057: 768×768, 24 FPS, normally 124 frames / 5.167 s.
- 058–061: 73 frames / 3.042 s.
- 062 onward: mixed 107/124/73-frame H3 sources.
- 083: legacy 720×1280, 480 frames / 20.01 s.
- 084–085: legacy 1280×720, 240 frames / 10.005 s.
- 001–082: YuNet found exactly one face in every one of the 16 sampled frames;
  sampled minimum scores were approximately 0.91 or better.

Decision totals:

| Decision | Count |
|---|---:|
| Keep | 50 |
| Trim/compose | 28 |
| Manual semantic/quality review | 3 |
| Discard | 4 |

## Findings

- Most 001–082 clips preserve hair, clothing, lighting, identity, and camera
  framing well enough for curation, but contain long redundant holds.
- None should be treated as an infinite persistent-state loop. Idle/listening are
  schedulers over a still base and occasional microactions.
- Talk clips move the face vertically by roughly 36–51 source pixels. Tracking
  solved position but physical QA showed that their mouth/teeth geometry still
  deforms a different H3 expression. The current pack therefore preserves each
  clean authored talk clip full-frame. ROI extraction remains a compiler feature
  for future sources generated specifically as layers.
- Speech clips are sources for mouth shapes only. They are never emotion ids.
- Sources 39, 83, 84, and 85 are discarded. Source 39 has neutral background/
  panel drift; 83–85 have incompatible aspect, zoom, identity, or composition.
- Sources 28 and 82 remain semantically ambiguous. Source 64 has an anger/shout
  peak with unsafe teeth/jaw deformation. A second visual review confirmed that
  source 76 is a stable crying arc distinct from the stronger visible-tears
  source 77, so 76 moved from review to trim/keep.
- Several intense clips stop at peak instead of returning. The current lab pack
  uses the compatible return portion of source 49 after sources 50/74. This is a
  provisional curated transition, not evidence of a native H3 return.

## Current compiled desktop pack

The desktop manifest compiles 79 sequences / 2,888 logical frames from 76 distinct H3
sources:

- 2 state bases: neutral and sleeping;
- 28 microactions, including six blink variants, double blink, left/right eye
  wink, three brow variants, soft/strong four-direction gaze, nod, shake,
  acknowledge, three head tilts, idle breath and micro smiles;
- 30 emotions and 9 intense emotions, covering three anger levels, worry,
  relief, sadness levels, surprise levels, smiles/joy, displeasure, skeptical,
  playful, laugh levels, crying/tears, sleep/fall-asleep/yawn/wake;
- 10 independent speech sources across soft, normal, expressive, happy/playful
  and serious styles.

All 79 current sequences are full-frame. Nineteen eye/brow/gaze actions and ten
speech sources were previously evaluated as ROI layers; physical QA rejected
that build because cross-clip identity geometry deformed eyes and lips.
Sources 2 and 27 remain out because they are visually redundant with retained
variants. Review sources 28/64/82 and discard sources 39/83–85 remain out.

Persistent states are idle, waiting, attentive, listening, processing, and
sleeping. Their wait ranges and cooldowns prevent mechanical repetition.

## Content still worth regenerating with H3

- a natural neutral return for `laugh_hard`, open joy, strong anger, strong
  sadness, fear/worry, relief, and tears;
- clean native `crying`/`crying_tears` recovery instead of a curated reverse;
- a strong shout/anger peak with stable teeth and jaw;
- distinct fear, embarrassed, proud, love, and disgust arcs with neutral entry and
  exit;
- dedicated short wake/sleep transitions without mixed semantic phases;
- purpose-built mouth-layer sources for neutral/happy/serious/expressive speech:
  exact canonical starting image, fixed camera/head/body/eyes/brows/hair, only
  jaw/lips moving, stable teeth/tongue, and identical closed-mouth entry/exit;
- purpose-built upper-face layers: the same canonical image with head/body/mouth
  fixed and only blink, gaze or brows moving. Generic full-face blink videos are
  not interchangeable layers;
- optional phoneme/viseme coverage only if generated with labeled ground truth
  (`rest`, closed M/B/P, A/E/I/O/U, F/V, L); do not infer those labels from the
  current unlabeled talk clips.

The source MP4 files were not deleted or modified.
Post-build verification found 85 inventory entries, 85 source MP4 files, and
zero SHA-256 mismatches against `source_inventory.json`.
