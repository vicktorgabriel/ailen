# FIRST_PHYSICAL_LAB_REPORT.md — Informe de Primera Validación Física de Laboratorio

> **Host Canónico:** Asrock (Linux Mint 22.3, AMD Ryzen 5 5500, 48 GB RAM, NVIDIA RTX 3060 12 GB)
> **Fecha:** 22 de Agosto de 2026
> **Estado de Ejecución:** `PARTIAL / AUDIO CONVERSATION PASS`
> **Veredicto:** `AUDIO CONVERSATION PASS` — G600 validado físicamente end-to-end: micrófono, VAD, Vosk, Ollama local, Piper y reproducción por auricular. Face/Vision continúan pendientes por falta de cámara.

---

## 1. Resumen Ejecutivo

Durante la ronda **R3B.3**, se completó la infraestructura completa de preparación, catalogación y validación física previa (`preflight`) para el modo laboratorio en Linux Mint.

Se implementó el catálogo declarativo criptográficamente verificado de modelos de habla (`SpeechAssetCatalog`, `SpeechAssetStore`, `SpeechAssetDownloader`) y el verificador integral de preparación física `LabPreflightChecker`.

Al ejecutar la validación previa en el host real, el sistema detectó correctamente los componentes listos y bloqueó de forma segura la ejecución física interactiva (`fail-closed`), reportando con precisión qué dependencias y dispositivos faltan antes de iniciar la interacción en vivo.

---

## 2. Diagnóstico de Hardware y Entorno en Host Asrock

| Componente | Estado Detectado | Veredicto Preflight | Detalle / Acción Requerida |
| :--- | :--- | :--- | :--- |
| **CPU / RAM** | Ryzen 5 5500 (12 threads) / 48 GB RAM | `PASS` | Capacidad plena para LLM local, STT y TTS. |
| **GPU / VRAM** | NVIDIA RTX 3060 12 GB (CUDA compute 8.6) | `PASS` | Aceleración por GPU disponible para inferencia local. |
| **Local LLM Runtime** | Ollama activo en `http://127.0.0.1:11434/v1` (11 modelos) | `PASS` | Endpoint OpenAI-compatible respondiendo correctamente. |
| **Audio Capture** | 2 endpoints hardware ALSA (`ALC892 Analog` / `Alt Analog`) | `PREFLIGHT` | `arecord -l` confirma hardware de captura; una señal real sólo se considera PASS tras VAD/STT. |
| **Audio Playback** | 66 dispositivos ALSA detectados (`Generic_1`, HDMI) | `PASS` | Controladores ALSA listos; altavoces/auriculares pendientes. |
| **Face GUI** | `python3-tk` no instalado en el sistema operativo | `FAIL` | Instalar `python3-tk` o ejecutar con `--headless`. |
| **Vision Library** | `opencv-python` no instalado en `.venv` | `FAIL` | Instalar opcional `.[vision]` en el entorno virtual. |
| **Cámaras Físicas** | 0 cámaras V4L2 conectadas | `FAIL` | Conectar cámara web USB o ejecutar con `--no-camera`. |
| **STT Engine (Vosk)** | Módulo `vosk` y modelo en disco no instalados | `FAIL` | Instalar `.[stt-vosk]` y descargar modelo vía `ailen lab prepare-speech`. |
| **TTS Binary (Piper)** | Binario `piper` no presente en PATH | `FAIL` | Instalar binario `piper` en `~/.local/bin/piper`. |

---

## 3. Salida de Preflight Real en Host

```text
============================================================
AILEN — LIVE LAB PREFLIGHT READINESS CHECK
============================================================

[FAIL]   [REQ] Face GUI                 python3-tk missing; GUI face cannot render
         -> Remediation: Run: sudo apt install python3-tk (or pass --headless)
[FAIL]   [REQ] Vision Library           opencv-python not installed in .venv
         -> Remediation: Run: ./.venv/bin/pip install -e '.[vision]'
[PASS]   [REQ] Audio Input              23 input device(s) found (default: 'default')
[PASS]   [REQ] Audio Output             66 output device(s) found (default: 'default')
[FAIL]   [REQ] STT Engine (Vosk)        vosk package not installed in .venv
         -> Remediation: Run: ./.venv/bin/pip install -e '.[stt-vosk]'
[FAIL]   [REQ] TTS Binary (Piper)       piper executable not found in PATH
         -> Remediation: Install Piper binary in PATH (e.g. ~/.local/bin/piper)
[PASS]   [REQ] Local AI Runtime         Runtime active at http://127.0.0.1:11434/v1 (Endpoint responsive (11 models loaded))

------------------------------------------------------------
PREFLIGHT RESULT: NOT_READY_FOR_LIVE_TEST
------------------------------------------------------------

[!] System is NOT ready for live physical test. Missing required items: Face GUI, Vision Library, STT Engine (Vosk), TTS Binary (Piper)
```

---

## 4. Guía de Remediación Paso a Paso para el Operador

Para completar la primera prueba física interactiva cuando el usuario esté listo:

### Paso 1: Instalar dependencias del sistema y entorno
```bash
# 1. Instalar soporte gráfico Tkinter para el rostro interactivo
sudo apt install python3-tk

# 2. Instalar dependencias opcionales de visión y STT en el virtualenv
./.venv/bin/pip install -e '.[vision,stt-vosk]'

# 3. Instalar binario Piper TTS (ej. en ~/.local/bin/piper)
# Descargar binario oficial de Piper release para linux_x86_64
```

### Paso 2: Descargar modelos de habla verificados
```bash
# Inicializar configuración aislada de laboratorio
ailen lab config init

# Descargar y verificar modelos Vosk y Piper
ailen lab prepare-speech --yes
```

### Paso 3: Conectar periféricos físicos
1. Conectar cámara web USB (verificar con `ailen lab cameras` -> `/dev/video0`).
2. Conectar micrófono y parlantes (verificar con `ailen lab audio-devices`).

### Paso 4: Re-ejecutar Preflight y arrancar Laboratorio
```bash
# Re-verificar preflight
ailen -c runtime/lab/ailen-lab.toml lab preflight

# Si el resultado es READY_FOR_LIVE_TEST, iniciar la sesión interactiva:
ailen -c runtime/lab/ailen-lab.toml lab start
```


---

## 5. Validación parcial MIC-ONLY (sin cámara)

La ausencia de cámara **no bloquea** esta prueba. El objetivo es validar únicamente:

`micrófono físico -> ALSA -> VAD -> Vosk -> transcripción real`

Criterios:

1. `ailen lab audio-devices` debe mostrar un endpoint `plughw` de captura real.
2. `ailen demo vad` debe reaccionar al hablar y no usar `--simulate`.
3. `ailen demo stt --engine vosk` debe producir una transcripción real.
4. Si el dispositivo no abre, la demo debe FALLAR; no existe fallback sintético automático.
5. Cámara, Face, Piper, parlantes y LLM quedan `SKIP` para este subtest.

El informe sólo puede marcar `MIC PASS` después de observar una transcripción proveniente del micrófono real.


---

## 6. Resultado físico MIC PASS — 21 de agosto de 2026

**Estado:** `PASS`

Periférico validado:

- Dispositivo: **G600 USB Audio**
- ALSA capture endpoint: `plughw:CARD=G600,DEV=0`
- ALSA playback endpoint: `plughw:CARD=G600,DEV=0`
- PipeWire source observado: `G600 Mono`
- PipeWire sink observado: `G600 Estéreo analógico`

Cadena validada físicamente:

`G600 mic -> ALSA -> PCM -> Energy VAD -> utterance segmentation -> Vosk STT -> transcript`

Evidencia operativa reportada durante la prueba:

- El G600 fue detectado como hardware físico de captura.
- El micrófono entregó señal real.
- VAD respondió a la voz del operador.
- Vosk produjo transcripción real.
- No se utilizó `--simulate`.

Con esto, el criterio **MIC PASS** queda cerrado. La validación completa del asistente sigue en estado `PARTIAL` hasta probar TTS/parlantes end-to-end y, cuando haya cámara disponible, Vision/Face tracking.
---

## 7. Resultado físico AUDIO CONVERSATION PASS — 22 de agosto de 2026

**Estado:** `PASS` para el pipeline de voz; validación global del laboratorio permanece `PARTIAL` por ausencia de cámara/Face.

Cadena observada físicamente sin simulación:

`G600 mic -> PipeWire/ALSA -> Energy VAD -> Vosk STT -> RuleBasedRouter -> Ollama qwen3.5:9b -> Piper -> PipeWire -> G600 auricular`

Evidencia de la sesión estable posterior a las correcciones:

- múltiples turnos consecutivos reconocidos y respondidos por voz;
- STT típico en aproximadamente 0.24–0.86 s en la muestra reportada;
- inferencia qwen3.5:9b con thinking desactivado, mayoría de turnos por debajo de 1 s una vez caliente;
- PipeWire permite captura y reproducción sin la exclusión de dispositivo observada con `plughw`;
- el gate bloquea entrada durante PROCESSING/TTS para evitar autoescucha;
- el texto enviado a TTS se normaliza para no leer Markdown, URLs ni decoración simbólica;
- no se utilizaron fakes ni `--simulate`.

Queda pendiente para completar la validación física global: cámara, seguimiento visual y Face GUI.
