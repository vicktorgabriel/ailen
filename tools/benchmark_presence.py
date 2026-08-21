"""Physical Presence and Face Animation Benchmark Suite for AILEN.

Measures throughput, frame time latency (p50/p95/p99), and memory usage
for FaceAnimator, VisionDebouncer, and the combined Coordinator pipeline.
"""

import json
import os
import resource
import time
from pathlib import Path
from typing import Any

from ailen.core.coordinator import InteractionCoordinator
from ailen.core.events import EventBus
from ailen.core.social import SocialEngine
from ailen.core.state import StateManager
from ailen.domain.enums import AssistantState, SocialMode
from ailen.face.animator import FaceAnimator
from ailen.face.null import NullFaceController
from ailen.vision.contracts import PresenceObservation
from ailen.vision.debouncer import VisionDebouncer


def get_peak_rss_mb() -> float:
    """Return process peak RSS in megabytes (Linux ru_maxrss)."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_maxrss / 1024.0


class SimClock:
    """Deterministic monotonic-style clock for integrated benchmarks."""

    def __init__(self, start: float = 100.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def benchmark_face_animator(iterations: int = 5000) -> dict[str, Any]:
    """Benchmark raw FaceAnimator compute throughput and frame time."""
    animator = FaceAnimator()
    animator.set_state(AssistantState.ATTENTION)
    animator.set_gaze(0.5, -0.3)
    animator.set_speech_level(0.7)

    frame_times_us: list[float] = []
    start_rss = get_peak_rss_mb()
    t_start = time.perf_counter()

    for i in range(iterations):
        t0 = time.perf_counter()
        animator.step(current_time=100.0 + i * 0.033)
        t1 = time.perf_counter()
        frame_times_us.append((t1 - t0) * 1_000_000.0)

    total_time_sec = time.perf_counter() - t_start
    end_rss = get_peak_rss_mb()

    frame_times_us.sort()
    p50 = frame_times_us[int(len(frame_times_us) * 0.50)]
    p95 = frame_times_us[int(len(frame_times_us) * 0.95)]
    p99 = frame_times_us[int(len(frame_times_us) * 0.99)]
    avg_us = sum(frame_times_us) / len(frame_times_us)
    throughput_fps = iterations / total_time_sec

    return {
        "component": "FaceAnimator",
        "iterations": iterations,
        "total_time_sec": round(total_time_sec, 4),
        "throughput_fps": round(throughput_fps, 1),
        "avg_frame_time_us": round(avg_us, 2),
        "p50_frame_time_us": round(p50, 2),
        "p95_frame_time_us": round(p95, 2),
        "p99_frame_time_us": round(p99, 2),
        "process_peak_rss_mb_start": round(start_rss, 2),
        "process_peak_rss_mb_end": round(end_rss, 2),
        "process_peak_rss_delta_mb": round(max(0.0, end_rss - start_rss), 2),
    }


def benchmark_vision_debouncer(iterations: int = 10000) -> dict[str, Any]:
    """Benchmark VisionDebouncer update throughput."""
    debouncer = VisionDebouncer(debounce_seconds=2.0)
    raw_present = PresenceObservation(present=True, primary_x_normalized=0.2, primary_y_normalized=0.1)
    raw_absent = PresenceObservation(present=False)

    update_times_us: list[float] = []
    t_start = time.perf_counter()

    for i in range(iterations):
        raw = raw_present if (i % 100 < 50) else raw_absent
        t0 = time.perf_counter()
        debouncer.update(raw, current_time=100.0 + i * 0.05)
        t1 = time.perf_counter()
        update_times_us.append((t1 - t0) * 1_000_000.0)

    total_time_sec = time.perf_counter() - t_start
    update_times_us.sort()
    p50 = update_times_us[int(len(update_times_us) * 0.50)]
    p95 = update_times_us[int(len(update_times_us) * 0.95)]
    avg_us = sum(update_times_us) / len(update_times_us)
    throughput_ops = iterations / total_time_sec

    return {
        "component": "VisionDebouncer",
        "iterations": iterations,
        "total_time_sec": round(total_time_sec, 4),
        "throughput_updates_per_sec": round(throughput_ops, 1),
        "avg_update_time_us": round(avg_us, 2),
        "p50_update_time_us": round(p50, 2),
        "p95_update_time_us": round(p95, 2),
    }


def benchmark_integrated_pipeline(iterations: int = 3000) -> dict[str, Any]:
    """Benchmark end-to-end vision debouncer -> coordinator -> social -> face pipeline."""
    state_mgr = StateManager(initial_state=AssistantState.IDLE)
    social_engine = SocialEngine(default_cooldown_seconds=60.0)
    event_bus = EventBus(record_history=False)
    clock = SimClock(100.0)
    face_ctrl = NullFaceController(animator=FaceAnimator(clock=clock))
    debouncer = VisionDebouncer(debounce_seconds=2.0, clock=clock)

    coordinator = InteractionCoordinator(
        state_manager=state_mgr,
        social_engine=social_engine,
        event_bus=event_bus,
        mode=SocialMode.WORKSHOP,
        face_controller=face_ctrl,
        debouncer=debouncer,
        clock=clock,
    )

    raw_present = PresenceObservation(present=True, primary_x_normalized=0.4, primary_y_normalized=0.2)
    raw_absent = PresenceObservation(present=False)

    latencies_us: list[float] = []
    t_start = time.perf_counter()

    for i in range(iterations):
        raw = raw_present if (i % 60 < 30) else raw_absent
        clock.advance(0.1)
        t0 = time.perf_counter()
        # Step debouncer + coordinator + face controller pose using the same
        # simulated clock, so debounce transitions are actually exercised.
        coordinator.handle_raw_presence_observation(raw)
        face_ctrl.get_current_pose(current_time=clock())
        t1 = time.perf_counter()
        latencies_us.append((t1 - t0) * 1_000_000.0)

    total_time_sec = time.perf_counter() - t_start
    latencies_us.sort()
    p50 = latencies_us[int(len(latencies_us) * 0.50)]
    p95 = latencies_us[int(len(latencies_us) * 0.95)]
    avg_us = sum(latencies_us) / len(latencies_us)
    throughput_cycles = iterations / total_time_sec

    return {
        "component": "IntegratedPipeline",
        "iterations": iterations,
        "total_time_sec": round(total_time_sec, 4),
        "throughput_cycles_per_sec": round(throughput_cycles, 1),
        "avg_cycle_time_us": round(avg_us, 2),
        "p50_cycle_time_us": round(p50, 2),
        "p95_cycle_time_us": round(p95, 2),
    }


def run_all_benchmarks() -> dict[str, Any]:
    """Run all benchmark scenarios and return structured report."""
    return {
        "environment": "DEV MACHINE — NO HARDWARE TARGET",
        "system_info": {
            "os": os.uname().sysname,
            "release": os.uname().release,
            "machine": os.uname().machine,
        },
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "benchmarks": {
            "face_animator": benchmark_face_animator(5000),
            "vision_debouncer": benchmark_vision_debouncer(10000),
            "integrated_pipeline": benchmark_integrated_pipeline(3000),
        },
    }


def format_markdown_report(report: dict[str, Any]) -> str:
    """Format benchmark report as Markdown."""
    face = report["benchmarks"]["face_animator"]
    vision = report["benchmarks"]["vision_debouncer"]
    pipe = report["benchmarks"]["integrated_pipeline"]

    return f"""# Benchmark de Presencia Física y Face — AILEN R2A

> **ADVERTENCIA OBLIGATORIA:**  
> **{report['environment']}**  
> Estas mediciones fueron ejecutadas en la máquina de desarrollo (`{report['system_info']['machine']}`, Linux `{report['system_info']['release']}`).  
> **NO constituyen benchmark ni validación en hardware objetivo** (Banghó Zero G05 / SF20BA). Las pruebas en dichos dispositivos permanecen pendientes de ejecución física.

**Fecha de ejecución:** `{report['timestamp']}`

---

## 1. FaceAnimator (Motor Lógico de Rostro)

Calcula poses normalizadas, parpadeo natural no periódico, interpolación suave de mirada y apertura de boca.

| Métrica | Valor |
| :--- | :--- |
| **Iteraciones** | {face['iterations']} |
| **Tiempo total** | {face['total_time_sec']} s |
| **Throughput** | **{face['throughput_fps']} FPS** (modo unconstrained) |
| **Frame Time Promedio** | **{face['avg_frame_time_us']} µs** ({face['avg_frame_time_us']/1000:.3f} ms) |
| **Frame Time p50** | {face['p50_frame_time_us']} µs |
| **Frame Time p95** | {face['p95_frame_time_us']} µs |
| **Frame Time p99** | {face['p99_frame_time_us']} µs |
| **Peak RSS del proceso (inicio → fin)** | {face['process_peak_rss_mb_start']} → {face['process_peak_rss_mb_end']} MB |
| **Δ peak RSS durante la prueba** | {face['process_peak_rss_delta_mb']} MB |

*Interpretación Face:* esta medición cubre sólo costo de cómputo del `FaceAnimator`; el RSS corresponde al **proceso Python completo**, no a memoria atribuible exclusivamente al rostro. El uso de CPU a 30 FPS debe medirse por separado en hardware objetivo.

---

## 2. VisionDebouncer (Filtro Temporal de Presencia)

Filtra oscilaciones rápidas y confirma presencia/ausencia estable según ventana temporal.

| Métrica | Valor |
| :--- | :--- |
| **Iteraciones** | {vision['iterations']} |
| **Throughput** | **{vision['throughput_updates_per_sec']} updates/segundo** |
| **Latencia Promedio** | **{vision['avg_update_time_us']} µs** |
| **Latencia p50** | {vision['p50_update_time_us']} µs |
| **Latencia p95** | {vision['p95_update_time_us']} µs |

---

## 3. Pipeline Integrado (Visión → Debouncer → Coordinator → Social → Face)

Ciclo completo de presencia física: actualización de visión, debounce temporal, transición de estados en `StateManager`, evaluación en `SocialEngine` y emisión de pose en `FaceAnimator`.

| Métrica | Valor |
| :--- | :--- |
| **Ciclos evaluados** | {pipe['iterations']} |
| **Throughput integrado** | **{pipe['throughput_cycles_per_sec']} ciclos/segundo** |
| **Tiempo por ciclo promedio** | **{pipe['avg_cycle_time_us']} µs** ({pipe['avg_cycle_time_us']/1000:.3f} ms) |
| **Tiempo por ciclo p50** | {pipe['p50_cycle_time_us']} µs |
| **Tiempo por ciclo p95** | {pipe['p95_cycle_time_us']} µs |

*Interpretación General:* este benchmark mide overhead lógico del Core/Social/Face en la máquina DEV. No mide captura OpenCV real, render gráfico real ni audio/STT, y **no permite inferir todavía porcentajes de CPU ni latencia en Banghó/SF20BA**.
"""


def main() -> None:
    report = run_all_benchmarks()
    out_dir = Path("docs/benchmarks")
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "dev_presence_benchmark.json"
    md_path = out_dir / "dev_presence_benchmark.md"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(format_markdown_report(report), encoding="utf-8")

    print(f"Reporte JSON guardado en: {json_path}")
    print(f"Reporte Markdown guardado en: {md_path}")


if __name__ == "__main__":
    main()
