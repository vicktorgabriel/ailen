"""Benchmark the native FacePack engine on the current machine only."""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from pathlib import Path
from typing import Any

from ailen.face.native_engine import NativeFaceEngine


def _rss_bytes() -> int:
    fields = Path("/proc/self/statm").read_text(encoding="ascii").split()
    return int(fields[1]) * os.sysconf("SC_PAGE_SIZE")


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _timed_realtime_loop(
    engine: NativeFaceEngine,
    seconds: float,
    frame_ms: int,
) -> tuple[float, list[float]]:
    deadline = time.perf_counter() + seconds
    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    samples: list[float] = []
    while time.perf_counter() < deadline:
        frame_started = time.perf_counter()
        engine.update(frame_ms)
        engine.frame_rgb()
        elapsed = time.perf_counter() - frame_started
        samples.append(elapsed * 1000.0)
        remaining = frame_ms / 1000.0 - elapsed
        if remaining > 0:
            time.sleep(remaining)
    wall = time.perf_counter() - wall_started
    cpu = time.process_time() - cpu_started
    return (100.0 * cpu / wall if wall > 0 else 0.0), samples


def benchmark(library: Path, pack: Path, duration_seconds: float) -> dict[str, Any]:
    baseline_rss = _rss_bytes()
    library_started = time.perf_counter()
    engine = NativeFaceEngine(library)
    library_load_ms = (time.perf_counter() - library_started) * 1000.0
    before_pack_rss = _rss_bytes()
    pack_started = time.perf_counter()
    engine.load_pack(pack, allowed_root=pack.parent)
    pack_load_ms = (time.perf_counter() - pack_started) * 1000.0
    after_pack_rss = _rss_bytes()
    try:
        engine.set_random_seed(20260830)
        engine.set_state("idle")
        idle_cpu, idle_samples = _timed_realtime_loop(engine, duration_seconds, 33)

        engine.clear_expression()
        engine.trigger_expression("happy", duration_seconds + 1.0)
        engine.set_speech_level(0.8)
        animation_cpu, animation_samples = _timed_realtime_loop(
            engine, duration_seconds, 33
        )

        engine.set_speech_level(0.0)
        engine.clear_expression()
        engine.trigger_expression("happy")
        expression_started = time.perf_counter()
        engine.trigger_expression("surprised")
        engine.update(1)
        expression_switch_ms = (time.perf_counter() - expression_started) * 1000.0

        tight_samples: list[float] = []
        engine.clear_expression()
        engine.trigger_expression("happy", 10.0)
        engine.set_speech_level(0.8)
        tight_started = time.perf_counter()
        for _ in range(250):
            started = time.perf_counter()
            engine.update(33)
            engine.frame_rgb()
            tight_samples.append((time.perf_counter() - started) * 1000.0)
        tight_wall = time.perf_counter() - tight_started
        sustainable_fps = 250 / tight_wall

        copy_samples: list[float] = []
        for _ in range(200):
            started = time.perf_counter()
            engine.frame_rgb()
            copy_samples.append((time.perf_counter() - started) * 1000.0)

        return {
            "scope": "ASRock laboratory only; no extrapolation to product tiers",
            "platform": platform.platform(),
            "cpu_logical_count": os.cpu_count(),
            "system_load_average": list(os.getloadavg()),
            "engine_library_bytes": library.stat().st_size,
            "facepack_bytes": pack.stat().st_size,
            "pack_id": engine.pack_id,
            "pack_version": engine.pack_version,
            "frame": {
                "width": engine.width,
                "height": engine.height,
                "rgb_bytes": engine.width * engine.height * 3,
            },
            "library_load_ms": library_load_ms,
            "pack_load_ms": pack_load_ms,
            "rss": {
                "baseline_bytes": baseline_rss,
                "after_library_bytes": before_pack_rss,
                "after_pack_bytes": after_pack_rss,
                "pack_delta_bytes": after_pack_rss - before_pack_rss,
            },
            "idle_realtime": {
                "duration_seconds": duration_seconds,
                "process_cpu_percent_one_core_scale": idle_cpu,
                "update_copy_ms_avg": statistics.fmean(idle_samples),
                "update_copy_ms_p95": _percentile(idle_samples, 0.95),
            },
            "layered_animation_realtime": {
                "duration_seconds": duration_seconds,
                "process_cpu_percent_one_core_scale": animation_cpu,
                "update_copy_ms_avg": statistics.fmean(animation_samples),
                "update_copy_ms_p95": _percentile(animation_samples, 0.95),
                "layers": ["pack_selected_full_frame_speech"],
                "semantic_emotion_retained": True,
            },
            "tight_loop": {
                "iterations": 250,
                "sustainable_fps": sustainable_fps,
                "update_copy_ms_avg": statistics.fmean(tight_samples),
                "update_copy_ms_p95": _percentile(tight_samples, 0.95),
            },
            "frame_copy_ms_avg": statistics.fmean(copy_samples),
            "frame_copy_ms_p95": _percentile(copy_samples, 0.95),
            "expression_switch_update_ms": expression_switch_ms,
            "expressions": list(engine.expressions),
            "runtime_uses_mp4": False,
        }
    finally:
        engine.close()


def _tk_screen_size() -> tuple[int, int]:
    import tkinter as tk

    probe = tk.Tk()
    probe.withdraw()
    try:
        probe.update_idletasks()
        return probe.winfo_screenwidth(), probe.winfo_screenheight()
    finally:
        probe.destroy()


def _benchmark_tk_profile(
    library: Path,
    pack: Path,
    duration_seconds: float,
    *,
    width: int,
    height: int,
    fullscreen: bool,
) -> dict[str, Any]:
    """Measure one real Tk/PPM presentation profile."""

    from ailen.domain.enums import AssistantState
    from ailen.face.native_controller import NativeFaceController

    controller = NativeFaceController(
        library_path=library,
        facepack_path=pack,
        allowed_facepack_root=pack.parent,
        width=width,
        height=height,
        fullscreen=fullscreen,
        fps_limit=30,
    )

    def measure() -> dict[str, float | int]:
        wall_started = time.perf_counter()
        cpu_started = time.process_time()
        pumps = 0
        while time.perf_counter() - wall_started < duration_seconds:
            controller.update()
            pumps += 1
            time.sleep(0.005)
        wall = time.perf_counter() - wall_started
        cpu = time.process_time() - cpu_started
        return {
            "process_cpu_percent_one_core_scale": 100.0 * cpu / wall,
            "event_pump_iterations": pumps,
            "frame_generation": controller.engine.frame_generation,
        }

    try:
        controller.start_window(interactive_keys=False)
        controller.engine.set_random_seed(20260830)
        controller.set_state(AssistantState.IDLE)
        idle = measure()
        generation_before_animation = controller.engine.frame_generation
        controller.set_expression("happy", duration_seconds + 1.0)
        controller.set_speech_level(0.8)
        animation = measure()
        animation["generated_frames"] = (
            controller.engine.frame_generation - generation_before_animation
        )
        return {
            "display": os.environ.get("DISPLAY", ""),
            "window_size": [width, height],
            "fullscreen": fullscreen,
            "fps_limit": 30,
            "presentation_ratio": list(controller.presentation_ratio),
            "presentation_size": list(controller.presentation_size),
            "idle": idle,
            "animation_with_speech": animation,
        }
    finally:
        controller.close()


def benchmark_tk_display(
    library: Path,
    pack: Path,
    duration_seconds: float,
) -> dict[str, Any]:
    """Measure 800x480, 1280x720, and the current fullscreen X11 path."""

    screen_width, screen_height = _tk_screen_size()
    profiles = {
        "window_800x480": (800, 480, False),
        "window_1280x720": (1280, 720, False),
        "fullscreen_current": (screen_width, screen_height, True),
    }
    return {
        name: _benchmark_tk_profile(
            library,
            pack,
            duration_seconds,
            width=width,
            height=height,
            fullscreen=fullscreen,
        )
        for name, (width, height, fullscreen) in profiles.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=float, default=3.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--with-tk",
        action="store_true",
        help="also open the real X11/Tk display path for idle/animation CPU measurements",
    )
    args = parser.parse_args()
    result = benchmark(args.library, args.pack, max(1.0, args.duration_seconds))
    if args.with_tk:
        result["tk_display"] = benchmark_tk_display(
            args.library,
            args.pack,
            max(1.0, args.duration_seconds),
        )
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
