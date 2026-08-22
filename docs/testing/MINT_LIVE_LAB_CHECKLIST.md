# Checklist de Primera Validación Física en Linux Mint (R3B.3)

Guía paso a paso para la primera sesión interactiva completa en la estación de desarrollo/laboratorio:

## 1. Verificación Preflight y Diagnóstico del Host

```bash
# Diagnóstico integral no invasivo de dependencias y estado
ailen lab doctor

# Verificación de dispositivos de audio y cámaras conectadas
ailen lab audio-devices
ailen lab cameras

# Preflight integral de preparación para prueba física en vivo
ailen lab preflight
```

## 2. Preparación de Configuración y Modelos de Voz (STT/TTS)

```bash
# Listar modelos y voces verificadas 2026
ailen speech list

# Generar archivo de configuración aislado de laboratorio (gitignored)
ailen lab config init

# Descargar y verificar modelos Vosk y Piper en ~/.local/share/ailen/speech/
ailen lab prepare-speech --yes
```

## 3. Preparación de Modelo LLM Local

```bash
# Inspeccionar estado del modelo local y runtimes
ailen lab prepare-ai

# Descargar/verificar modelo y ejecutar smoke-test temporal del runtime (opcional)
ailen lab prepare-ai --yes --start-runtime
```

## 4. Validación Preflight con Configuración de Laboratorio

```bash
# Evaluar preflight con la configuración aislada de laboratorio
ailen -c runtime/lab/ailen-lab.toml lab preflight
```

## 5. Prueba en Modo Simulación (Offline Verification)

```bash
# Inicializar con backends sintéticos para validar GUI y flujo sin periféricos
ailen lab start --simulate --duration 5
```

## 6. Prueba Físicamente Integrada en Vivo

Con micrófono, parlantes y cámara web USB conectados:

```bash
# Modo Dry-Run para verificar tabla de componentes sin entrar al loop
ailen -c runtime/lab/ailen-lab.toml lab start --dry-run

# Modo interactivo en vivo completo
ailen -c runtime/lab/ailen-lab.toml lab start
```

### Criterios de Aceptación:
1. **Face:** La ventana gráfica de rostro se inicializa en estado `IDLE` (o `ATTENTION` si se detecta presencia).
2. **Visión:** Al ubicarse frente a la cámara, el gaze orienta los ojos hacia el usuario y se emite saludo según `SocialEngine`.
3. **Audio VAD:** Al hablar, el estado pasa a `LISTENING`.
4. **STT:** Al terminar de hablar, se emite `TRANSCRIPT_READY` y el estado pasa a `PROCESSING`.
5. **AI:** El router determina destino (local Ollama / llama.cpp o reglas) y registra la latencia realmente observada. No se exige ni se declara un umbral de <1 s hasta medirlo.
6. **TTS:** Piper sintetiza la voz en español y ALSA reproduce el audio con movimiento de boca (`speech_level`).
7. **Cierre:** Al presionar `Ctrl+C`, se liberan todos los recursos, se detiene el runtime propio (si aplica) y se guarda el log de métricas en `runtime/lab/`.


## Prueba MIC-ONLY cuando no hay cámara

Esta prueba es válida como evidencia parcial y no requiere Tkinter, OpenCV, Piper ni LLM.

```bash
./.venv/bin/ailen lab audio-devices
./.venv/bin/ailen demo vad --device <CAPTURE_DEVICE> --duration 10
./.venv/bin/ailen demo stt --engine vosk --model ~/.local/share/ailen/speech/stt/vosk-model-small-es-0.42 --device <CAPTURE_DEVICE> --duration 15
```

No usar `--simulate` para una validación física. Si el micrófono no abre, VAD/STT deben fallar en vez de sustituirlo por audio sintético. `MIC PASS` requiere transcripción real.


## Evidencia registrada: G600 — MIC PASS

- [x] Hardware de captura detectado: `plughw:CARD=G600,DEV=0`
- [x] PipeWire source: `G600 Mono`
- [x] Señal de voz real detectada por VAD
- [x] Vosk produjo una transcripción real
- [x] Sin `--simulate`
- [ ] TTS/parlantes end-to-end
- [ ] Cámara/Vision/Face tracking

Resultado actual del laboratorio físico: **PARTIAL / MIC PASS**.
