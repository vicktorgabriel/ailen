# FIRST_PHYSICAL_LAB_REPORT.md — Informe de Primera Validación Física de Laboratorio

> **Host Canónico:** Asrock (Linux Mint 22.3, AMD Ryzen 5 5500, 48 GB RAM, NVIDIA RTX 3060 12 GB)
> **Fecha:** 23 de Agosto de 2026
> **Estado de Ejecución:** `PARTIAL / AUDIO CONVERSATION PASS + YUNET FACE DETECTION PASS`
> **Veredicto:** `AUDIO CONVERSATION PASS` + `YUNET FACE DETECTION PASS`; visión semántica/objetos aún no implementados — G600 validado end-to-end y webcam reciclada validada físicamente para presencia/gaze. Face GUI Tkinter ya abre; quedan STT y calidad de cámara como frentes de mejora.

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
| **Vision Library** | OpenCV 4.14.0 en `.venv` | `PASS` | Haar frontal + profile fallback operativos. OpenCV 5 queda excluido mientras este backend dependa de CascadeClassifier. |
| **Cámaras Físicas** | Webcam reciclada de notebook vía USB: `/dev/video1` + endpoint secundario `/dev/video2` | `PASS` | `/dev/video1` es el stream capturable; AILEN lo auto-selecciona si `/dev/video0` no existe. |
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

Tkinter/Face GUI ya quedaron disponibles posteriormente; cámara YuNet, voz y GUI están integradas en Lab. El frente pendiente es calidad STT y repetir con mejor cámara.
---

## 8. Resultado físico VISION PRESENCE PASS — 23 de agosto de 2026

**Estado:** `EXPERIMENTAL` para Vision. La cámara funciona, pero Haar/profile mostró falsos positivos y no demuestra rostro fiable. Face GUI abre correctamente con Tkinter.

Periférico validado:

- Webcam reciclada de notebook convertida a USB.
- Nombre V4L2 observado: `HD Webcam: HD Webcam`.
- Endpoints detectados: `/dev/video1` y `/dev/video2`.
- Stream real capturable: `/dev/video1`, 640×480.
- `/dev/video2` no abre como stream de captura y el demo falla correctamente en ese caso.

Correcciones necesarias encontradas durante la validación:

1. `opencv-python-headless 5.0.0.93` ya no expone el Haar `CascadeClassifier` usado por este POC; el extra `[vision]` queda limitado a OpenCV 4.x mientras permanezca esta implementación.
2. El preflight ahora valida `CascadeClassifier` y el archivo Haar real, no sólo `import cv2`.
3. `demo vision` falla con código no-cero cuando el backend no está `HEALTHY`.
4. La factoría auto-selecciona una cámara V4L2 detectada si la ruta configurada (por defecto `/dev/video0`) no existe. En Asrock eligió `/dev/video1` automáticamente.
5. Históricamente se probó `profileface` como fallback; fue retirado posteriormente por falsos positivos. Haar queda experimental y YuNet es el detector preferido del Lab.
6. `VisionDebouncer` usa histéresis para tolerar misses cortos del detector sin perder una presencia real, y conserva una ventana más larga para confirmar ausencia.
7. `PRESENCE_DETECTED` / `PRESENCE_LOST` representan transiciones reales, no cada observación de cámara.

Evidencia física:

- `ailen demo vision --camera /dev/video1` abrió el backend como `HEALTHY`.
- Se observó `Raw present=True`, `Caras: 1` y posteriormente `Debounced present=True`.
- El gaze cambió durante movimiento del operador (por ejemplo de aprox. `(+0.22,+0.33)` a `(+0.75,-0.16)`), demostrando seguimiento espacial y no sólo una detección estática.
- `ailen lab start --headless` arrancó con Vision `READY` usando `/dev/video1` auto-seleccionado.
- Sesión física `runtime/lab/session_1787457458.json`: 211 observaciones y **2 transiciones reales de presencia** en 12.34 s.
- Sin `--simulate`.

Calidad posterior a las correcciones: **432 tests**, Ruff limpio, mypy limpio sobre 126 archivos fuente y `git diff --check` limpio.

Este punto quedó resuelto posteriormente: `tkinter` está instalado y Face GUI abre en el Lab.

### Revisión del veredicto Vision — 23 de agosto de 2026

Una prueba controlada de 30 s con Haar produjo 25/60 detecciones raw (41.7%), 33/60 presencia estable (55.0%) y 4 transiciones. El patrón incluyó detecciones incompatibles con una interpretación segura de "rostro" durante el tramo sin persona, por lo que se retira el `VISION PRESENCE PASS`. Haar queda sólo como detector experimental/ultraliviano.

Se inició evaluación de OpenCV YuNet (`FaceDetectorYN`) como detector facial moderno. En una primera muestra física con el operador presente, YuNet produjo detección estable con score ~0.91-0.93, pero requiere todavía un control negativo con cámara vacía antes de promoverlo a baseline.

Hasta completar ese control, el LLM no debe afirmar que "ve" o "detecta" al usuario basándose en Haar.

### YuNet FACE DETECTION PASS — 23 de agosto de 2026

**Estado:** `PASS` para detección facial y posición aproximada con YuNet en la webcam reciclada actual. No implica reconocimiento de identidad, objetos ni comprensión de escena.

Prueba controlada de 30 s con OpenCV YuNet (`FaceDetectorYN`) y umbral 0.8:

- tramo inicial sin persona: 0 detecciones durante ~11 s;
- al entrar el operador: detecciones continuas con `confidence` ~0.92-0.95;
- desplazamiento espacial observado en gaze, incluyendo rango aproximado `x=[-0.58,+0.88]`, `y=[-0.62,-0.02]`;
- pérdida de detección al salir del encuadre / degradarse el ángulo y recuperación posterior con confidence alto;
- resumen total de la secuencia: 30/60 detecciones raw (50%) y 30/60 presencia estable (50%), coherente con una prueba que incluyó segmentos sin persona y segmentos con rostro presente.

Condiciones de prueba: noche, iluminación artificial, webcam HD reciclada de notebook convertida a USB. Estas condiciones pueden aumentar ruido, exposición lenta y motion blur, por lo que la estabilidad en movimiento no se considera baseline final de cámara.

Veredicto: YuNet sí proporciona evidencia suficiente de **rostro real** y posición aproximada. La cámara actual queda aceptada para desarrollo; se recomienda repetir el benchmark con una cámara reciclada de mejor calidad para comparar estabilidad en baja luz y movimiento.

### Benchmarks reproducibles Vision + STT — 23 de agosto de 2026

Nueva herramienta de medición: `ailen lab benchmark-vision` y `ailen lab benchmark-stt`. Ambas CPU-first, sin GUI, sin persistencia de frames ni audio (salvo `--record` con autorización explícita), sin descargas automáticas.

#### benchmark-vision — host Ryzen 5 5500 (CPU puro, 640x480, 5 FPS)

- **YuNet** (`face_detection_yunet_2023mar.onnx`, sha256 `8f2383e4...52fa4`, umbral 0.8), fase `face`, 60 frames:
  - detecciones: 60/60 (100%);
  - latencia avg 49.0 ms / p50 50.9 ms / p95 91.1 ms / max 159.1 ms;
  - confianza avg 0.910 / min 0.887; gaze x [+0.74,+0.85], y [-0.24,-0.22];
  - veredicto: apto a 5 FPS en CPU; confirma la medición previa de ~56.7 ms en Asrock. La RTX 3060 no es requisito.
- **Haar** (experimental), fase `face`, 40 frames: 40/40 con rostro presente, pero avg 67.3 ms con picos >500 ms y sin confianza calibrada. Sigue sin habilitar afirmaciones visuales del LLM.
- Reportes JSON en `runtime/lab/vision_benchmarks/`. La fase es etiqueta del operador (`--phase uncontrolled|empty|face|movement`); el sistema no infiere falsos positivos automáticamente.

#### benchmark-stt — utterance Piper pasada por el mismo WAV

Utterance sintetizada con Piper (`es_ES-davefx-medium`): "Detecto un rostro frente a la cámara." convertida a WAV 16 kHz mono PCM16 y evaluada contra esa referencia:

- **Vosk small-es 0.42**: OK; transcripto "detectó un rostro frente a la cámara"; WER 0.143 (1 error / 7 palabras); latencia ~407 ms.
  - Muestra real del problema de calidad de Vosk en español (confusión de acentos/tildes; casos observados previos: "AILEN" -> "Hayden").
- **whisper.cpp**: `NOT_INSTALLED` (binario `whisper-cli` y modelos ggml `whisper-ggml-tiny`/`base` ausentes). Sin descarga automática; queda listo para prueba física cuando el operador instale los assets.

Uso recomendado para comparativa completa: instalar whisper.cpp + ggml base, grabar utterances reales del micrófono G600 con `--record N --out /ruta.wav`, correr `--engines vosk,whisper_cpp --reference "..."` y decidir migración de STT con WER medido, no impresiones.

### Auditoría post-oX Alpha — 23 de agosto de 2026

- Preflight actual: Face GUI, YuNet, audio, Vosk, Piper y Ollama `READY_FOR_LIVE_TEST`.
- `benchmark-vision` auto-selecciona la cámara real como el Lab y ya no clona métricas de frames no observados. En fase `uncontrolled` (sin ground truth) una muestra de 20 frames produjo 13 detecciones, confidence media 0.853 y ~9.8 ms de inferencia promedio; estos valores describen rendimiento, no accuracy.
- Persistencia de conversación quedó cableada en producción: sesión SQLite `sess-*`, turnos user/assistant y cierre de `ended_at`.
- Vosk continúa como principal limitación perceptible; Whisper.cpp sigue `NOT_INSTALLED` y no se descargó durante esta auditoría.
