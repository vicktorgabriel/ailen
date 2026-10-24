# Task Board — AILEN

> Fuente operativa de trabajo inmediato. No reemplaza `ROADMAP.md`.

## Estado general

Versión: `0.4.0-dev.0`

Milestone activo: `R4/R5 — consolidación de capacidades cotidianas + Web Admin`, con `R5B — FacePack realista extensible` como renderer lógico por defecto; `portrait` queda sólo como renderer legacy seleccionable manualmente.

R1, R2, R3A/R3B/R3C están integrados. El baseline completo actual es de 1164 tests en verde, Ruff limpio, mypy limpio en 168 módulos fuente, diff-check y wheel de 211 entradas inspeccionado en verde. El gate C++/FacePack previo permanece válido porque este vertical no modificó el engine ni el pack.

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
- [x] ADR-006 aceptado como baseline provisional 0.4.x; benchmarks de hardware objetivo siguen abiertos.

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

## Bloque 9 — AI Router Híbrido R3A (histórico; sustituido por remotos nombrados en Bloque 18)

- [x] AI Router v1 determinista con matriz completa por `DeviceProfile` (`SATELLITE`, `CLOUD`, `HYBRID`, `LOCAL`, `LAN_BRAIN`) y códigos de razón canónicos (`src/ailen/ai/router.py`).
- [x] `OutboundPrivacyPolicy` determinista (`PUBLIC`, `RESTRICTED`, `PRIVATE`) que bloquea envíos a Cloud y LAN no confiable (`src/ailen/ai/privacy.py`).
- [x] `SecretResolver` seguro para API keys desde variables de entorno y archivos `0600`, con enmascaramiento total en logs y reportes (`src/ailen/ai/secrets.py`).
- [x] `BudgetPolicy` circuit breaker consultando la tabla `ai_usage` en SQLite para frenar cargos cloud automáticamente ante excesos diarios o mensuales (`src/ailen/ai/budget.py`).
- [x] `AiContextBuilder` construyendo prompts mínimos acotados en caracteres/tokens con filtrado de privacidad social y outbound (`src/ailen/ai/context.py`).
- [x] Cliente HTTP genérico OpenAI-compatible basado en stdlib (`urllib.request`) sin dependencias pesadas (`GenericOpenAiBackend`).
- [x] Implementación histórica de `LocalAiBackend`, `LanBrainAiBackend` y `CloudAiBackend`; el backend cloud monolítico fue retirado en R4 y sustituido por `remote:<id>` con transportes por protocolo.
- [x] `AiOrchestrator` ejecutando la secuencia de fallback de forma segura y registrando telemetría y eventos en `EventBus` (`src/ailen/ai/orchestrator.py`).
- [x] `ConversationCoordinator` unificando Transcript STT -> Context -> Router -> Orchestrator -> TTS Output (`src/ailen/core/conversation.py`).
- [x] Configuración histórica `[ai.cloud]`, migrada en R4 a `[ai.remote.providers.<id>]`; el esquema actual conserva sólo la migración fail-closed.
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
- [x] persistir de forma atómica y consentida la selección target-qualified de
  hardware/modelo/runtime/contexto/offload; runner fail-closed y sin lectura si
  local está deshabilitado. Integración con el instalador Debian sigue en R6.
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
- [x] proveedor DDGS real para `WebSearchTool`, con búsqueda `text`, noticias
  fechadas `news`, frescura acotada y vacío fail-closed; rate limit/política de
  producción continúan abiertos en el ítem R4 específico.
- [ ] catálogo/reproductor musical local seleccionable por nombre/estado de ánimo; MPRIS actual sólo controla un player ya abierto y no resuelve consultas libres como "poné música alegre".
- [x] comandos de gesto facial allowlisted sobre `FaceAnimator`; once expresiones
  tienen geometría pixel propia, sobreviven `SPEAKING` de forma acotada y la boca
  continúa articulando durante playback.
- [x] `face_style="portrait"`: renderer raster legacy manual usando el retrato exacto aprobado de AILEN como asset base, con parpadeo/wink, mirada, boca por nivel de habla y parallax; `pixel`/`vector` también son selecciones manuales. Assets incluidos en el wheel y prueba GUI funcional realizada; benchmark CPU/RSS raster en hardware objetivo queda pendiente.
- [ ] visión avanzada opcional: objetos/pose/gestos y, en hardware potente, VLM local o LAN Brain; YuNet queda como baseline liviano de rostro/presencia.
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
## Bloque 18 — R4 Proveedores Externos Configurables y Panel Web Admin de IA (ADR-011)

- [x] Abstracción `AiProvider` y `ProviderRegistry` desacoplando Core/Memoria/Herramientas de motores de inferencia.
- [x] Experimentos históricos AGY/Antigravity y OpenCode medidos y retirados el
  2026-09-01: no quedan adapters, runtimes, secretos, UI ni rutas productivas;
  configs viejas migran a `auto` con warning. Sus reportes se conservan.
- [x] `ExternalRuntimeManager` limitado a runtimes realmente soportados por el
  producto: remotos HTTP configurados y local Ollama sólo cuando está habilitado.
- [x] Web Admin `/ia` administra remotos nombrados y acciones reales de
  catálogo/prueba/secreto, sin login/update de agentes CLI retirados.
- [x] Almacén seguro de secretos (`SecretResolver`) con permisos atómicos POSIX `0600` y directorio `0700`, fuera de TOML y SQLite.
- [x] Soporte de primer nivel para una instalación remota en Tier 4 GB
  (`ai.local.enabled = false` documentado y verificado en preflight/runner), sin
  confundir ese modo con el baseline local autónomo todavía por medir.
- [x] Enrutamiento adaptativo determinista (`RuleBasedRouter`) con prioridades configurables y respeto estricto de `OutboundPrivacyPolicy`.
- [x] Evidencia histórica AGY preservada como rechazo de producto: aislamiento
  funcionó, pero ~6,7 s a primer texto y contexto interno impiden usarlo en voz.
- [x] Gate histórico del Provider Manager: 697 tests, Ruff y mypy limpios; el
  baseline integrado vigente se mantiene en el encabezado de este documento.
- [x] ADR-011 documentado y actualizado.
- [x] Semántica estricta de `ai.local.enabled=false`: sin discovery, backend,
  startup, prewarm, parser semántico ni fallback local oculto.
- [x] Contrato local común para Ollama/llama.cpp; llama.cpp administrado se carga
  al primer uso y sólo un runtime propio/ocioso se libera por presión de RAM.
- [x] Envelopes canónicos de planificación para 4/8/16/32/64+ GB con contexto, budget
  de modelo y reserva; mantener etiqueta `TARGET_*_BENCHMARK_REQUIRED`.
- [x] Propagar evidencia STT completa a Core y aplicar guarda de confianza a
  tools con efecto, sin convertir confianza semántica en acústica.
- [x] Streaming de conversación a frases TTS incrementales con prefetch uno,
  cancelación de barge-in y prohibición de empalmar fallback tras salida parcial.
- [x] Quitar saludos/charla abierta del fast path de respuestas deterministas y
  generalizar la personalidad base sin perder contexto técnico cuando corresponde.
- [x] Prioridades `/ia` conectadas al orden real; proveedor explícito sano
  primero y remotos independientes `remote:<id>` para cascada observable.
- [x] Taxonomía de error externa (`timeout`, `rate_limit`, `authentication`,
  `invalid_model`, `network`, `unavailable`, `invalid_response`,
  `internal_error`), fallback observable y cooldown acotado por 429.
- [x] Boundary remoto reconstruido y probado por captura: sólo turno actual;
  sin historial, memoria, persona, capabilities, paths, tools ni secretos.
- [x] `/ia` distingue selección de verificación efectiva, fuente de catálogo,
  clave propia, latencia medida y reinicio requerido; no inventa health/modelos.
- [x] Harness sintético externo dry-run por defecto, sin contenido privado ni Ollama bajo
  `runtime/lab/external_ai_validation/`.
- [x] Transportes livianos OpenAI Responses SSE (`store=false`), OpenAI Chat
  Completions SSE y Anthropic Messages SSE con tests simulados; presets OpenAI,
  Anthropic, DeepSeek, Kimi y MiniMax permanecen no probados hasta consentimiento.
- [x] `ProvisioningPlan` automático por hardware/calificación con runtime,
  contexto, offload, reservas, hashes/licencia y acciones consentidas. Perfiles
  Lab ya no fijan modelo; candidates no se instalan silenciosamente. El runtime
  se indexa y selecciona por evidencia target-specific independiente y CPU/CUDA
  nunca se infiere desde la mera compatibilidad del descriptor.
- [x] El arranque local respeta el runtime exacto calificado y nunca ejecuta un
  candidato automático ni cruza evidencia llama.cpp/Ollama; el campo
  `ai.local.runtime` ya es consumido y validado.
- [x] PipeWire default nativo sin `pactl` y target explícito sin ambigüedad;
  cadena NS -> capture gain dB -> AGC bounded con gate/hold/release -> limiter,
  con métricas raw/por etapa/final y SNR/clipping/WER RAM-only. Se retiró
  `audio.input_volume` decorativo.
- [ ] Seleccionar y medir GGUF local por tier en hardware reciclado objetivo con
  el stack completo. ASRock/RTX no cierra soporte 4/8 GB.
- [ ] Repetir la matriz de captura con los micrófonos integrados/nativos de
  las placas recicladas a 30/75/100 cm. La campaña USB Jieli
  `voice-20260901T084132Z-1cfb53` fue inconclusa y no aprobó ningún perfil.
- [ ] Conectar el endpoint físico aprobado al onboarding/provisionador R6 de cada
  unidad. Hasta entonces `input_device="default"` sigue siendo un valor Lab y no
  una selección automática del micrófono nativo; no inferir calidad por nombre.
- [ ] Validar físicamente VAD WebRTC modo 2/3 y silence 380/500/600 ms, TTFAR,
  barge-in temprano/medio/tardío, transcript preservado y contaminación por eco.
- [ ] Extender captura/STT con hipótesis parciales correlacionadas cuando un
  backend real las entregue; nunca ejecutar un parcial como orden final.
- [ ] Medir cancelación de Piper: distinguir stop de playback de inferencia ONNX
  ya iniciada y cambiar chunking sólo si la evidencia muestra el cuello.
- [x] Implementar lifecycle generacional de TTS: cancelación lógica, descarte
  stale, lock de backend, joins acotados y exclusión de assistant parcial.
- [x] Implementar bandas STT configurables y evitar que una frase multi-palabra
  de confianza extremadamente baja llegue al LLM como válida.
- [x] Reemplazar calibración RMS sintética del panel por captura real RAM-only o
  `not_supported` honesto.
- [x] Agregar `ailen lab calibrate-voice`, incluido `--barge-in-only`; queda
  ejecutar la matriz con operador y micrófono físico. El modo sin `--device`
  autodetecta un conjunto bounded/deduplicado; métricas raw/gained/processed y
  snapshot de fuentes son escalares RAM-only y no cambian configuración.
- [x] Agregar manifests y CLI de calificación local sin descargas; 1–1.7B y
  3–4B continúan candidatos hasta benchmark objetivo.
- [ ] Evaluar APIs directas de baja latencia (OpenAI Responses, Anthropic,
  DeepSeek, Kimi, MiniMax u otra) con clave propia, TTFT físico y calidad rioplatense antes de
  promover una suscripción administrada.


## Bloque 19 — R5B FacePack realista extensible

- [x] generar lote amplio de expresiones H3 usando identidad/cámara/resolución constantes.
- [x] conservar videos fuente como materia prima y fuera del package-data del wheel.
- [x] proteger MP4 crudos contra commit accidental mientras se clasifican.
- [ ] terminar/regenerar retornos naturales para emociones intensas, sueño, llanto y risa; no sustituirlos por afirmaciones de calidad no observada.
- [x] reconstruir orden cronológico y clasificar visualmente los 85 clips con manifiesto trazable.
- [x] separar estados persistentes (`idle`, `waiting`, `attentive`, `listening`, `processing`, `sleeping`) de microacciones, emociones y speech.
- [x] definir FacePack v1 versionado con tablas, anchors, intensidad, loopability, interruptibilidad, retorno, límites y checksums.
- [x] construir `libailen_face_engine.so` C++17 con C ABI; ningún LLM controla frames/UI.
- [x] implementar scheduler base + espera variable + microacción + retorno, sin repetir MP4 completos.
- [x] validar capas ROI de ojos/cejas/boca: el tracking funcionó pero la mezcla de identidades H3 deformó rasgos; FacePack 1.6 usa movimiento full-frame limpio y conserva ROI sólo para futuros assets compatibles. Speech sigue siendo una categoría independiente de emoción.
- [x] wrapper `ctypes`, renderer Tk y failover estable `facepack -> headless` tanto al cargar como ante fallo nativo durante una sesión; `pixel` permanece disponible sólo manualmente.
- [x] demostrar expresión nueva en Pack B sin recompilar el engine mediante test nativo.
- [x] proyectar expresiones dinámicas del pack al schema de Tool/metadata conversacional mediante el contrato Face, sin lista paralela del renderer.
- [x] benchmark ASRock de carga/RSS/decode/CPU/Tk; no extrapolar a Raspberry/Banghó/SF20BA.
- [x] documentar formato, ABI, build, pack compiler y procedimiento de actualización independiente.
- [x] separar preflight Tk de health nativo: cargar ABI/pack para PASS y advertir display facial deshabilitado ante fallo.
- [x] auditoría post-Codex R5B: timing natural del pack (`duration=0`), failover native->headless en caliente y 730 tests; Ruff, mypy (145 + 6 módulos), C++ warnings, diff-check y wheel sin MP4/FacePack/binarios nativos.
- [x] ampliar el FacePack desktop a 79 secuencias/2.888 frames lógicos/39 emociones listables, usando 76 fuentes `keep/trim` y dejando fuera sólo redundancias o material inseguro.
- [x] ejecutar `transition_in/out`, prioridad, `gaze_compatible`, estilos de speech y retorno visual compatible sin permitir que el renderer cambie el estado de Core.
- [x] endurecer ABI 1.4: `noexcept` en exports, captura total de excepciones, snapshots thread-local, copia/copia bilinear segura, mutex por handle y errores limpios de JPEG/pack.
- [x] corregir deformación/doble imagen: preservar movimiento full-frame authored, usar borde constante y trackear capas composables sobre la cabeza actual.
- [x] eliminar saltos directos desde pose expresiva a neutral mediante retornos de frames reales y deduplicación de payload, sin crossfade.
- [x] validar físicamente ojos y boca en showcase focal: `blink_double` quedó limpio y speech full-frame mejoró labios/dientes; el seam casi no se percibe a velocidad real.
- [ ] validar físicamente todos los retornos/emociones del showcase completo; algunos clips intensos todavía necesitan un retorno H3 authored.
- [ ] validar DLL Windows y CMake en un host con toolchain/libjpeg; CMake no estaba instalado en ASRock.
- [ ] compilar/medir perfil LOW real antes de decidir JPEG Q, resolución o derivado RGB565.
- [ ] validar una sesión conversacional completa con `face_style="facepack"` y speech_level PCM real; el smoke X11 actual no sustituye esa prueba.


## Bloque 20 — R5 Web Admin: cero datos sintéticos

- [x] `/ia` consume runtime/config/proveedores reales y protege acciones con CSRF.
- [x] `/audio` lee configuración efectiva y expone pruebas controladas.
- [x] eliminar estados ficticios de `/herramientas`, `/vision`, `/rostro`, `/personalidad`, `/sistema` y `/setup` (2026-10-23); conteos/logs en vivo siguen pendientes (observabilidad).
- [x] `/memoria`: búsqueda literal paginada, CRUD y exportación JSON de recuerdos explícitos sobre SQLite; públicos por defecto, opt-in privado, confirmación y CSRF para cambios/exportación.
- [ ] Ampliar administración de memoria a notas, recordatorios e historial; el slice actual no mezcla esas tablas ni ofrece purga masiva.
- [x] `/diagnostico`: health del proceso, LabDoctor explícito y métricas del último reporte Lab finalizado; procedencia real/simulación, muestras y fecha, sin PASS/latencias inventadas.
- [ ] Observabilidad entre procesos en vivo y visor de logs redactados; el reporte de sesión finalizada no los sustituye.
- [x] `/personalidad`: lee identidad, SocialMode y rasgos base desde config; el simulador queda marcado no disponible. Falta mostrar rasgos evolucionados persistidos (PersonalityService solo existe en runtime Lab).
- [x] `/vision`: leer valores efectivos de SettingsService y estado de cámara/detector; conservar `/api/vision/test` como prueba explícita.
- [x] (catálogo por config; estado en vivo de tools requiere inyectar ToolRegistry en `serve`) `/herramientas`: reflejar ToolRegistry/servicios reales y estado MPRIS/WebSearch; no mostrar “habilitada” si sólo existe contrato o falta validación física.
- [x] (config real; metadata FacePack pendiente) `/rostro`: sincronizar configuración real del renderer estable y, más adelante, metadata del FacePack sin acoplarlo al LLM.
- [x] (defaults eliminados; setup aún sin wizard multi-paso ni POST; validar flujo móvil real pendiente) `/sistema` y `/setup`: eliminar defaults ficticios, mantener acciones destructivas bajo confirmación y validar flujo móvil real.
- [x] Regresiones de memoria/diagnóstico: datos reales, vacíos, privacidad, CSRF, errores redactados, exportación acotada y procedencia de métricas.
- [ ] Extender la misma cobertura al resto de vistas al conectarlas.

## Bloque 21 — R6 Vertical 1: updates firmados y recuperables

- [x] contrato/manifiesto JSON estricto y versionado, con compatibilidad de
  plataforma/config/DB y rechazo de campos/URLs/tamaños inseguros.
- [x] firma Ed25519 de bytes exactos mediante OpenSSL, inputs regulares
  `O_NOFOLLOW`, límites, timeout y errores públicos redacted.
- [x] downloader HTTPS bounded/cancelable/reanudable por ETag + Range y CAS
  inmutable verificado por tamaño/SHA-256.
- [x] journal atómico de operaciones, aprobación efímera, un worker y
  recuperación sólo tras re-fetch/reverify/reapproval.
- [x] extracción tar segura, preparación atómica, activación/probation/rollback
  sobre fronteras inyectadas y compatibilidad DB sin down-migration automática.
- [x] configuración/factory side-effect-free; Web `/actualizaciones` + API
  autenticada/CSRF consumen sólo `UpdateAdminService` y DTOs redacted.
- [x] aceptación sintética firmada: éxito, rollback por candidato unhealthy y
  reanudación sin Internet, systemd, `/opt` ni base real.
- [ ] daemon privilegiado `ailen-updaterd` y protocolo de activación Appliance.
- [ ] pipeline de firma productivo, bundle offline y política de retención/GC.
- [ ] pruebas físicas de power loss, disco lleno, health y rollback en appliance.
- [ ] provisionamiento firmado independiente de modelos, voces y FacePack.


## Bloque 22 — R5C Agente de Core y voz en vivo (ADR-014, ADR-015)

- [x] ADR-014 y ADR-015 aceptados; PRODUCT.md §9, ADR README, CHANGELOG y RECENT_DECISIONS actualizados (2026-10-23).
- [x] Auditoría delegada del working tree R5 (memoria/diagnóstico) con AGY y OpenCode; 2 fixes aplicados, gates: pytest 1164+1, Ruff y mypy (168) en verde.
- [ ] Baja prioridad de la auditoría: allowlist en export de memoria, `reports_dir` absoluto, LabDoctor con timeout, tests HTTP 409/503 de `/diagnostico/run`.
- [x] Contrato `autonomy_level` (N1–N3): `AutonomyLevel`/`autonomy_level_of` (valor inválido falla cerrado a N3, sin atributo = N1), `ToolContext.max_autonomy`, gate 2b del `ToolExecutor` (`AUTONOMY_DENIED`; SHOP/PUBLIC limitados a N1) y `agent.max_autonomy_level` (1–3, default 1, editable en panel, requiere reinicio). Todas las tools actuales son N1: sin cambio de comportamiento. Pendiente: mostrarlo en `/herramientas` y que `CapabilityRegistry` use el tope.
- [x] Servicio de confirmación humana (`core/confirmation.py`): TTL 60 s, un solo uso, hash de argumentos, voz rechazada si truncada/confianza None o < 0.72, panel autenticado puede aprobar, fail-closed sin servicio, resumen por tool sin contenido. Pendiente: flujo conversacional/panel que pida y resuelva la confirmación (hoy `CONFIRMATION_REQUIRED` no tiene UI).
- [x] Tool de archivos N2 (`tools/builtin/files.py`): list/read/create/append/overwrite en `agent.file_roots`, O_NOFOLLOW+fstat+nlink==1, backup antes de modificar, confirmación para overwrite y append sobre existente, auditoría sin contenido. Registrada en el runner sólo si hay raíces; inerte con `max_autonomy_level` 1. Pendiente: UI de raíces y validación física.
- [x] Bucle de agente (`core/agent_loop.py`): `AgentPlanner` abstracto, presupuesto de pasos/tiempo/resultado, cancelación, detección de bucles, resultados de tools como datos no confiables delimitados, pausa `AWAITING_CONFIRMATION` y `resume()`, pasos auditados con argumentos redactados (Codex Luna; 19 tests). Pendiente: adaptador del planner al AI Router (tool-calling del LLM local/remoto) y disparo desde voz/panel.
- [x] Base del adaptador realtime (`ai/realtime/`): contrato, cliente WebSocket stdlib RFC 6455, sesión fake, bridge a ToolExecutor con modo/autonomía en vivo, presupuesto por reloj y sample rate, SHOP/PUBLIC denegado. Pendiente: adaptador de un proveedor concreto (protocolo del proveedor), ruta `remote_realtime` en el router, harness dry-run con clave propia y medición TTFT/TTFAR.
- [x] Planner del agente (`ai/agent_planner.py`): protocolo JSON estricto sobre AiOrchestrator, `privacy_level=PRIVATE` (nunca remoto), tools limitadas por filtro vivo, un reintento y degradación fija (Luna, revisado por AGY sin hallazgos). `AgentService` (`core/agent_service.py`): una tarea a la vez, rechazo en SHOP/PUBLIC, cancelación, espera/reanudación por confirmación aprobada, vistas sin argumentos (Luna, 32 tests). Corregida la carrera de `resume()` (lock por run, OpenCode Go). Deuda: `resume()` usa FAILED como estado interino; agregar `RUNNING` al enum. `AgentService` conserva el modo más estricto entre el vivo y el enviado (SHOP/PUBLIC cancela la tarea) y toma el lock del run al vencer una confirmación. Falta test dedicado para ambos casos.
- [x] `AgentService` cableado al runner Lab (`core/agent_trigger.py`, gancho en `ConversationCoordinator`): sólo se crea con autonomía N2+ o `file_roots`; disparador explícito ('agente, <tarea>' con coma/dos puntos y 3+ palabras, 'tarea para el agente: ...'), cancelar/confirmar/denegar por voz sólo en la ventana de 60 s tras el anuncio TTS, ambigüedad -> panel, bloqueado en SHOP/PUBLIC, hilos y SQLite cerrados en orden. `RUNNING` agregado al enum y tests de modo estricto/vencimiento. Revisado por AGY (11 hallazgos, 8 grupos corregidos por Luna).
- [x] Planner con tool-calling NATIVO para backends locales (llama.cpp/OpenAI-compatible y Ollama), `tool_specs` nunca a remoto/LAN, JSON textual sólo como respaldo; arnés `scripts/agent_planner_eval.py`. Medición real en un solo host (RTX 3060, gpt-oss-20b vía llama-server): 36/36 expectativas, 100 % tools correctas, 0 % alucinadas, p50 ~712 ms (`docs/testing/AGENT_PLANNER_EVAL.md`). Falta repetir con qwen3.5:9b/Ollama en modo nativo y medir en hardware objetivo.
- [ ] Compartir `ConfirmationService`/`AgentService` entre `serve` y el runner Lab (hoy `/agente` en `serve` no ve confirmaciones ni puede lanzar tareas) y botón 'Nueva tarea' en el panel.
- [ ] Tool de navegador N3 aislado con tests de prompt injection. Investigación hecha (`docs/research/BROWSER_N3_OPTIONS.md`, AGY): recomienda chromium-headless-shell de Debian 13 por CDP sobre el cliente WebSocket stdlib, perfil efímero y fallback HTML sin JS; requiere ADR y medición RSS/arranque en 8/4 GB antes de aceptar.
- [x] Vista `/agente` (AgentAdminService + agent_view + rutas POST `/agente/approve|deny` con sesión+CSRF): tope de autonomía, raíces, confirmaciones pendientes con aprobar/denegar y últimos 50 eventos de `tool_events` sin contenido (`MemoryRepository.recent_tool_events`). Pendiente: en `serve` no hay `ConfirmationService` (vive en el runner Lab), así que muestra 'No disponible' hasta compartir el servicio entre procesos; botón de cancelar run del agente.

## Reglas del board

- No marcar hardware como validado sin prueba real.
- No marcar un bloque como completado si faltan tests/documentación razonables.
- Cambios de arquitectura se reflejan en ADR.
- Este archivo se actualiza al cerrar cada lote de trabajo relevante.
- No hacer commit/push sin autorización del propietario.
- Todo cambio y decisión se documenta en el mismo lote (TASKS, CURRENT_STATE, RECENT_DECISIONS, CHANGELOG, ADR); la delegación a AGY/OpenCode también se registra.
