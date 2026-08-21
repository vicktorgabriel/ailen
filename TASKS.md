# Task Board — AILEN

> Fuente operativa de trabajo inmediato. No reemplaza `ROADMAP.md`.

## Estado general

Versión: `0.1.0-dev.0`

Milestone activo: `R3B — Lab Mode + detección de hardware + Model Manager local`.

Los slices R1, R2A, R2B y R3A quedaron integrados y auditados. R3A cerró con 254 tests tras la revisión final y queda como baseline para el runtime de laboratorio.

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

## Bloque 9 — AI Router Híbrido y Proveedores Local/LAN/Cloud (R3A)

- [x] AI Router v1 determinista con matriz completa por `DeviceProfile` (`SATELLITE`, `CLOUD`, `HYBRID`, `LOCAL`, `LAN_BRAIN`) y códigos de razón canónicos (`src/ailen/ai/router.py`).
- [x] `OutboundPrivacyPolicy` determinista (`PUBLIC`, `RESTRICTED`, `PRIVATE`) que bloquea envíos a Cloud y LAN no confiable (`src/ailen/ai/privacy.py`).
- [x] `SecretResolver` seguro para API keys desde variables de entorno y archivos `0600`, con enmascaramiento total en logs y reportes (`src/ailen/ai/secrets.py`).
- [x] `BudgetPolicy` circuit breaker consultando la tabla `ai_usage` en SQLite para frenar cargos cloud automáticamente ante excesos diarios o mensuales (`src/ailen/ai/budget.py`).
- [x] `AiContextBuilder` construyendo prompts mínimos acotados en caracteres/tokens con filtrado de privacidad social y outbound (`src/ailen/ai/context.py`).
- [x] Cliente HTTP genérico OpenAI-compatible basado en stdlib (`urllib.request`) sin dependencias pesadas (`GenericOpenAiBackend`).
- [x] Backends especializados para servidor HTTP local (`LocalAiBackend`), servidor LAN Brain con trust boundary (`LanBrainAiBackend`) y cloud con cost tracking (`CloudAiBackend`).
- [x] `AiOrchestrator` ejecutando la secuencia de fallback de forma segura y registrando telemetría y eventos en `EventBus` (`src/ailen/ai/orchestrator.py`).
- [x] `ConversationCoordinator` unificando Transcript STT -> Context -> Router -> Orchestrator -> TTS Output (`src/ailen/core/conversation.py`).
- [x] Configuración extendida `[ai]`, `[ai.local]`, `[ai.lan]`, `[ai.cloud]` en `src/ailen/core/config.py` y `config/ailen.example.toml`.
- [x] Comandos CLI `ailen diagnose ai` y `ailen demo ai "<prompt>" [--dry-run]`.
- [x] Benchmark reproducible DEV del AI Router (`docs/benchmarks/dev_ai_router_benchmark.md`), sin extrapolar cifras a hardware objetivo.
- [x] Documentos POC (`docs/research/AI_ROUTER_POC.md`, `docs/research/LOCAL_LLM_BACKEND_POC.md`, `docs/research/LAN_BRAIN_POC.md`, `docs/research/CLOUD_PROVIDER_POC.md`).
- [x] Suite auditada de R3A con 254 tests offline, ruff/mypy/diff-check/wheel en verde tras revisión final.

## Bloque 10 — R3B Lab Mode + Hardware-aware Model Manager

- [ ] formalizar `ailen lab start` sin cambios persistentes del SO.
- [ ] soporte de laboratorio explícito para Linux Mint y Windows 11.
- [ ] detectar CPU/arquitectura/RAM/GPU/VRAM/disco/audio/cámara/display de forma multiplataforma.
- [ ] separar adapters Linux/Windows del Core.
- [ ] producir `HardwareCapabilityReport` normalizado.
- [ ] `ModelCatalog` declarativo y versionado.
- [ ] `ModelPlanner` que elija runtime/modelo/quantización según hardware y perfil.
- [ ] `ModelPlan` explicable con reason codes.
- [ ] downloader seguro con HTTPS, tamaño esperado y SHA-256 obligatorio.
- [ ] consentimiento explícito de descarga en Lab Mode.
- [ ] cache/model store local sin incluir modelos en Git.
- [ ] preparar llama.cpp/Ollama u otro runtime desacoplado sin meterlo en Core.
- [ ] `ailen models plan`, `ailen models list`, `ailen models fetch` o equivalente.
- [ ] prueba end-to-end fake: detectar hardware -> elegir modelo -> resolver backend local -> ConversationCoordinator.
- [ ] benchmark DEV sin descargar modelos automáticamente durante tests.
- [ ] documentar Lab Mode vs Appliance Mode (`docs/deployment/LAB_AND_APPLIANCE_MODES.md`).

## Bloque 11 — R3C Memory API + Personality + Tools

- [ ] Memory API avanzada (consolidación semántica, decaimiento de memoria, tags).
- [ ] Personality Engine evolutivo con simulación de estados anímicos y límites de personalidad.
- [ ] Integración de herramientas locales controladas por allowlist.
- [ ] Medición y benchmarks físicos posteriores en Banghó Zero G05 y SF20BA.

## Reglas del board

- No marcar hardware como validado sin prueba real.
- No marcar un bloque como completado si faltan tests/documentación razonables.
- Cambios de arquitectura se reflejan en ADR.
- Este archivo se actualiza al cerrar cada lote de trabajo relevante.
- No hacer commit/push sin autorización del propietario.
