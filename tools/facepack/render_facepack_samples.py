"""Render diagnostic FacePack frames to PPM files without opening a viewer."""

from __future__ import annotations

import argparse
from pathlib import Path

from ailen.face.native_engine import NativeFaceEngine


def _write_ppm(path: Path, width: int, height: int, rgb: bytes) -> None:
    path.write_bytes(f"P6\n{width} {height}\n255\n".encode("ascii") + rgb)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--elapsed-ms", type=int, default=800)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with NativeFaceEngine(args.library) as engine:
        engine.load_pack(args.pack, allowed_root=args.pack.parent)
        engine.set_random_seed(20260830)
        engine.set_state("idle")
        engine.update(1)
        _write_ppm(
            args.output_dir / "idle.ppm",
            engine.width,
            engine.height,
            engine.frame_rgb(),
        )
        for expression in engine.expressions:
            engine.clear_expression()
            engine.trigger_expression(expression)
            engine.update(args.elapsed_ms)
            _write_ppm(
                args.output_dir / f"expression_{expression}.ppm",
                engine.width,
                engine.height,
                engine.frame_rgb(),
            )
        engine.clear_expression()
        engine.trigger_expression("happy", 2.0)
        engine.update(args.elapsed_ms)
        engine.set_gaze(-0.9, 0.0)
        engine.update(0)
        _write_ppm(
            args.output_dir / "happy_with_gaze.ppm",
            engine.width,
            engine.height,
            engine.frame_rgb(),
        )
        engine.update(120)
        _write_ppm(
            args.output_dir / "happy_with_gaze_advanced.ppm",
            engine.width,
            engine.height,
            engine.frame_rgb(),
        )
        engine.set_speech_level(0.85)
        engine.update(0)
        _write_ppm(
            args.output_dir / "happy_with_gaze_and_speech.ppm",
            engine.width,
            engine.height,
            engine.frame_rgb(),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
