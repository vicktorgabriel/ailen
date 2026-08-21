# Benchmark de Audio, VAD, STT y TTS — AILEN R2B

> **ADVERTENCIA OBLIGATORIA:**  
> **DEV MACHINE — NO HARDWARE TARGET**  
> Estas mediciones fueron ejecutadas en la máquina de desarrollo (`x86_64`, Linux `7.0.0-28-generic`).  
> **NO constituyen benchmark ni validación en hardware objetivo** (Banghó Zero G05 / SF20BA). Las pruebas en dichos dispositivos permanecen pendientes de ejecución física.

**Fecha de ejecución:** `2026-08-21T20:13:47Z`  
**Memoria RSS del proceso:** `73.07 MB` (proceso Python completo con benchmarks)

---

## 1. Benchmarks Lógicos (Python Puro / Zero ML Dependency)

### 1.1 Cálculo de RMS en PCM (`compute_pcm_rms`)
Procesamiento de frames PCM 16-bit mono a 16 kHz (20 ms / 640 bytes por frame):

| Métrica | Valor |
| :--- | :--- |
| **Iteraciones** | 50000 |
| **Throughput** | **38,596.9 frames/segundo** |
| **Tiempo por frame promedio** | **25.72 µs** (0.0025 ms) |
| **Tiempo por frame p50** | 23.22 µs |
| **Tiempo por frame p95** | 28.07 µs |

---

### 1.2 Energy VAD (`EnergyVad`)
Detección de voz/silencio por frame + manejo de hangover:

| Métrica | Valor |
| :--- | :--- |
| **Iteraciones** | 50000 |
| **Throughput** | **43,787.0 frames/segundo** |
| **Tiempo por frame promedio** | **22.5 µs** |
| **Tiempo por frame p50** | 17.72 µs |
| **Tiempo por frame p95** | 28.21 µs |
| **Tiempo por frame p99** | 36.51 µs |

*Interpretación VAD:* en esta máquina DEV el costo lógico por frame es muy pequeño frente a una ventana de audio de 20 ms. Esto **no equivale a una medición de porcentaje de CPU** en Banghó/SF20BA.

---

### 1.3 UtteranceCollector (Agrupador Temporal)
Ring buffer de pre-roll + acumulación de frames y verificación de timeout:

| Métrica | Valor |
| :--- | :--- |
| **Iteraciones** | 20000 |
| **Throughput** | **28,092.9 frames/segundo** |
| **Latencia promedio por frame** | **35.4 µs** |
| **Latencia p50** | 16.77 µs |
| **Latencia p95** | 28.25 µs |

---

### 1.4 AudioTurnGate (Half-Duplex Filtering)
Filtrado atómico y verificación de estado/cooldown acústico:

| Métrica | Valor |
| :--- | :--- |
| **Iteraciones** | 50000 |
| **Throughput** | **1,370,650.1 frames/segundo** |
| **Latencia promedio** | **0.58 µs** |

---

### 1.5 Pipeline Integrado (`AudioInteractionCoordinator`)
Ciclo completo de coordinación (TTS + bloqueo half-duplex + mouth sync + retorno a IDLE):

| Métrica | Valor |
| :--- | :--- |
| **Ciclos completos** | 1000 |
| **Throughput** | **1089.0 turnos/segundo** |
| **Tiempo por ciclo promedio** | **917.76 µs** (0.918 ms) |
| **Tiempo por ciclo p50** | 931.15 µs |
| **Tiempo por ciclo p95** | 1224.53 µs |

---

## 2. Estado de Motores Reales de Inferencia en Máquina DEV

| Motor | Componente | Estado de Detección | Estado de Benchmark |
| :--- | :--- | :--- | :--- |
| **Vosk** | STT | `DISABLED` (vosk not installed (optional dependency [stt-vosk])) | `NOT RUN (MODEL NOT CONFIGURED)` |
| **whisper.cpp** | STT | `DISABLED` (whisper.cpp binary not found: whisper-cli) | `NOT RUN (BINARY/MODEL NOT CONFIGURED)` |
| **Piper** | TTS | `DISABLED` (Piper binary not found: piper) | `NOT RUN (BINARY/MODEL NOT CONFIGURED)` |

*Nota:* Conforme a la política de seguridad y testing offline, los modelos neuronales reales no se descargan automáticamente en CI ni en tests normales. Cuando se instalen en el hardware objetivo (Banghó / SF20BA), se registrarán los tiempos reales de inferencia y RTF físico.
