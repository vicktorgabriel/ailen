# Estado actual — AILEN

**Fecha:** 2026-08-21  
**Versión:** `0.1.0-dev.0`  
**Fase:** R2B software POC integrado y auditado; Audio local + VAD + wrappers STT/TTS + Half-Duplex + nivel de boca básico sobre R1/R2A. Validación física de motores/modelos reales sigue pendiente. Próximo milestone: R3A AI Router híbrido.

## Qué existe

- carpeta del proyecto creada en `/mnt/hdd4tb/repo/ailen`;
- definición del producto;
- plan maestro;
- arquitectura inicial;
- roadmap hasta 1.0.0;
- changelog y versionado inicial;
- reglas para agentes y contribución;
- estructura documental inspirada en AndesKey;
- comportamiento del producto documentado (`PRODUCT_BEHAVIOR.md`);
- plan de implementación operativo (`IMPLEMENTATION_PLAN.md`);
- contratos entre módulos (`MODULE_CONTRACTS.md`);
- task board de R1, R2A y R2B (`TASKS.md`);
- handoff específico para Gemini/OpenCode/Codex (`AGENT_HANDOFF.md`);
- matriz de aceptación verificable (`ACCEPTANCE_MATRIX.md`);
- carpetas preparadas para código, pruebas, scripts, empaquetado y releases.

- Foundation/Core ejecutable (`pyproject.toml`, CLI `ailen`, versión unificada);
- Sistema de configuración tipado con `schema_version` y plantilla versionada (`config/ailen.example.toml`);
- Logging estructurado con redacción automática de secretos y tokens;
- Diagnóstico de hardware best-effort (`ailen diagnose hardware`) y recomendador de perfiles;
- RuntimeState y HealthService observables;
- EventBus in-memory ligero con suscripciones tipadas, aislamiento de errores y correlation IDs;
- SocialEngine determinista con modos sociales (`HOME`, `WORKSHOP`, `SHOP`, `PUBLIC`, `PRIVATE`, `SLEEP`), cooldown y deduplicación por sesión de presencia;
- `SocialPrivacyPolicy` determinista fuera del LLM con aislamiento inviolable de memorias privadas en `PUBLIC` y `SHOP`;
- `InteractionCoordinator` orquestando ciclo de presencia física, transiciones de estado, decisiones sociales y publicación de eventos;
- `PersonalityBoundary` con límites inviolables sobre seguridad, herramientas y privacidad;
- Panel web utilizable desde celular: `SettingsService` con allowlist de campos administrables, vista `/config` responsive (GET/POST con CSRF, validación server-side, guardado atómico del TOML), identidad del personaje configurable (`[identity].display_name`, voz) separada de la marca AILEN;
- Autenticación administrativa persistente por usuario + contraseña en SQLite (migración `0002_admin_credentials`, ADR-007): PBKDF2-HMAC-SHA256 con 600k iteraciones, salt aleatorio, comparación constant-time, lockout por IP, fail-closed sin credencial; CLI `ailen admin set-password` vía getpass;
- Hardening HTTP baseline del panel: límite de body (413), métodos permitidos (405), Content-Type exigido en POST (415), CSP/Referrer-Policy/no-store, timeout de socket; fallos de diagnóstico no tiran abajo el panel;
- SQLite endurecida con permisos owner-only (`0600`) en POSIX porque contiene memoria privada y credencial administrativa derivada;
- `SettingsService.update()` usa semántica de patch parcial; la Web traduce checkboxes HTML ausentes a `false`;
- Motor lógico de rostro `FaceAnimator` y modelo `FacePose` agnóstico de renderer, con parpadeo no periódico, micro-movimientos y apertura de boca;
- Baseline de despliegue aceptado en ADR-008: Debian 13 stable amd64 netinst/minimal, sin entorno de escritorio; con Tkinter se usa sólo Xorg/xinit/python3-tk y los nodos headless no instalan X;
- Backend gráfico POC `TkinterFaceController` (sin dependencia pip, requiere `python3-tk`/stack gráfico del sistema) y `NullFaceController` para headless; consumo real pendiente de benchmark físico;
- `VisionDebouncer` temporal para presencia física basado en `presence_debounce_seconds`;
- Backend de cámara POC `OpenCvVisionBackend` con Haar cascade a 5 FPS / 320px y degradación limpia;
- Formato canónico de audio: PCM 16-bit signed LE, mono, 16000 Hz (`src/ailen/audio/pcm.py`) con RMS matemático puro;
- VAD en Python puro (`EnergyVad`) con umbral configurable y hangover; benchmark lógico DEV documentado sin extrapolar porcentaje de CPU a hardware objetivo;
- `UtteranceCollector` con defaults actuales de pre-roll 200 ms, mínimo de habla 250 ms, silencio final 700 ms y corte máximo 15 s;
- Compuerta Half-Duplex `AudioTurnGate` con cooldown acústico para prevenir auto-transcripción y feedback de parlantes;
- Backends I/O reales ALSA (`AlsaAudioInputBackend`, `AlsaAudioOutputBackend`, `AlsaDeviceEnumerator`) y fakes para CI/tests;
- Backend STT local offline `VoskSttBackend` (extra `[stt-vosk]`) y alternativa `WhisperCppSttBackend` (`whisper-cli` actual, nombres legacy best-effort); no inventan confidence cuando el motor no lo provee;
- Backend TTS local offline `PiperTtsBackend` compatible con el CLI actual: WAV temporal, extracción de PCM/sample-rate/canales reales y control de velocidad/volumen;
- `AudioInteractionCoordinator` integrando micrófono, turn gate, VAD, STT, TTS y un nivel de boca RMS básico durante playback; lip-sync dinámico por chunks queda pendiente;
- Comandos CLI de audio: `ailen diagnose audio`, `ailen demo vad`, `ailen demo stt`, `ailen demo tts`;
- Suite de benchmark reproducible (`tools/benchmark_audio.py`) y reporte en `docs/benchmarks/dev_audio_benchmark.md` con tag `DEV MACHINE — NO HARDWARE TARGET`;
- Suite auditada en R2B: 213 tests pasando tras correcciones de robustez; `ruff`, `mypy`, `git diff --check` y build del wheel validados en verde antes del commit.

## Qué NO existe todavía

- backend gráfico de producción nativo DRM/KMS para appliance sin X11 (actualmente POC Tkinter + Headless);
- AI Router / integración LLM local o cloud real;
- LAN Brain;
- updater;
- benchmarks físicos en hardware objetivo (Banghó Zero G05 / SF20BA).

## Hardware objetivo inmediato

### Prototipo

Banghó Zero G05:

- 8 GB RAM;
- M.2 500 GB;
- pantalla/cámara/audio integrados disponibles para el prototipo.

### Laboratorio

Ryzen 5 5500 + 48 GB DDR4 + RTX 3060 12 GB VRAM para pruebas de modelos y benchmarks de referencia.

### Próximos objetivos

1. SF20BA 8 GB;
2. SF20BA 4 GB;
3. equipos 2 GB en modo Satellite/Cloud;
4. placas con pantalla rota usando monitor externo o modo sin pantalla.

## Próxima decisión técnica

Cerrar `ADR-006` o usarlo explícitamente como baseline provisional antes de integrar dependencias que condicionen el producto. Debe resolver mediante POC/benchmark:

- lenguaje/core;
- framework web;
- backend gráfico del rostro;
- STT/TTS baseline;
- persistencia;
- cómo encapsular proveedores LLM.

La base Foundation/Core/Web, Face/Vision y el slice software de Audio/VAD/STT/TTS ya están integrados. Tras cerrar esta auditoría, el siguiente trabajo pasa a R3: AI Router híbrido, proveedores y contexto/memoria, manteniendo backends intercambiables.

## Próximo milestone

`R3 — AI Router híbrido: reglas/local/LAN/cloud + contexto mínimo`, sin convertir todavía ningún proveedor o modelo en dependencia obligatoria.

Trabajo inmediato definido en `TASKS.md` y `docs/operations/AGENT_HANDOFF.md`.

El repositorio Git local está inicializado en `main` y conectado a `git@github.com:vicktorgabriel/ailen.git`. Commits existentes: fundación `84906c5` y R2A Face/Vision `86b36a7`. R2B se commitea sólo después de cerrar esta auditoría. No se hace push sin autorización explícita.

## Riesgos conocidos

- latencia y consumo real en SF20BA aún desconocidos;
- compatibilidad gráfica sin X/Wayland aún no validada;
- STT/TTS óptimos por perfil aún no medidos;
- costo cloud estimado pero aún no medido con tráfico real;
- nombre `AILEN` fijado para proyecto/plataforma; queda pendiente sólo la verificación marcaria/legal antes de comercialización formal;
- soporte de equipos de 2 GB sujeto a pruebas reales.
