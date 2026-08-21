# Task Board — AILEN

> Fuente operativa de trabajo inmediato. No reemplaza `ROADMAP.md`.

## Estado general

Versión: `0.1.0-dev.0`

Milestone activo: `R3A — AI Router híbrido y proveedores`.

Los slices de software de R1, R2A y R2B quedaron integrados y auditados. R2B cerró con 213 tests verdes antes de su commit.

## Bloque 0 — Antes de código

- [x] Producto documentado.
- [x] Comportamiento documentado.
- [x] Arquitectura base documentada.
- [x] Contratos de módulos documentados.
- [x] Plan de implementación documentado.
- [x] Handoff para agentes documentado.
- [x] Nombre del proyecto/plataforma fijado: `AILEN`.
- [x] Repo Git local inicializado en `main`.
- [x] Remoto `origin` configurado: `git@github.com:vicktorgabriel/ailen.git`.
- [ ] ADR-006 cerrado o aceptado como baseline provisional.

## Bloque 1 — Foundation/Core

### Alta prioridad

- [x] `pyproject.toml`.
- [x] paquete `src/ailen` importable.
- [x] `__main__.py`.
- [x] CLI `ailen --help`.
- [x] lectura de `VERSION`/versión centralizada.
- [x] estructura de módulos inicial.
- [x] modelos básicos de dominio.
- [x] configuración con `schema_version`.
- [x] `config/ailen.example.toml` o equivalente.
- [x] logging estructurado/redactado.
- [x] `RuntimeState`.
- [x] health service.
- [x] tests de foundation.

### Hardware diagnostics

- [x] `ailen diagnose hardware`.
- [x] CPU/arquitectura.
- [x] RAM.
- [x] disco.
- [x] GPU best-effort.
- [x] audio input/output.
- [x] cámaras.
- [x] displays.
- [x] red.
- [x] OS/kernel.
- [x] salida JSON opcional.

## Bloque 2 — Persistencia

- [x] SQLite connection manager.
- [x] migración `0001`.
- [x] `schema_meta`.
- [x] `sessions`.
- [x] `messages`.
- [x] `memories`.
- [x] `business_facts`.
- [x] `preferences`.
- [x] `personality_state`.
- [x] `personality_events`.
- [x] `tool_events`.
- [x] `ai_usage`.
- [x] `system_events`.
- [x] FTS5 si está disponible.
- [x] tests de migración.

## Bloque 3 — Web skeleton

- [x] servidor web ligero.
- [x] layout responsive.
- [x] login/logout.
- [x] auth service.
- [x] dashboard mínimo.
- [x] status API/service.
- [x] vista config básica.
- [x] manejo de errores.
- [x] tests web sin Internet.
- [x] `SettingsService` con allowlist explícita de campos administrables.
- [x] guardado de configuración atómico (temp + `os.replace`).
- [x] sección identidad del personaje (`display_name`, voz) separada de la marca AILEN.
- [x] auth persistente en SQLite (migración 0002) con PBKDF2/salt/lockout.
- [x] CLI `ailen admin set-password` vía getpass (sin password en argv).
- [x] hardening HTTP baseline: límite de body, métodos permitidos, CSP/referrer headers, timeout de socket.
- [ ] sesiones persistentes (hoy efímeras en memoria; deuda aceptada).
- [ ] smoke HTTP periódico en CI (hoy test manual local incluido).

## Bloque 4 — Contratos y mocks

- [x] `AiBackend` protocol/interface.
- [x] fake AI backend.
- [x] `VisionBackend` interface.
- [x] fake vision backend.
- [x] `SttBackend` interface.
- [x] fake STT backend.
- [x] `TtsBackend` interface.
- [x] fake TTS backend.
- [x] Tool protocol.
- [x] fake tools.
- [x] Router models.
- [x] tests de contratos.

## Bloque 5 — Core event/state

- [x] event model.
- [x] correlation IDs.
- [x] assistant state enum.
- [x] state transitions.
- [x] EventBus ligero con aislamiento de errores.
- [x] Social Engine baseline.
- [x] cooldown de saludo.
- [x] reglas `PUBLIC/PRIVATE` deterministas fuera del LLM.
- [x] Interaction Coordinator baseline.
- [x] Personality boundary & safety constraints.
- [x] tests de eventos, privacidad, social y coordinación.

## Bloque 6 — Primer slice integrable

Debe quedar funcionando:

- [x] `ailen --help`.
- [x] `ailen diagnose hardware`.
- [x] `ailen serve` integrado con panel web local.
- [x] dashboard local.
- [x] config validada.
- [x] runtime state visible.
- [x] SQLite creado/migrado.
- [x] backends fake disponibles.
- [x] tests verdes.
- [x] documentación actualizada.

## Bloque 7 — Investigación / POC R2A

- [x] comparar/evaluar backend Face liviano y documentar resultado (`docs/research/FACE_BACKEND_POC.md`).
- [x] comparar/evaluar backend Vision liviano y documentar resultado (`docs/research/VISION_BACKEND_POC.md`).
- [x] Face Animator agnóstico de renderer con poses normalizadas (`FacePose`).
- [x] Face Renderer GUI POC (`TkinterFaceController`) y Headless (`NullFaceController`).
- [x] Vision Debouncer temporal para presencia física.
- [x] Vision real POC con Haar cascades (`OpenCvVisionBackend`) opcional y degradable.
- [x] Integración de presencia y mirada con `InteractionCoordinator`.
- [x] Demos CLI `ailen demo face` y `ailen demo vision`.
- [x] Benchmark reproducible del pipeline lógico en DEV machine (`docs/benchmarks/dev_presence_benchmark.md`).
- [ ] benchmark físico del renderer Tkinter en Banghó/SF20BA.
- [ ] benchmark físico de OpenCV/cámara en Banghó/SF20BA.
- [ ] benchmark STT español en hardware objetivo.
- [ ] benchmark TTS español en hardware objetivo.
- [ ] benchmark VAD/wake word en hardware objetivo.
- [ ] benchmark LLM local pequeño en hardware objetivo.
- [ ] medir baseline RAM Python/runtime en Banghó cuando esté disponible físicamente.

## Bloque 8 — Audio Local, VAD, STT y TTS (R2B)

- [x] Formato canónico de audio: PCM 16-bit signed LE, mono, 16000 Hz (`src/ailen/audio/pcm.py`).
- [x] Contratos y dataclasses de audio I/O, VAD, STT y TTS (`src/ailen/audio/contracts.py`).
- [x] VAD liviano en Python puro con cálculo de RMS y hangover (`EnergyVad`).
- [x] `UtteranceCollector` con pre-roll buffer, umbral mínimo de voz y timeout de silencio.
- [x] `AudioTurnGate` con compuerta Half-Duplex y cooldown acústico para evitar feedback de parlantes.
- [x] Backends reales ALSA (`AlsaAudioInputBackend`, `AlsaAudioOutputBackend`, `AlsaDeviceEnumerator`).
- [x] Backends simulados para CI y headless (`FakeAudioInputBackend`, `FakeAudioOutputBackend`, `FakeSttBackend`, `FakeTtsBackend`).
- [x] Wrappers STT offline (`VoskSttBackend` y `WhisperCppSttBackend`) con degradación limpia; benchmark real de modelos sigue pendiente.
- [x] Wrapper TTS offline `PiperTtsBackend` compatible con el CLI actual; benchmark real de voces/modelos sigue pendiente.
- [x] `AudioInteractionCoordinator` integrando captura, compuerta half-duplex, VAD, STT, TTS y publicación en `EventBus`.
- [x] Comandos CLI `ailen diagnose audio`, `ailen demo vad`, `ailen demo stt`, `ailen demo tts`.
- [x] Benchmark reproducible de audio y VAD en DEV machine (`docs/benchmarks/dev_audio_benchmark.md`).
- [x] Documentos de investigación (`docs/research/AUDIO_IO_POC.md`, `docs/research/STT_BACKEND_POC.md`, `docs/research/TTS_BACKEND_POC.md`).

## Bloque 9 — Próximos pasos (R3A / AI Router híbrido)

- [ ] AI Router v1 con rutas `RULE_ONLY`, `LOCAL`, `LAN`, `CLOUD` y fallback explícito.
- [ ] Cloud provider rápido/económico detrás de contrato genérico, sin acoplar identidad al proveedor.
- [ ] Local LLM backend mediante proceso/HTTP local intercambiable (llama.cpp/Ollama como candidatos, no dependencia obligatoria).
- [ ] LAN Brain backend opcional con health/timeout/fallback.
- [ ] Presupuesto cloud, métricas de tokens/costo/latencia y reason codes.
- [ ] Construcción de contexto mínimo respetando `SocialPrivacyPolicy` antes de cualquier llamada remota.
- [ ] Integración Transcript -> AI Router -> TTS usando fakes en tests.
- [ ] Memory API completa y Personality Engine evolutivo se separan para R3B después de estabilizar routing.
- [ ] Medición y benchmarks físicos en Banghó Zero G05 y SF20BA.

## Reglas del board

- No marcar hardware como validado sin prueba real.
- No marcar un bloque como completado si faltan tests/documentación razonables.
- Cambios de arquitectura se reflejan en ADR.
- Este archivo se actualiza al cerrar cada lote de trabajo relevante.
- No hacer commit/push sin autorización del propietario.
