"""Inventory H3 video metadata and optionally create visual contact sheets.

This tool never assigns expression labels. Contact sheets are evidence for human
visual classification; chronology and filenames are not treated as semantics.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _run_json(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "external media probe failed")
    result = json.loads(completed.stdout)
    if not isinstance(result, dict):
        raise TypeError("external media probe returned an invalid document")
    return result


def _safe_sources(inventory: Path, source_dir: Path) -> list[tuple[int, Path]]:
    raw = json.loads(inventory.read_text(encoding="utf-8"))
    root = source_dir.resolve(strict=True)
    result: list[tuple[int, Path]] = []
    for item in raw["videos"]:
        path = (root / item["filename"]).resolve(strict=True)
        if root not in path.parents or not path.is_file():
            raise RuntimeError(f"source escapes corpus root: {item['filename']}")
        result.append((int(item["sequence"]), path))
    return result


def _probe(sequence: int, path: Path) -> dict[str, Any]:
    raw = _run_json(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,avg_frame_rate,nb_frames,duration",
            "-of",
            "json",
            str(path),
        ]
    )
    streams = raw.get("streams", [])
    if not streams:
        raise RuntimeError(f"no video stream: {path.name}")
    stream = streams[0]
    return {
        "sequence": sequence,
        "filename": path.name,
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "avg_frame_rate": stream.get("avg_frame_rate"),
        "frame_count": int(stream.get("nb_frames", 0)),
        "duration_seconds": float(stream.get("duration", 0.0)),
    }


def _contact_sheet(path: Path, destination: Path, duration: float, samples: int) -> None:
    sample_rate = samples / max(0.001, duration)
    columns = 4
    rows = (samples + columns - 1) // columns
    filter_graph = (
        f"fps={sample_rate:.8f},scale=240:-1:flags=lanczos,"
        f"drawtext=text='%{{n}}':x=8:y=8:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.6,"
        f"tile={columns}x{rows}"
    )
    completed = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(path),
            "-vf",
            filter_graph,
            "-frames:v",
            "1",
            str(destination),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"contact sheet failed: {path.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
    parser.add_argument("--contact-sheet-dir", type=Path)
    parser.add_argument("--samples", type=int, choices=(8, 16), default=16)
    args = parser.parse_args()
    if shutil.which("ffprobe") is None:
        print("ffprobe is required", file=sys.stderr)
        return 2
    if args.contact_sheet_dir is not None and shutil.which("ffmpeg") is None:
        print("ffmpeg is required for contact sheets", file=sys.stderr)
        return 2
    try:
        sources = _safe_sources(args.inventory, args.source_dir)
        videos = [_probe(sequence, path) for sequence, path in sources]
        if args.contact_sheet_dir is not None:
            args.contact_sheet_dir.mkdir(parents=True, exist_ok=True)
            for metadata, (_, path) in zip(videos, sources, strict=True):
                _contact_sheet(
                    path,
                    args.contact_sheet_dir / f"{metadata['sequence']:03d}.jpg",
                    float(metadata["duration_seconds"]),
                    args.samples,
                )
        report = {
            "source_video_count": len(videos),
            "classification_performed": False,
            "videos": videos,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (OSError, KeyError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"source analysis failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
