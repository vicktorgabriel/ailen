# Task Board — AILEN

> Fuente operativa de trabajo inmediato. No reemplaza `ROADMAP.md`.

## Estado general

Versión: `0.1.0-dev.0`

Milestone activo: `R4 — capacidades cotidianas, periféricos intercambiables y operación persistente`.

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

## Bloque 10 — R3B Lab Mode + Hardware-aware Model Manager (R3B.1 Lab Stabilization)

- [x] formalizar `ailen lab start` sin cambios persistentes del SO ni dependencias de root/services.
- [x] soporte de laboratorio explícito para Linux Mint y Windows 11 (adaptadores y parsers CIM/PowerShell con `csv.reader` tolerando comas/quotes sin `shell=True`).
- [x] verdad de hardware: CPU flags y VRAM libre en Windows CIM reportan `None` (UNKNOWN) en lugar de asumir AVX2 o VRAM libre.
- [x] manejar hardware no medido de forma defensiva: emitir `HARDWARE_RAM_UNKNOWN` y `LOCAL_PLAN_BLOCKED_INSUFFICIENT_EVIDENCE` ante RAM no medida sin convertir a Satellite.
- [x] separar adapters Linux (`LinuxHardwareAdapter`), Windows (`WindowsHardwareAdapter`) y test (`FakeHardwareAdapter`) del Core en `src/ailen/hardware/`.
- [x] contar physical cores en Linux considerando `(physical id, core id)` para soporte multi-socket.
- [x] DRM cards en Linux reportan `backend=None` sin asumir Vulkan sin prueba explícita.
- [x] `ModelCatalog` declarativo e inmutable (`src/ailen/models/catalog.py`) con validación de IDs, URLs HTTPS, SHA-256 de 64 hex y modelos Qwen 3.5 0.8B (Q4_0 / Q8_0) verificados con Git LFS.
- [x] `ModelPlanner` adaptativo con validación de fracciones, capping de context, comprobación de disco libre y CPU requirements en GPU offload.
- [x] `ModelStore` con sanitización regex estricta y validación `is_relative_to` contra path traversal.
- [x] `ModelDownloader` seguro con HTTPS forzado, rechazo de downgrade HTTP en redirecciones, límites de tamaño, verificación SHA-256 fail-closed y renombre atómico.
- [x] `LocalRuntimeManager` desacoplado que detecta `llama-server`, `llama serve` y `Ollama`, reportando `DEGRADED` ante HTTP 404.
- [x] `LabRunner` real no invasivo (`src/ailen/runtime/runner.py`) con tabla de estado de componentes, soporte para `--headless`, `--no-camera`, `--no-audio`, `--no-ai`, `--duration` y cleanup ante Ctrl+C.
- [x] `LabDoctor` no invasivo (`src/ailen/runtime/doctor.py`) con diagnóstico `PASS`/`WARN`/`FAIL`/`SKIP` (`ailen lab doctor`).
- [x] Comandos CLI operativos: `ailen lab inspect`, `ailen lab start`, `ailen lab doctor`, `ailen lab benchmark`, `ailen models list`, `ailen models plan`, `ailen models fetch`, `ailen models verify`.
- [x] Documentos de investigación: `docs/research/HARDWARE_CAPABILITY_V2.md`, `docs/research/LOCAL_MODEL_CATALOG_2026.md`, `docs/research/LOCAL_RUNTIME_POC.md`, `docs/research/MODEL_PLANNER.md`.
- [x] Suite auditada de R3B.1 con 292 tests offline, ruff limpio, mypy en 95 archivos fuente, diff-check limpio y wheel construible.

## Bloque 11 — R3B.2 Live Lab Integration

- [x] eliminar sustituciones fake silenciosas en Lab Mode: cada estado `READY` corresponde al backend real configurado; los fakes se restringen exclusivamente a `--simulate`.
- [x] crear `LabComponentFactory` para resolver componentes físicos vs simulados y reportar estados estructurados `ComponentStatus`.
- [x] conectar Audio real -> VAD -> STT configurado -> `ConversationCoordinator` -> Router/LLM -> TTS configurado -> Face.
- [x] usar `EventBus` (`EventType.TRANSCRIPT_READY`) y candado atómico single-flight para procesar cada transcript una sola vez evitando colisiones concurrentes.
- [x] integrar presencia Vision -> `InteractionCoordinator` -> mirada/estado Face y ciclo de vigilia/atención durante la sesión de laboratorio.
- [x] soportar Local AI mediante Ollama/llama.cpp con consulta de inventario real `RuntimeModelInventory` y fallback cloud/Rule-only según política.
- [x] `ManagedLlamaRuntime` para ciclo de vida de procesos propios de AILEN con respeto de ownership de procesos externos.
- [x] flujo `ailen lab prepare-ai` con preflight de hardware, plan de modelo, verificación de integridad y arranque opcional.
- [x] agregar `ModelPurpose` (`SANITY`, `BALANCED`, `QUALITY`) para guiar la selección de modelos en el planner.
- [x] agregar métricas de sesión reales `LabSessionMetrics` (latencias STT/AI/TTS, conteo de tokens, transiciones de presencia, FPS de Face) y exportación a `runtime/lab/session_<timestamp>.json`.
- [x] mejorar `ailen lab doctor` con remediaciones claras y flag `--json`.
- [x] documentos: `docs/research/LIVE_LAB_PIPELINE.md`, `docs/testing/MINT_LIVE_LAB_CHECKLIST.md`.
- [x] Suite auditada de R3B.2 con 324 tests offline, ruff limpio, mypy en 100 archivos fuente, diff-check limpio y wheel construible.

## Bloque 12 — R3B.3 First Physical Lab Validation

- [x] implementar catálogo declarativo de modelos de voz y habla `SpeechAssetCatalog` (`src/ailen/speech/catalog.py`) con modelos Vosk, Whisper.cpp y voces Piper en español verificadas criptográficamente.
- [x] implementar `SpeechAssetStore` (`src/ailen/speech/store.py`) en `~/.local/share/ailen/speech/{stt,tts}/` con protección estricta contra path traversal.
- [x] implementar `SpeechAssetDownloader` (`src/ailen/speech/downloader.py`) con HTTPS forzado, streaming temporal, verificación SHA-256 fail-closed y extracción segura de zip (protección anti Zip-Slip).
- [x] implementar flujo de preparación de modelos de voz `LabSpeechPreparer` (`src/ailen/speech/prepare.py`) y comando `ailen lab prepare-speech --yes`.
- [x] implementar generador de configuración aislada de laboratorio `ailen lab config init` (`src/ailen/runtime/lab_config.py`) para `runtime/lab/ailen-lab.toml` (gitignored).
- [x] implementar verificador exhaustivo de preparación física `LabPreflightChecker` (`src/ailen/runtime/preflight.py`) y comando `ailen lab preflight`.
- [x] agregar comandos CLI para inspección y gestión: `ailen speech list/plan/fetch/verify`, `ailen lab audio-devices`, `ailen lab cameras`.
- [x] documentar catálogo y especificaciones en `docs/research/SPEECH_ASSET_CATALOG_2026.md`.
- [x] registrar estado de preflight y guía de remediación del host Asrock en `docs/testing/FIRST_PHYSICAL_LAB_REPORT.md`.
- [x] conectar y validar G600 físico (micrófono + auricular) en Asrock / Linux Mint; pipeline voz end-to-end `AUDIO CONVERSATION PASS`.
- [x] instalar/configurar Vosk + Piper y ejecutar `ailen -c runtime/lab/ailen-lab.toml lab start --headless --no-camera` con hardware real.
- [x] medir latencias físicas reales STT/AI/TTS y tokens en sesión de voz; Vision/presencia/gaze también validados físicamente.
- [x] conectar webcam reciclada USB y validar detección facial/posición con YuNet; Haar queda experimental.
- [x] instalar Tkinter y abrir Face GUI física integrada con Lab; queda repetir experiencia completa tras mejoras STT/cámara.
- [ ] realizar después un segundo laboratorio en Windows 11 sin convertirlo en appliance.

## Bloque 13 — R3B.4 Adaptive Runtime + Voice Latency

- [x] agregar abstracción `InferenceProfile` (`RULE_ONLY`, `FAST`, `BALANCED`, `QUALITY`) y recomendación determinista por hardware (`recommend_inference_profile`), separada de `DeviceProfile`.
- [x] conectar hardware -> `InferenceRecommendation` -> `ModelPlanner` -> residencia Ollama por perfil; sin model hopping automático por turno.
- [x] benchmark reproducible de latencia/calidad (`ailen lab benchmark-ai`) evaluando modelos ya instalados en Ollama y reportando candidatos ausentes como `NOT_INSTALLED` sin descargas automáticas.
- [x] incorporar candidatos en ModelCatalog (`llama-3.2-3b-instruct`, `qwen3.5-4b-instruct`, `gemma-3-4b-instruct`, `qwen2.5-3b-instruct`) con metadatos y `downloadable=False`.
- [x] mantener fallback Rule-only/LAN/cloud cuando no haya modelo local viable con recomendación `RecommendedDeployment`.
- [x] Piper Python `AudioChunk` con voz cacheada, playback incremental por oración, prewarm de Lab y fallback CLI; TTFAR conectado desde fin de voz hasta primer PCM enviado a playback.
- [x] mejorar VAD con perfiles (`conservative`, `normal`, `fast`) y conectar `SttQualityEvaluator` al Lab para reprompt determinista antes del LLM, sin inventar confidence.
- [x] documentar matriz preliminar CPU/RAM/GPU en `docs/research/ADAPTIVE_INFERENCE_2026.md` y reporte de benchmark en `docs/benchmarks/LOCAL_MODEL_COMPARISON.md`.

## Bloque 14 — R3C Product Behaviors + Controlled Tools + Web

- [x] intent resolver determinista para acciones simples antes del LLM con filtrado estricto de negativos conceptuales (`src/ailen/tools/intent_resolver.py`).
- [x] tools allowlisted: hora, timer, volumen, música, notas y status; `MusicTool` tiene contrato/routing pero backend físico real aún pendiente.
- [x] `ToolRegistry`/`ToolExecutor` con schema estricto, permisos por SocialMode, niveles de privacidad, timeout acotado y auditoría SQLite (`tool_events`).
- [x] `web_search` provider-agnostic (`WebSearchProvider`, `WebSearchTool`, `UnconfiguredWebSearchProvider`, `FakeWebSearchProvider`) controlado por Core; sin Internet irrestricto para el LLM.
- [x] `web_fetch` seguro con `WebFetchPolicy`, HTTPS por defecto, límite de 256 KiB, allowlist de Content-Type, inspección de redirecciones y defensas anti-SSRF (bloqueo de loopback, RFC1918, link-local y endpoints de metadata cloud).
- [x] devolver resultados de tools al LLM sólo cuando haga falta redactar/resumir; respuesta directa para acciones locales simples.
- [x] privacidad/budget para búsqueda remota y cloud; costos del proveedor visibles (`FREE`, `PAID`, `UNKNOWN`).
- [x] persistencia SQLite para notas (`notes` table, migración 0003) con queries parametrizadas.
- [x] integración en `ConversationCoordinator` y `LabRunner` con bypass determinista de LLM (`RULE_ONLY_TOOL`).
- [x] documentos de investigación: `docs/research/CONTROLLED_TOOLS_ARCHITECTURE.md`, `docs/research/WEB_SEARCH_BOUNDARY.md`.
- [x] Suite auditada de R3C con 430 tests offline, ruff limpio, mypy en 126 archivos fuente, diff-check limpio y wheel construible.

## Bloque 15 — Auditoría R3C + STT Quality + Vision YuNet Hardening

- [x] auditoría completa del working tree R3C sin commit (tools, executor, intent resolver, web boundary, memoria, visión).
- [x] fix `ToolExecutor`: timeout no bloquea al llamador mediante worker daemon; red outbound explícita; tools destructivas fail-closed hasta executor cancelable (`src/ailen/tools/executor.py`).
- [x] fix máquina de estados: `PROCESSING -> ATTENTION` válida; `PROCESSING -> LISTENING` prohibido con regresión (`src/ailen/core/state.py`).
- [x] fix `IntentResolver`: notas preservan casing original; query web extraída del texto crudo; búsqueda web explícita prevalece sobre negativos conceptuales.
- [x] hardening preflight: YuNet instancia realmente `FaceDetectorYN` (no basta archivo existente), valida score threshold; Haar valida carga del cascade (`src/ailen/runtime/preflight.py`).
- [x] benchmark vision CPU-first: `ailen lab benchmark-vision` con latencia avg/p50/p95/max, detecciones, confianza, gaze por fase y reporte JSON (`src/ailen/vision/benchmark.py`).
- [x] medición física YuNet en CPU: ~49 ms avg / p95 ~91 ms a 5 FPS con confianza ~0.91 (Ryzen 5 5500); Haar ~67 ms avg con picos >500 ms.
- [x] benchmark STT reproducible: `ailen lab benchmark-stt` multi-motor sobre mismos WAVs, WER propio con normalización española, `NOT_INSTALLED` sin descargas, grabación sólo con autorización explícita (`src/ailen/audio/stt_benchmark.py`).
- [x] medición Vosk small-es sobre utterance Piper: WER 0.143 en muestra única (transcripto "detectó" vs "detecto"); whisper.cpp queda `NOT_INSTALLED`.
- [x] regresión explícita de historial reciente: m0..m7 con limit=3 devuelve m5,m6,m7 incluso con timestamps idénticos (desempate por rowid).
- [x] cierre post-auditoría: 478 tests offline; ruff limpio; mypy limpio en 128 archivos fuente; diff-check limpio; wheel construible.

- [x] persistencia conversacional real: `LabRunner` crea/cierra sesión `sess-*` y `ConversationCoordinator` persiste turnos sin duplicar input actual.
- [x] WebSearch hardening: resultados acotados/no confiables; WebFetch HTTPS-only; política `[network].outbound_web_enabled` separada de cloud.
- [ ] backend de reproducción musical real (PipeWire/MPRIS/local player) detrás de `MusicService`; `MprisMusicService` vía `playerctl` ya está cableado y testeado en software, pero falta validar reproducción audible con un player MPRIS real antes de cerrar este ítem.
- [x] instalación limpia: `diagnose ai` y `demo ai` ejecutan migraciones SQLite antes de consultar `ai_usage`, evitando depender de una base ya inicializada en otro host.
- [x] instalar Whisper.cpp tiny/base y verificar assets en Debian; [ ] decidir baseline STT sólo tras WER real sobre 10-20 utterances físicas.

## Bloque 16 — Voice Understanding + Semantic Tool Fallback

- [x] auditar sesión física real y comparar transcripts vs tools ejecutadas.
- [x] tolerancia ASR determinista para clock/notes/volume.
- [x] reprompt para fragmentos de una palabra demasiado ambiguos.
- [x] parser semántico local restringido a tools locales no-network/no-destructive, con schema validation posterior.
- [x] búsqueda de notas por frase + tokens significativos y respuesta con contenido.
- [x] reducir repetición de contexto Vision y coletillas genéricas.
- [x] corregir ClockTool de UTC a hora local.
- [x] integración real con qwen3.5:9b sobre frases fallidas de la sesión.
- [x] 487 tests + Ruff + mypy 129 source files + diff-check.
- [ ] repetir sesión física G600 y registrar tasa de tool hit / semantic fallback / reprompt / chat.
- [ ] comparar Vosk vs Whisper.cpp con 10-20 utterances reales antes de cambiar baseline STT.

## Bloque 17 — R4 capacidades cotidianas y portabilidad de hardware

- [x] selección de cámara explícita `auto|usb|rtsp`, con modos estrictos, fallback sólo en `auto`, compatibilidad legacy y secretos RTSP fuera de TOML.
- [ ] validar físicamente webcam USB reciclada en Debian con YuNet; no marcar PASS hasta conectar y medir.
- [x] migración `0004_reminders` + CRUD SQLite + `RemindersTool` + scheduler/evento `REMINDER_DUE`.
- [x] separar intención temporal de `NotesTool`: recordatorio con tiempo explícito -> `reminders`; nota sin tiempo -> `notes`; timer sigue volátil.
- [x] diferir anuncios de recordatorio hasta canal de voz IDLE/ATTENTION, sin TTS desde hilo scheduler.
- [ ] validar físicamente un recordatorio audible y comprobar que `AudioTurnGate` evita auto-transcripción.
- [ ] cerrar reproducción MPRIS audible y luego catálogo/playlists local seguro.
- [ ] proveedor WebSearch real con rate limit, boundary no confiable y fail-closed.
- [ ] Web Admin: sesiones persistentes + visores de conversaciones/memorias/notas/auditoría.
- [ ] RTSP audio como `AudioInputBackend` opcional; NC250 no debe ser requisito de hardware.
- [ ] provisionador Debian appliance idempotente y systemd endurecido, sin ejecutarlo destructivamente sobre Lab.

## Reglas del board

- No marcar hardware como validado sin prueba real.
- No marcar un bloque como completado si faltan tests/documentación razonables.
- Cambios de arquitectura se reflejan en ADR.
- Este archivo se actualiza al cerrar cada lote de trabajo relevante.
- No hacer commit/push sin autorización del propietario.
