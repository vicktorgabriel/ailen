# Changelog — AILEN

Todos los cambios relevantes del proyecto se documentarán aquí.

El proyecto usa versionado semántico durante desarrollo, con prereleases cuando corresponda.

## [Unreleased]

### Added

- **R3A AI Router Híbrido, Políticas de Privacidad Outbound, Presupuesto Cloud y Proveedores Local/LAN/Cloud**:
  - Router determinista de IA `RuleBasedRouter` con soporte para todos los perfiles de hardware (`SATELLITE`, `CLOUD`, `HYBRID`, `LOCAL`, `LAN_BRAIN`), cadenas de fallback explícitas y códigos de razón canónicos (`RULE_ONLY_INTENT`, `CLOUD_FAST_PATH`, `CLOUD_BUDGET_EXCEEDED`, `PRIVATE_REMOTE_BLOCKED`, `ALL_BACKENDS_UNAVAILABLE`, etc.).
  - Política de privacidad outbound `OutboundPrivacyPolicy` fail-closed: `RESTRICTED`/`PRIVATE` nunca se rebajan silenciosamente a `PUBLIC`; Cloud y LAN no confiable quedan bloqueados fuera del LLM.
  - `SecretResolver` para API keys desde variables de entorno o archivos owner-only; en POSIX rechaza archivos accesibles por grupo/mundo y Cloud falla cerrado sin credencial/configuración suficiente.
  - `BudgetPolicy` circuit breaker: `0 USD` significa no gastar, `None` significa sin límite interno y precios cloud desconocidos no se interpretan como cero; los precios vigentes deben configurarse explícitamente.
  - Constructor de contexto `AiContextBuilder` que produce prompts mínimos acotados en caracteres y tokens, integrando memorias y datos de negocio filtrados por `SocialPrivacyPolicy` y `OutboundPrivacyPolicy` (`src/ailen/ai/context.py`).
  - Cliente HTTP genérico OpenAI-compatible `GenericOpenAiBackend` construido exclusivamente con la librería estándar de Python (`urllib.request`), con timeouts estrictos, manejo de errores de red y parseo resiliente de respuestas y tool calls (`src/ailen/ai/http_backend.py`).
  - Backends especializados para servidor HTTP local (`LocalAiBackend`), LAN Brain con awareness de trust boundary (`LanBrainAiBackend`) y Cloud con cálculo de costos por tokens (`CloudAiBackend`).
  - Orquestador de inferencia `AiOrchestrator` que ejecuta la secuencia de backends primario y fallbacks, registra telemetría de tokens/costo en SQLite y publica eventos en `EventBus` (`src/ailen/ai/orchestrator.py`).
  - Coordinador conversacional end-to-end `ConversationCoordinator` conectando `Transcript` STT -> `AiContextBuilder` -> `RuleBasedRouter` -> `AiOrchestrator` -> `AudioInteractionCoordinator.speak()` (`src/ailen/core/conversation.py`).
  - Configuración extendida `[ai]`, `[ai.local]`, `[ai.lan]`, `[ai.cloud]`, serialización TOML recursiva/round-trip y validación de endpoint/model/pricing cuando un backend está habilitado.
  - Nuevos comandos CLI: `ailen diagnose ai` y `ailen demo ai "<prompt>" [--dry-run]`.
  - Benchmark reproducible del AI Router (`tools/benchmark_ai_router.py`) con reportes DEV en `docs/benchmarks/dev_ai_router_benchmark.md` y `.json`; las cifras se regeneran y no se extrapolan a hardware objetivo.
  - Documentos de arquitectura y POCs: `docs/research/AI_ROUTER_POC.md`, `docs/research/LOCAL_LLM_BACKEND_POC.md`, `docs/research/LAN_BRAIN_POC.md`, `docs/research/CLOUD_PROVIDER_POC.md`, `ADR-009`.
  - Estrategia formal `Lab Mode` vs `Appliance Mode` en `docs/deployment/LAB_AND_APPLIANCE_MODES.md`: Mint/Windows no se modifican persistentemente; Debian dedicado será provisionado de extremo a extremo más adelante.
  - Formato canónico de audio establecido: PCM 16-bit signed LE, mono, 16000 Hz (`src/ailen/audio/pcm.py`) con cálculo matemático de energía RMS y utilidades para tests de tonos/silencios.
  - Contratos formales y dataclasses de audio I/O, VAD, STT y TTS (`src/ailen/audio/contracts.py`).
  - VAD liviano en Python puro (`EnergyVad`) con umbral configurable y hangover para detección robusta sin dependencias de ML pesado; benchmark lógico DEV documentado sin extrapolar CPU a hardware objetivo.
  - Agrupador de audio `UtteranceCollector` con defaults actuales de pre-roll 200 ms, mínimo de habla 250 ms, timeout de silencio 700 ms y corte máximo de 15 s.
  - Compuerta Half-Duplex `AudioTurnGate` con control de estados `LISTENING_ALLOWED` y `SPEAKING_BLOCKED`, protegiendo el VAD del feedback acústico de los parlantes mediante cooldown acústico de asentamiento.
  - Backends reales de audio I/O para Debian 13 minimal basados en ALSA (`AlsaAudioInputBackend`, `AlsaAudioOutputBackend`, `AlsaDeviceEnumerator`), con lectura respetando timeout y sin inventar dispositivos cuando `alsa-utils` no está disponible.
  - Backends simulados completos (`FakeAudioInputBackend`, `FakeAudioOutputBackend`, `FakeDeviceEnumerator`, `FakeSttBackend`, `FakeTtsBackend`) para tests unitarios deterministas y ejecución en entornos CI.
  - Backend STT local offline `VoskSttBackend` con extra opcional `stt-vosk`; los valores de confidence sólo se informan si el motor los provee realmente.
  - Backend STT local alternativo `WhisperCppSttBackend` usando el CLI actual `whisper-cli` con compatibilidad best-effort para nombres legacy.
  - Backend TTS local offline `PiperTtsBackend` adaptado al CLI actual de Piper: WAV temporal, extracción del PCM/sample-rate/canales reales y control de velocidad/volumen.
  - `AudioInteractionCoordinator` integrando captura, turn gate, VAD, STT, TTS, playback y nivel de boca RMS básico; recupera estado/gate ante excepciones de STT/TTS/playback.
  - Publicación de eventos de audio de bajo peso en `EventBus` (`VOICE_STARTED`, `VOICE_ENDED`, `SPEECH_CAPTURED`, `TRANSCRIPT_READY`, `SPEECH_STARTED`, `SPEECH_FINISHED`, `AUDIO_ERROR`) sin transportar PCM.
  - Comandos CLI nuevos: `ailen diagnose audio`, `ailen demo vad`, `ailen demo stt`, `ailen demo tts`.
  - Suite de benchmark reproducible `tools/benchmark_audio.py` y reportes en `docs/benchmarks/dev_audio_benchmark.md` y `.json` etiquetados explícitamente con `DEV MACHINE — NO HARDWARE TARGET`.
  - Documentos de investigación: `docs/research/AUDIO_IO_POC.md`, `docs/research/STT_BACKEND_POC.md`, `docs/research/TTS_BACKEND_POC.md`.
- **R2A Presencia Física y Face POC**:
  - Motor lógico `FaceAnimator` y modelo `FacePose` completamente desacoplados de librerías gráficas, con parpadeo no periódico con jitter, micro-saccades, interpolación suave de mirada y apertura de boca proporcional a `speech_level`.
  - Backend gráfico POC `TkinterFaceController` usando canvas 2D vectorial, sin dependencia pip obligatoria pero con `python3-tk`/stack gráfico del sistema; consumo real pendiente de benchmark físico.
  - `NullFaceController` integrado con `FaceAnimator` para operación headless de primera clase en nodos sin pantalla.
  - `VisionDebouncer` temporal para presencia física basado en `presence_debounce_seconds` (2.0s), eliminando parpadeos espurios y oscilaciones de presencia.
  - Backend de cámara POC `OpenCvVisionBackend` con clasificador Haar cascade liviano a 5 FPS y 320px, sin reconocimiento facial ni almacenamiento biométrico, con degradación limpia.
  - Integración en `InteractionCoordinator` enlazando presencia debounced con transiciones de estado, mirada y expresiones en el rostro.
  - Comandos CLI de demo: `ailen demo face` (con `--gui` y `--headless`) y `ailen demo vision`.
  - Suite de benchmark reproducible (`tools/benchmark_presence.py`) y reporte en máquina de desarrollo (`docs/benchmarks/dev_presence_benchmark.md`).
  - Documentación de investigación: `docs/research/FACE_BACKEND_POC.md` y `docs/research/VISION_BACKEND_POC.md`.
- `SettingsService` (contrato Web <-> configuración, MODULE_CONTRACTS §16): allowlist explícita de campos administrables desde el panel (identidad del personaje, nodo, pantalla, audio, visión, voz, comportamiento social, canal de updates). Validación server-side completa antes de guardar; claves desconocidas rechazadas; escritura atómica del TOML.
- Vista `/config` responsive mobile-first: GET con valores efectivos, POST con CSRF, mensajes de éxito/error por campo, sin JS obligatorio, sin secretos renderizados.
- Sección de identidad del personaje: nueva sección `[identity]` en configuración con `display_name` (default neutro "Asistente"); AILEN queda como marca/plataforma, nunca como nombre hardcodeado del personaje.
- Autenticación administrativa persistente (`PersistentAuthService`) manteniendo el contrato `AuthService`: credencial en SQLite (migración `0002_admin_credentials`), PBKDF2-HMAC-SHA256 con 600k iteraciones, salt aleatorio por credencial, comparación constant-time, lockout por IP, fail-closed sin credencial.
- CLI `ailen admin set-password`: alta/cambio de contraseña vía `getpass` (nunca argv visible en `ps`), longitud mínima 8, confirmación doble; ejecuta migraciones automáticamente.
- Hardening HTTP baseline en el servidor del panel: límite de body (1 MiB -> 413), métodos permitidos explícitos (405), exigencia de `application/x-www-form-urlencoded` en POST (415), headers `Content-Security-Policy`, `Referrer-Policy`, `Cache-Control: no-store`, timeout de socket por conexión.
- Resiliencia del panel: fallos de diagnóstico/status ya no tiran abajo dashboard ni páginas (se muestra estado UNKNOWN / aviso, nunca información falsa).
- Smoke tests HTTP sobre TCP real (headers, 413, 405, 415, flujo login/config) sin Internet.
- EventBus ligero in-memory con soporte para suscripciones tipadas/globales, aislamiento de excepciones en listeners y trazabilidad por `correlation_id`.
- SocialEngine determinista con soporte para modos `HOME`, `WORKSHOP`, `SHOP`, `PUBLIC`, `PRIVATE` y `SLEEP`, cooldowns de saludos y generación de intenciones sin hardcodear frases.
- `SocialPrivacyPolicy` determinista que aísla de forma inviolable las memorias privadas en modos públicos y comerciales (`PUBLIC`/`SHOP`).
- `InteractionCoordinator` como baseline de coordinación entre observaciones de presencia, StateManager, SocialEngine y EventBus.
- `PersonalityBoundary` para garantizar que la evolución de rasgos de personalidad no altere seguridad, permisos, herramientas ni presupuestos.
- Extensión del modelo `AssistantIdentity` con `display_name` y desacoplamiento limpio entre nombre del producto/plataforma (`AILEN`) y nombre visible del asistente.
- Nombre estable del proyecto/plataforma: `AILEN` — Asistente Inteligente Local, Evolutivo y Natural.
- CLI `ailen serve` integrada con el panel web local y el estado real de Foundation.
- Package data para templates, assets web y migraciones SQLite en builds instalables.
- Error tipado `TOOL_ARGS_INVALID` y baseline de calidad con `ruff` + `mypy`.
- Definición inicial del producto y casos de uso hogar/taller/comercio.
- Arquitectura híbrida local/LAN/cloud.
- Separación explícita entre identidad del asistente y motor LLM.
- Perfiles de hardware `Satellite/Cloud/Hybrid/Local/LAN Brain`.
- Estrategia de administración web responsive sin app móvil obligatoria.
- Plan de actualización por releases con health check y rollback.
- Roadmap inicial hasta `1.0.0` comercial.
- Documentación base inspirada en la disciplina de AndesKey.

### Fixed

- Flujo de wake del `InteractionCoordinator`: presencia durante `SLEEP` ahora produce `WAKE` antes de permitir un saludo posterior, en lugar de perder el estado de sueño al transicionar.
- Login administrativo ahora verifica realmente **usuario + contraseña**; el usuario persistido dejó de ser un dato decorativo.
- SQLite restringe el archivo de datos a modo `0600` en POSIX porque contiene memoria privada y material derivado de credenciales.
- `SettingsService.update()` usa semántica de patch parcial; la traducción de checkboxes HTML ausentes a `false` pertenece a la capa Web.
- Una ruta explícita de configuración o `AILEN_CONFIG` inexistente falla de forma visible en lugar de caer silenciosamente a defaults.
- Cookie de sesión sin `Max-Age` duplicado/hardcodeado; el TTL autoritativo queda en `AuthService`.

### Decisions

- Debian 13 stable amd64 netinst/minimal queda aceptado como baseline del appliance (ADR-008). Sin desktop completo; con Tkinter se usa sólo stack gráfico mínimo y los nodos headless no instalan X.
- `web.host`/`web.port` NO son editables desde el panel: cambiar el bind en caliente puede exponer el panel o dejar afuera al operador; se administran por archivo/CLI y aplican al reiniciar (ver ADR-007).
- La credencial administrativa vive en SQLite (tabla dedicada, fila única) y no en variables de entorno ni en el TOML versionado (ver ADR-007).
- PBKDF2-HMAC-SHA256 (stdlib) como KDF baseline del panel: sin dependencias externas sobre hardware objetivo; reemplazable por Argon2 vía ADR si se justifica.
- Banghó Zero G05 de 8 GB como primer prototipo físico.
- SF20BA 8 GB y 4 GB como objetivos posteriores de optimización.
- Hardware de 2 GB tratado como candidato viable para `Satellite/Cloud`.
- SQLite como baseline de memoria persistente.
- FTS5 antes de introducir bases vectoriales.
- Herramientas controladas; sin shell general para el LLM.
- Personalidad y memoria locales por defecto.

## [0.1.0-dev.0] - 2026-08-21

### Added

- Scaffold documental inicial del proyecto.
- `README.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `CHANGELOG.md`, `VERSION` y documentación de contexto.
- Panel web skeleton responsive sin SPA (stdlib `http.server`, carril Web/Mocks/Contracts):
  login/logout con sesiones y CSRF, dashboard con datos sintéticos, páginas skeleton
  (Comercio, Personalidad, IA, Audio/Cámara, Sistema), APIs `/api/status`, `/api/health`, `/api/ping`.
- Servicios web fake: `FakeAuthService` (PBKDF2, lockout, sin contraseña default;
  se configura vía `AILEN_ADMIN_PASSWORD`) y `FakeStatusService`.
- Contratos y fakes de backends: `AiBackend` + `FakeAiBackend`, router reglas
  (`RuleBasedRouter`), `SttBackend`/`TtsBackend` + fakes, `VisionBackend` +
  `FakeVisionBackend`, `FaceController` + `NullFaceController`, protocolo `Tool`
  con validación de argumentos y tools fake (`clock`, `volume`, `notes`).
- `adapters.build_fake_backends()` como punto único de cableado de backends simulados.
- Tests web y de contratos/fakes sin Internet (`tests/web/`, `tests/fakes/`).

### Notes

- `AILEN` queda fijado como identidad estable del proyecto/plataforma; el nombre, voz y apariencia del personaje serán configurables por instalación.
- La verificación marcaria/legal del nombre queda pendiente antes de comercialización formal.
