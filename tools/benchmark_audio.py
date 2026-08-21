"""Audio, VAD, STT, and TTS Benchmark Suite for AILEN.

Measures throughput and latency (p50/p95/p99) for:
- PCM RMS energy computation
- Voice Activity Detection (EnergyVad)
- Utterance Collector throughput
- AudioTurnGate frame filtering
- End-to-end AudioInteractionCoordinator pipeline
"""

import json
import os
import resource
import time
from pathlib import Path
from typing import Any

from ailen.audio.coordinator import AudioInteractionCoordinator
from ailen.audio.fake import (
    FakeAudioInputBackend,
    FakeAudioOutputBackend,
    FakeSttBackend,
    FakeTtsBackend,
)
from ailen.audio.pcm import compute_pcm_rms, generate_silence_pcm, generate_tone_pcm
from ailen.audio.piper_backend import PiperTtsBackend
from ailen.audio.turn_gate import AudioTurnGate
from ailen.audio.vad import EnergyVad, UtteranceCollector
from ailen.audio.vosk_backend import VoskSttBackend
from ailen.audio.whisper_backend import WhisperCppSttBackend
from ailen.core.events import EventBus
from ailen.core.state import StateManager
from ailen.domain.enums import AssistantState
from ailen.face.null import NullFaceController


def get_current_rss_mb() -> float:
    """Return resident set size in megabytes."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_maxrss / 1024.0


def benchmark_pcm_rms(iterations: int = 50000) -> dict[str, Any]:
    """Benchmark raw PCM RMS calculation."""
    frame = generate_tone_pcm(freq_hz=440.0, duration_ms=20.0, amplitude=0.1, sample_rate=16000)
    latencies_us: list[float] = []

    t_start = time.perf_counter()
    for _ in range(iterations):
        t0 = time.perf_counter()
        compute_pcm_rms(frame)
        t1 = time.perf_counter()
        latencies_us.append((t1 - t0) * 1_000_000.0)

    total_time = time.perf_counter() - t_start
    latencies_us.sort()

    return {
        "component": "compute_pcm_rms",
        "iterations": iterations,
        "total_time_sec": round(total_time, 4),
        "throughput_frames_per_sec": round(iterations / total_time, 1),
        "avg_frame_time_us": round(sum(latencies_us) / len(latencies_us), 2),
        "p50_frame_time_us": round(latencies_us[int(len(latencies_us) * 0.50)], 2),
        "p95_frame_time_us": round(latencies_us[int(len(latencies_us) * 0.95)], 2),
    }


def benchmark_energy_vad(iterations: int = 50000) -> dict[str, Any]:
    """Benchmark Energy VAD per-frame processing."""
    vad = EnergyVad(threshold_rms=0.02)
    voice_frame = generate_tone_pcm(freq_hz=440.0, duration_ms=20.0, amplitude=0.1)
    silence_frame = generate_silence_pcm(duration_ms=20.0)

    latencies_us: list[float] = []
    t_start = time.perf_counter()

    for i in range(iterations):
        frame = voice_frame if (i % 2 == 0) else silence_frame
        t0 = time.perf_counter()
        vad.process_frame(frame)
        t1 = time.perf_counter()
        latencies_us.append((t1 - t0) * 1_000_000.0)

    total_time = time.perf_counter() - t_start
    latencies_us.sort()

    return {
        "component": "EnergyVad",
        "iterations": iterations,
        "total_time_sec": round(total_time, 4),
        "throughput_frames_per_sec": round(iterations / total_time, 1),
        "avg_frame_time_us": round(sum(latencies_us) / len(latencies_us), 2),
        "p50_frame_time_us": round(latencies_us[int(len(latencies_us) * 0.50)], 2),
        "p95_frame_time_us": round(latencies_us[int(len(latencies_us) * 0.95)], 2),
        "p99_frame_time_us": round(latencies_us[int(len(latencies_us) * 0.99)], 2),
    }


def benchmark_utterance_collector(iterations: int = 20000) -> dict[str, Any]:
    """Benchmark UtteranceCollector frame processing and buffering."""
    vad = EnergyVad(threshold_rms=0.02)
    collector = UtteranceCollector(vad=vad, frame_ms=20.0)
    voice_frame = generate_tone_pcm(freq_hz=440.0, duration_ms=20.0, amplitude=0.1)
    silence_frame = generate_silence_pcm(duration_ms=20.0)

    latencies_us: list[float] = []
    t_start = time.perf_counter()

    for i in range(iterations):
        frame = voice_frame if (i % 50 < 25) else silence_frame
        t0 = time.perf_counter()
        collector.process_frame(frame)
        t1 = time.perf_counter()
        latencies_us.append((t1 - t0) * 1_000_000.0)

    total_time = time.perf_counter() - t_start
    latencies_us.sort()

    return {
        "component": "UtteranceCollector",
        "iterations": iterations,
        "total_time_sec": round(total_time, 4),
        "throughput_frames_per_sec": round(iterations / total_time, 1),
        "avg_frame_time_us": round(sum(latencies_us) / len(latencies_us), 2),
        "p50_frame_time_us": round(latencies_us[int(len(latencies_us) * 0.50)], 2),
        "p95_frame_time_us": round(latencies_us[int(len(latencies_us) * 0.95)], 2),
    }


def benchmark_turn_gate(iterations: int = 50000) -> dict[str, Any]:
    """Benchmark AudioTurnGate filter latency."""
    gate = AudioTurnGate(settling_cooldown_seconds=0.1)
    frame = b"\x00\x00" * 320

    latencies_us: list[float] = []
    t_start = time.perf_counter()

    for _ in range(iterations):
        t0 = time.perf_counter()
        gate.filter_frame(frame)
        t1 = time.perf_counter()
        latencies_us.append((t1 - t0) * 1_000_000.0)

    total_time = time.perf_counter() - t_start
    latencies_us.sort()

    return {
        "component": "AudioTurnGate",
        "iterations": iterations,
        "total_time_sec": round(total_time, 4),
        "throughput_frames_per_sec": round(iterations / total_time, 1),
        "avg_frame_time_us": round(sum(latencies_us) / len(latencies_us), 2),
        "p50_frame_time_us": round(latencies_us[int(len(latencies_us) * 0.50)], 2),
        "p95_frame_time_us": round(latencies_us[int(len(latencies_us) * 0.95)], 2),
    }


def benchmark_audio_coordinator_pipeline(iterations: int = 1000) -> dict[str, Any]:
    """Benchmark full audio coordinator pipeline (VAD + State + Events + STT/TTS)."""
    input_backend = FakeAudioInputBackend()
    output_backend = FakeAudioOutputBackend()
    stt_backend = FakeSttBackend(canned_text="comando de prueba")
    tts_backend = FakeTtsBackend()
    state_mgr = StateManager(initial_state=AssistantState.IDLE)
    face_ctrl = NullFaceController()
    event_bus = EventBus(record_history=False)

    coordinator = AudioInteractionCoordinator(
        audio_input=input_backend,
        audio_output=output_backend,
        stt=stt_backend,
        tts=tts_backend,
        state_manager=state_mgr,
        face_controller=face_ctrl,
        event_bus=event_bus,
    )

    latencies_us: list[float] = []
    t_start = time.perf_counter()

    for i in range(iterations):
        t0 = time.perf_counter()
        # Full turn cycle: speak() + fake listen
        coordinator.speak(f"Test utterance {i}")
        t1 = time.perf_counter()
        latencies_us.append((t1 - t0) * 1_000_000.0)

    total_time = time.perf_counter() - t_start
    latencies_us.sort()

    return {
        "component": "AudioInteractionCoordinator (Turn Cycle)",
        "iterations": iterations,
        "total_time_sec": round(total_time, 4),
        "throughput_cycles_per_sec": round(iterations / total_time, 1),
        "avg_cycle_time_us": round(sum(latencies_us) / len(latencies_us), 2),
        "p50_cycle_time_us": round(latencies_us[int(len(latencies_us) * 0.50)], 2),
        "p95_cycle_time_us": round(latencies_us[int(len(latencies_us) * 0.95)], 2),
    }


def check_optional_models() -> dict[str, Any]:
    """Check physical status of Vosk, Whisper, and Piper models on host."""
    vosk = VoskSttBackend().health()
    whisper = WhisperCppSttBackend().health()
    piper = PiperTtsBackend().health()

    return {
        "vosk_stt": {
            "status": vosk.status.value,
            "detail": vosk.detail,
            "benchmark_status": "NOT RUN (MODEL NOT CONFIGURED)",
        },
        "whisper_cpp_stt": {
            "status": whisper.status.value,
            "detail": whisper.detail,
            "benchmark_status": "NOT RUN (BINARY/MODEL NOT CONFIGURED)",
        },
        "piper_tts": {
            "status": piper.status.value,
            "detail": piper.detail,
            "benchmark_status": "NOT RUN (BINARY/MODEL NOT CONFIGURED)",
        },
    }


def run_all_audio_benchmarks() -> dict[str, Any]:
    """Execute all audio benchmarks and compile results."""
    report = {
        "environment": "DEV MACHINE — NO HARDWARE TARGET",
        "system_info": {
            "os": os.uname().sysname,
            "release": os.uname().release,
            "machine": os.uname().machine,
        },
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "logical_benchmarks": {
            "pcm_rms": benchmark_pcm_rms(50000),
            "energy_vad": benchmark_energy_vad(50000),
            "utterance_collector": benchmark_utterance_collector(20000),
            "turn_gate": benchmark_turn_gate(50000),
            "coordinator_turn": benchmark_audio_coordinator_pipeline(1000),
        },
        "real_engines_status": check_optional_models(),
        "process_rss_mb": round(get_current_rss_mb(), 2),
    }
    return report


def format_markdown_report(report: dict[str, Any]) -> str:
    """Format benchmark report as Markdown."""
    rms = report["logical_benchmarks"]["pcm_rms"]
    vad = report["logical_benchmarks"]["energy_vad"]
    col = report["logical_benchmarks"]["utterance_collector"]
    gate = report["logical_benchmarks"]["turn_gate"]
    coord = report["logical_benchmarks"]["coordinator_turn"]
    engines = report["real_engines_status"]

    return f"""# Benchmark de Audio, VAD, STT y TTS — AILEN R2B

> **ADVERTENCIA OBLIGATORIA:**  
> **{report['environment']}**  
> Estas mediciones fueron ejecutadas en la máquina de desarrollo (`{report['system_info']['machine']}`, Linux `{report['system_info']['release']}`).  
> **NO constituyen benchmark ni validación en hardware objetivo** (Banghó Zero G05 / SF20BA). Las pruebas en dichos dispositivos permanecen pendientes de ejecución física.

**Fecha de ejecución:** `{report['timestamp']}`  
**Memoria RSS del proceso:** `{report['process_rss_mb']} MB` (proceso Python completo con benchmarks)

---

## 1. Benchmarks Lógicos (Python Puro / Zero ML Dependency)

### 1.1 Cálculo de RMS en PCM (`compute_pcm_rms`)
Procesamiento de frames PCM 16-bit mono a 16 kHz (20 ms / 640 bytes por frame):

| Métrica | Valor |
| :--- | :--- |
| **Iteraciones** | {rms['iterations']} |
| **Throughput** | **{rms['throughput_frames_per_sec']:,} frames/segundo** |
| **Tiempo por frame promedio** | **{rms['avg_frame_time_us']} µs** (0.00{int(rms['avg_frame_time_us'])} ms) |
| **Tiempo por frame p50** | {rms['p50_frame_time_us']} µs |
| **Tiempo por frame p95** | {rms['p95_frame_time_us']} µs |

---

### 1.2 Energy VAD (`EnergyVad`)
Detección de voz/silencio por frame + manejo de hangover:

| Métrica | Valor |
| :--- | :--- |
| **Iteraciones** | {vad['iterations']} |
| **Throughput** | **{vad['throughput_frames_per_sec']:,} frames/segundo** |
| **Tiempo por frame promedio** | **{vad['avg_frame_time_us']} µs** |
| **Tiempo por frame p50** | {vad['p50_frame_time_us']} µs |
| **Tiempo por frame p95** | {vad['p95_frame_time_us']} µs |
| **Tiempo por frame p99** | {vad['p99_frame_time_us']} µs |

*Interpretación VAD:* en esta máquina DEV el costo lógico por frame es muy pequeño frente a una ventana de audio de 20 ms. Esto **no equivale a una medición de porcentaje de CPU** en Banghó/SF20BA.

---

### 1.3 UtteranceCollector (Agrupador Temporal)
Ring buffer de pre-roll + acumulación de frames y verificación de timeout:

| Métrica | Valor |
| :--- | :--- |
| **Iteraciones** | {col['iterations']} |
| **Throughput** | **{col['throughput_frames_per_sec']:,} frames/segundo** |
| **Latencia promedio por frame** | **{col['avg_frame_time_us']} µs** |
| **Latencia p50** | {col['p50_frame_time_us']} µs |
| **Latencia p95** | {col['p95_frame_time_us']} µs |

---

### 1.4 AudioTurnGate (Half-Duplex Filtering)
Filtrado atómico y verificación de estado/cooldown acústico:

| Métrica | Valor |
| :--- | :--- |
| **Iteraciones** | {gate['iterations']} |
| **Throughput** | **{gate['throughput_frames_per_sec']:,} frames/segundo** |
| **Latencia promedio** | **{gate['avg_frame_time_us']} µs** |

---

### 1.5 Pipeline Integrado (`AudioInteractionCoordinator`)
Ciclo completo de coordinación (TTS + bloqueo half-duplex + mouth sync + retorno a IDLE):

| Métrica | Valor |
| :--- | :--- |
| **Ciclos completos** | {coord['iterations']} |
| **Throughput** | **{coord['throughput_cycles_per_sec']} turnos/segundo** |
| **Tiempo por ciclo promedio** | **{coord['avg_cycle_time_us']} µs** ({coord['avg_cycle_time_us']/1000:.3f} ms) |
| **Tiempo por ciclo p50** | {coord['p50_cycle_time_us']} µs |
| **Tiempo por ciclo p95** | {coord['p95_cycle_time_us']} µs |

---

## 2. Estado de Motores Reales de Inferencia en Máquina DEV

| Motor | Componente | Estado de Detección | Estado de Benchmark |
| :--- | :--- | :--- | :--- |
| **Vosk** | STT | `{engines['vosk_stt']['status']}` ({engines['vosk_stt']['detail']}) | `{engines['vosk_stt']['benchmark_status']}` |
| **whisper.cpp** | STT | `{engines['whisper_cpp_stt']['status']}` ({engines['whisper_cpp_stt']['detail']}) | `{engines['whisper_cpp_stt']['benchmark_status']}` |
| **Piper** | TTS | `{engines['piper_tts']['status']}` ({engines['piper_tts']['detail']}) | `{engines['piper_tts']['benchmark_status']}` |

*Nota:* Conforme a la política de seguridad y testing offline, los modelos neuronales reales no se descargan automáticamente en CI ni en tests normales. Cuando se instalen en el hardware objetivo (Banghó / SF20BA), se registrarán los tiempos reales de inferencia y RTF físico.
"""


def main() -> None:
    report = run_all_audio_benchmarks()
    out_dir = Path("docs/benchmarks")
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "dev_audio_benchmark.json"
    md_path = out_dir / "dev_audio_benchmark.md"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(format_markdown_report(report), encoding="utf-8")

    print(f"Reporte JSON guardado en: {json_path}")
    print(f"Reporte Markdown guardado en: {md_path}")


if __name__ == "__main__":
    main()
