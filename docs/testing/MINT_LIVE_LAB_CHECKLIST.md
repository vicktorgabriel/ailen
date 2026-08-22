# Checklist de Primera Validación Física en Linux Mint (R3B.3)

Guía paso a paso para la primera sesión interactiva completa en la estación de desarrollo/laboratorio:

## 1. Verificación Inicial de Dependencias y Hardware

```bash
# Diagnóstico integral de dependencias opcionales y estado del host
./.venv/bin/python -m ailen.cli lab doctor

# Salida estructurada JSON si se requiere para scripts
./.venv/bin/python -m ailen.cli lab doctor --json
```

## 2. Inspección y Planificación de Modelos

```bash
# Inspeccionar hardware, runtimes detectados y plan recomendado
./.venv/bin/python -m ailen.cli lab inspect

# Evaluar plan de modelos según propósito (SANITY, BALANCED, QUALITY)
./.venv/bin/python -m ailen.cli models plan --purpose SANITY
./.venv/bin/python -m ailen.cli models plan --purpose BALANCED
```

## 3. Preparación de Artefactos de IA

```bash
# Inspeccionar estado del modelo local y runtimes
./.venv/bin/python -m ailen.cli lab prepare-ai

# Descargar/verificar modelo y ejecutar smoke-test temporal del runtime (opcional)
./.venv/bin/python -m ailen.cli lab prepare-ai --yes --start-runtime
# El smoke-test se detiene al terminar; `ailen lab start` poseerá el runtime de la sesión.
```

## 4. Prueba en Modo Simulación (Offline Verification)

```bash
# Inicializar con backends sintéticos para validar GUI y flujo sin periféricos
./.venv/bin/python -m ailen.cli lab start --simulate --duration 5
```

## 5. Prueba Físicamente Integrada

Con micrófono, parlantes y cámara conectados:

```bash
# Modo Dry-Run para verificar tabla de componentes sin entrar al loop
./.venv/bin/python -m ailen.cli lab start --dry-run

# Modo interactivo en vivo
./.venv/bin/python -m ailen.cli lab start
```

### Criterios de Aceptación:
1. **Face:** La ventana gráfica de rostro se inicializa en estado `IDLE` (o `ATTENTION` si se detecta presencia).
2. **Visión:** Al ubicarse frente a la cámara, el gaze orienta los ojos hacia el usuario y se emite saludo según `SocialEngine`.
3. **Audio VAD:** Al hablar, el estado pasa a `LISTENING`.
4. **STT:** Al terminar de hablar, se emite `TRANSCRIPT_READY` y el estado pasa a `PROCESSING`.
5. **AI:** El router determina destino (local Ollama / llama.cpp o reglas) y registra la latencia realmente observada. No se exige ni se declara un umbral de <1 s hasta medirlo.
6. **TTS:** Piper sintetiza la voz en español y ALSA reproduce el audio con movimiento de boca (`speech_level`).
7. **Cierre:** Al presionar `Ctrl+C`, se liberan todos los recursos, se detiene el runtime propio (si aplica) y se guarda el log de métricas en `runtime/lab/`.
