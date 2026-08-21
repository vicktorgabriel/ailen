# POC e Investigación de Audio I/O — AILEN R2B

**Fecha:** 2026-08-21  
**Estado:** Evaluado / POC implementado  
**Hardware de referencia para análisis:** Debian 13 minimal en Banghó Zero G05 (8 GB) y SF20BA (4 GB / 8 GB).

---

## 1. Contexto y Objetivos

Para operar como asistente interactivo local, AILEN requiere:
1. **Captura de audio (Input):** Adquirir PCM mono a 16 kHz en frames pequeños (ej. 20 ms / 640 bytes) para alimentar el VAD y STT con baja latencia.
2. **Reproducción de audio (Output):** Emitir audio sintetizado (PCM/WAV) a los parlantes o salida de audio.
3. **Enumeración de dispositivos:** Listar interfaces de entrada y salida disponibles para diagnóstico y configuración desde el panel web.
4. **Bajo consumo y cero dependencias pesadas:** Evitar servidores de audio complejos o wrappers pesados que comprometan la RAM en equipos de 4 GB o menos.

---

## 2. Opciones Evaluadas

| Opción | Mecanismo | Dependencias / Paquetes | RAM Overhead | Latencia | Viabilidad en Debian 13 minimal |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **ALSA nativo (`arecord` / `aplay`)** | Subprocesos CLI estándar ALSA | `alsa-utils` (sistema) | **NO MEDIDO** | **NO MEDIDO** | **Seleccionado para POC.** Está disponible en Debian sin introducir bindings Python de audio. |
| **`sounddevice` (PortAudio)** | CFFI sobre `libportaudio2` | `python3-sounddevice`, `libportaudio2` | **NO MEDIDO** | **NO MEDIDO** | Alternativa si ALSA por procesos resulta insuficiente en los benchmarks físicos. |
| **`PyAudio` (PortAudio)** | Extensiones C Python | `python3-pyaudio` | **NO MEDIDO** | **NO MEDIDO** | Alternativa, con mayor costo de empaquetado/ABI que el POC ALSA. |
| **`soundcard` / stack Pulse/PipeWire** | Capa de audio de escritorio | Dependencias adicionales | **NO MEDIDO** | **NO MEDIDO** | No elegida para el appliance mínimo; puede reevaluarse si aparece un caso de uso concreto. |
| **Null / Fake Audio Backend** | In-memory synthetic | Ninguna | No atribuida de forma aislada | N/A | **Canónico para tests.** Permite CI y ejecución sin hardware de audio. |

---

## 3. Decisión Técnica para el POC

1. **Abstracción por Contratos:**
   - Se definen `AudioInputBackend`, `AudioOutputBackend` y `AudioDeviceEnumerator` en `src/ailen/audio/contracts.py`.
   - Ninguna parte del Core ni de la lógica de diálogo depende de ALSA ni de PortAudio.

2. **Backend Real POC:**
   - **`AlsaAudioInputBackend` y `AlsaAudioOutputBackend`:** Implementados utilizando pipes de `subprocess` seguros (`shell=False`, argv estricto) contra `arecord` y `aplay`.
   - Si `alsa-utils` o las placas de sonido no están disponibles, degradan limpiamente a `ServiceStatus.DISABLED` o `UNHEALTHY` sin lanzar excepciones no controladas.
   - Soporta enumeración mediante parsing de `arecord -L` / `aplay -L`.

3. **Backend Fake / Headless:**
   - `FakeAudioInputBackend` y `FakeAudioOutputBackend` para ejecución de tests, benchmarks sintéticos y operación en servidores/contenedores.

4. **Formato Canónico:**
   - **Formato:** PCM Signed 16-bit Little Endian (`s16le`).
   - **Canales:** 1 (Mono).
   - **Frecuencia de muestreo:** 16.000 Hz (16 kHz).
   - **Frame duration:** 20 ms (320 muestras = 640 bytes por frame).
