# ADR-006 — Stack técnico inicial del prototipo

**Estado:** Proposed  
**Fecha:** 2026-08-21

## Contexto

El primer prototipo debe correr en Banghó Zero G05 con 8 GB y después degradarse a SF20BA. La elección del stack no debe basarse sólo en comodidad del equipo de desarrollo.

## Candidatos iniciales

### Core

Python es candidato fuerte por ecosistema de audio, visión, IA, SQLite y velocidad de prototipado, pero se debe medir memoria/base runtime.

### Web

Se busca un servidor ligero con HTML/CSS/JS responsive. Evitar SPA pesada si no aporta valor al panel local.

### Rostro

Comparar al menos:

- SDL2 sobre backend disponible;
- DRM/KMS directo si el soporte real es viable;
- X/Wayland mínimo como fallback de compatibilidad.

### STT/TTS

Seleccionar por benchmark en la Banghó, incluyendo RAM, latencia y calidad en español.

### LLM local

Mantener interfaz genérica y benchmarkear modelos pequeños cuantizados. El MVP no depende de un modelo concreto.

## Criterios para aceptar

- instalación reproducible en Debian 13 minimal;
- RAM idle razonable;
- compatibilidad con Banghó y SF20BA;
- mantenimiento activo;
- capacidad de empaquetado/release;
- ausencia de dependencia innecesaria de GPU;
- tests automatizables.

## Decisión

Pendiente de benchmark/POC. No implementar un stack como definitivo sin actualizar este ADR.

## Nota de implementación provisional (carril Web, 2026-08-21)

Para el skeleton del panel web se adoptó **stdlib pura de Python**
(`http.server.ThreadingHTTPServer` + plantillas HTML propias con sustitución
mínima + CSS/JS vanilla). Fundamento:

- cero dependencias nuevas mientras el stack no está cerrado;
- bajo consumo acorde al hardware objetivo;
- sin SPA (alineado con este ADR y ADR-005);
- tests ejecutables sin Internet.

Esta elección es **provisional y reemplazable**: la lógica vive en
`ailen.web.app.AILENWebApp` (request/response agnósticos de transporte), así
migrar a un framework ligero (Starlette/Flask/etc.) no reescribe handlers.
La decisión definitiva queda sujeta a benchmark en la Banghó y cierre de este ADR.

## Nota de implementación provisional (Face y Visión POC R2A, 2026-08-21)

1. **Rostro:**
   - Se separó la lógica de animación (`FaceAnimator`) y los modelos de pose (`FacePose`) de cualquier biblioteca gráfica.
   - Backend GUI POC: `TkinterFaceController` sin dependencia pip, pero requiere `python3-tk` y un stack gráfico del sistema. Es una elección provisional para validar contratos/render 2D; RAM/CPU y compatibilidad final de kiosk/appliance quedan pendientes de benchmark físico.
   - Backend Headless: `NullFaceController` permite operar sin renderer gráfico; su overhead exacto se medirá en hardware objetivo y no se declara como 0 MB.
   - Documentación de alternativas: `docs/research/FACE_BACKEND_POC.md`.

2. **Visión y Presencia:**
   - Detección de presencia basada en Haar cascades de OpenCV (`opencv-python-headless` como dependencia opcional `[vision]`), ejecutándose a baja resolución (320px) y 5 FPS.
   - `VisionDebouncer` desacopla la presencia instantánea de la presencia estable para evitar oscilaciones espurias.
   - Degrada a modo deshabilitado/simulado si la cámara o OpenCV no están presentes.
   - Documentación de alternativas: `docs/research/VISION_BACKEND_POC.md`.

## Nota de implementación provisional (Audio Local, VAD, STT y TTS POC R2B, 2026-08-21)

1. **Formato canónico y Audio I/O:**
   - Formato canónico: PCM 16-bit signed LE, mono, 16000 Hz.
   - Backend I/O por defecto en Debian 13 minimal: ALSA (`arecord` y `aplay` vía pipes de subprocess seguros con timeouts). Zero dependencias wheel en el Core.
   - Backends de prueba/simulación: `FakeAudioInputBackend` y `FakeAudioOutputBackend` para tests deterministas y entornos CI.
   - Documentación de investigación: `docs/research/AUDIO_IO_POC.md`.

2. **VAD y Utterance Collection (Half-Duplex):**
   - VAD liviano en Python puro (`EnergyVad`) calculando RMS sobre frames de 20 ms sin dependencias ML. El benchmark DEV mide latencia lógica, no porcentaje de CPU en hardware objetivo.
   - `UtteranceCollector` con defaults actuales de pre-roll 200 ms, mínimo de voz 250 ms, timeout de silencio 700 ms y corte máximo 15 s.
   - `AudioTurnGate` bloquea el camino normal de STT durante procesamiento/TTS y aplica settling cooldown. Un detector RMS separado puede pedir barge-in, cancelar `aplay` desde otro thread y conservar esos frames hasta que el turno anterior libere la compuerta.

3. **STT (Speech-to-Text):**
   - Backend local preferente inicial para perfiles ligeros: `VoskSttBackend` (`vosk` como extra opcional `[stt-vosk]`), pendiente de benchmark físico.
   - Backend alternativo: `WhisperCppSttBackend`, usando el CLI actual `whisper-cli` y modelos GGML/ggml compatibles; rendimiento real pendiente de benchmark.
   - Degrada limpiamente a `DISABLED`/`UNHEALTHY` si los binarios o modelos no están presentes.
   - Documentación de investigación: `docs/research/STT_BACKEND_POC.md`.

4. **TTS (Text-to-Speech) y Mouth Sync:**
   - Backend preferente POC: `PiperTtsBackend` usa exclusivamente la API Python `piper-tts`, conserva `PiperVoice` cargada y entrega PCM incremental. El fallback CLI/WAV temporal fue eliminado para mantener una sola ruta canónica.
   - La energía RMS de cada chunk limita la intensidad de habla. `FaceAnimator`
     deriva de ella una articulación temporal determinista y vuelve a 0.0 al
     finalizar. Es animación sincronizada con playback, no lip-sync fonémico.
   - `AudioInteractionCoordinator` integra el pipeline y emite eventos livianos (`VOICE_STARTED`, `VOICE_ENDED`, `SPEECH_CAPTURED`, `TRANSCRIPT_READY`, `SPEECH_STARTED`, `SPEECH_FINISHED`, `AUDIO_ERROR`) sin PCM.
   - Documentación de investigación: `docs/research/TTS_BACKEND_POC.md`.

## Nota de auditoría física ASRock — 2026-08-26

- PipeWire entregaba frames de 20 ms en ráfagas con p95 ~129 ms cuando `arecord`
  no fijaba período/buffer. Derivar `-F/-B` desde `frame_ms` dejó p95 22.66 ms
  sobre G600 sin cambiar de dispositivo ni de STT.
- El hangover de `EnergyVad` mantiene una frase ya iniciada, pero no cuenta como
  evidencia para alcanzar `min_speech_ms`. La prueba idle de 8 s pasó de una
  frase falsa a cero con la misma configuración física.
- El G600 observado emite pulsos idle repetidos (~0.012–0.023 RMS). Con threshold
  0.012 podían impedir 500 ms de silencio hasta el máximo de 15 s; el perfil Lab
  local en 0.022 terminó enunciados en 0.26–1.98 s. No se convierte en default:
  falta repetir sensibilidad de voz baja con un micrófono sano.
- `AudioOutputBackend.play` recibe el token de cancelación del turno. Se validó
  `stop()` con `aplay` PipeWire activo en 0.03–1.51 ms en harness y 0.2 ms durante
  conversación; los frames interrumpidos llegaron a Vosk como el transcript
  correcto. Esto es evidencia del ASRock, no un requisito extrapolable.
- `FaceAnimator` separa estado de interacción de gesto transitorio validado; un
  cambio a `SPEAKING` ya no borra inmediatamente una expresión explícita.
- En ASRock, el renderer pixel de 800x480 pasó de bloques planos de 13 px a una
  malla de 4 px con contornos de dos escalones, iris/pupila y paleta de tres tonos.
  La articulación mueve boca, mirada y cabeza aun bajo un gesto transitorio. Una
  demo aislada a 30 FPS midió 2.1% CPU de proceso y 25.9 MB RSS bajo la carga
  coexistente observada; no se extrapola a Banghó/SF20BA.
- La NC250 mantiene gestión HTTP, RTSP y detección como estados separados. En el
  firmware observado las respuestas FCGI pueden ser `JSON&&JSON`; el driver las
  valida por fragmento, confirma por lectura el modo aplicado y no marca la
  capacidad disponible por mera presencia de credenciales.
- Piper mantiene como máximo una oración prefetched mientras reproduce la actual.
  En la sesión integrada los chunks observados tuvieron `gap_ms=0`; en muestras
  aisladas, pausas previas de 1.36–1.43 s bajaron a ~13–219 ms. La cancelación no
  espera síntesis en vuelo y descarta su resultado; no existe lip-sync fonémico.
