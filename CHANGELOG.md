# Changelog — AILEN

## [0.4.0-dev.0] — 2026-08-31

### Changed
- 2026-10-24 R5C: el planner del agente usa function-calling nativo en backends locales (gpt-oss/llama.cpp y Ollama); `AiRequest.tool_specs` y mensajes `tool` sólo viajan a destinos locales; filtro incremental de canales Harmony en streaming; historial del agente conserva los argumentos de cada llamada (acotados/redactados, nunca en auditoría). Arnés de evaluación `scripts/agent_planner_eval.py` y reporte `docs/testing/AGENT_PLANNER_EVAL.md`. Revisión adversarial AGY (Gemini 3.8) y correcciones de Codex Luna. Suite: 1463 tests.
- 2026-10-24 R5C: `AgentService` cableado al runner Lab con disparador por voz explícito y confirmación acotada a ventana tras el anuncio; estado `RUNNING`; correcciones de la revisión adversarial (AGY). Implementado por Codex Luna y AGY Gemini 3.8. Suite: 1391+ tests.
- 2026-10-23 R5C: planner del agente sobre el orquestador (`ai/agent_planner.py`), `AgentService` de tareas en segundo plano y ADR-016 (navegador N3, Proposed). Corrección de carrera en `AgentLoop.resume()`. Implementado por Codex Luna, AGY (Gemini 3.8) y OpenCode Go; revisión cruzada AGY. Suite: 1354 tests.
- 2026-10-23 R5C: panel `/agente` (confirmaciones pendientes, tope de autonomía, raíces y auditoría de tools) y `ConfirmationService.pending_requests()`; AGY pasa a `gemini-3.8-flash-high` y OpenCode usa un modelo gratuito o, si el cupo está agotado, OpenCode Go. Se eliminó el agente Spark de la documentación, scripts y configuración.
- 2026-10-23 R5C (ronda 2): bucle de agente de Core (`core/agent_loop.py`, Codex Luna), investigación del navegador N3 (`docs/research/BROWSER_N3_OPTIONS.md`, AGY) y corrección de seguridad en el bridge realtime: el texto/summary de tools no PUBLIC ya no sale al proveedor remoto (hallazgo de revisión automática). AGY y OpenCode agotaron su cupo gratuito durante la ronda; el panel del agente pasó a Codex Luna.
- 2026-10-23 R5C: servicio de confirmación humana (`core/confirmation.py`), tool de archivos N2 (`tools/builtin/files.py`, `agent.file_roots`) y base del proveedor realtime (`ai/realtime/`). Implementados por Codex Sol (confirmación y correcciones de seguridad), OpenCode DeepSeek (archivos) y AGY Gemini (realtime); revisión adversarial cruzada (AGY/OpenCode) con 25 hallazgos verificados y corregidos (hardlink/TOCTOU, append sin confirmar, contenido en auditoría, JSON no objeto, resultado de tool sin filtrar, autonomía inválida). Suite: 1286 tests.
- 2026-10-23 R5C: contrato de niveles de autonomía ADR-014 (N1–N3) en `ToolContext`/`ToolExecutor`, config `[agent].max_autonomy_level` y campo en el panel. Sin cambios de comportamiento hasta que existan tools N2/N3. Tests en `tests/unit/test_tool_autonomy.py` (OpenCode DeepSeek); revisión con gpt-oss local vía llama.cpp.
- 2026-10-23 R5: `/herramientas`, `/vision`, `/rostro`, `/personalidad`, `/sistema` y
  `/setup` leen la configuración efectiva (módulos `web/*_view.py` con funciones
  `*_context`) y dejan de mostrar latencias, benchmarks, modelos de cámara, estados
  "Habilitada" y botones de recarga inventados. `/setup` ya no fabrica 8192 MB si el
  hardware no se detecta. Corrige escala del umbral de visión, sección de guardado de
  `/rostro` y `/herramientas`, y agrega banner de guardado/error. Implementado con
  AGY (herramientas, visión, rostro) y OpenCode (personalidad, sistema, setup);
  cableado y gates por el agente principal. Suite: 1190 tests.
- 2026-10-23: auditoría delegada de `/memoria` y `/diagnostico` (AGY sin hallazgos;
  OpenCode DeepSeek free con 11, verificados por el agente principal). Corregidos:
  el log de cierre de conexión ya no incluye query string, y `execution_mode`
  pasa a `no_backends` cuando `--no-camera --no-audio --no-ai` desactivan todo, de
  modo que el diagnóstico no lo presenta como medición real.
- 2026-10-23: ADR-014 (agente de Core con niveles de autonomía N1–N3) y ADR-015
  (proveedor de voz en vivo opcional) aceptados; `PRODUCT.md` §9 ajustado. AGY
  (Gemini) y OpenCode (DeepSeek free) quedan como agentes auxiliares de desarrollo
  obligatorios para delegación; AGENTS.md, REGLAMENTO.md y AGENT_HANDOFF.md
  documentan la regla y que todo cambio debe documentarse. Sin cambios de código.
- R5 (2026-10-02): `/memoria` reemplaza maquetas por CRUD/búsqueda literal paginada
  y exportación JSON de recuerdos explícitos reales, con opt-in privado,
  confirmaciones y CSRF. No altera notas, recordatorios ni historial.
- `/diagnostico` muestra health del proceso, comprobaciones LabDoctor explícitas
  y métricas allowlisted de la última sesión Lab finalizada; diferencia muestras
  reales, simulación y reportes legacy sin procedencia. No expone logs crudos.
- `serve` deja periféricos no iniciados en UNKNOWN; LabDoctor omite discovery
  local cuando `ai.local.enabled=false`. Reportes Lab agregan procedencia y
  número de muestras sin modificar audio/inferencia.
- La selección local de instalación queda ligada a evidencia por
  `(hardware_class, model_id, runtime)`: soporte declarado no sustituye una
  medición. Runtime, CPU/CUDA y `gpu_layers` se eligen coherentemente desde la
  calificación; no se infiere offload GPU ni se admite offload parcial sin
  implementación y benchmark.
- AGY/Antigravity y OpenCode quedan retirados end-to-end del producto. Configs
  antiguas migran a `provider=auto` con warning y no existe adapter/runtime/UI/
  secreto capaz de reactivarlos; sus benchmarks históricos se conservan.
- Provider Manager admite múltiples `remote:<id>` con secretos/prioridad/health/
  cooldown propios y transportes SSE reales para OpenAI Responses (`store=false`),
  OpenAI Chat-compatible y Anthropic Messages. OpenAI, Anthropic, DeepSeek, Kimi
  y MiniMax son presets no probados, sin modelo hardcodeado ni gasto en esta pasada.
- Los defaults internacionales fijan Kimi en `api.moonshot.ai/v1` y MiniMax en
  `api.minimax.io/v1`; no seleccionan endpoints chinos implícitamente. Sólo
  OpenAI anuncia catálogo `live`; el resto permanece `manual` hasta verificar
  su endpoint oficial específico.
- El provisioning detecta hardware y genera un plan consentido con runtime,
  mejor modelo target-qualified que entra, fallback, contexto, offload, reservas,
  hash/licencia y assets. Candidatos no se instalan automáticamente y perfiles
  Lab ya no fijan un modelo.
- La selección aprobada puede activarse explícitamente después de verificar el
  artefacto exacto. Un manifiesto atómico `0600` liga hardware, runtime, modelo,
  contexto, offload y hash; el runner lo consume sin replantear por turno y lo
  ignora por completo cuando local está deshabilitado.
- Los envelopes de 16/32/64+ GB dejan de heredar un techo fijo de 6 GB: reservan
  margen proporcional y escalan por RAM/VRAM disponible más evidencia objetivo.
  El runtime local configurado es vinculante y un modelo automático no entra al
  factory si sigue `candidate` o si su evidencia pertenece a otro runtime.
- Captura incorpora target PipeWire explícito y cadena NS -> gain dB -> AGC
  acotado con gate/hold/release -> limiter. `pipewire` conserva el default nativo
  de `pw-record` sin exigir `pactl`, mientras `pipewire:<node>` nunca pierde su
  target. Se elimina `audio.input_volume` decorativo; calibración mide
  silencio/voz/SNR/clipping/WER sólo en RAM, propone el gate desde silencio y no
  persiste PCM.
- Telemetría de captura separa RMS raw, salidas DSP intermedias y clean final.
  El evento de drain TTS cancelado precede al contador cero y a la siguiente
  inferencia sobre el backend serializado.
- La calibración de ruido del panel ya no devuelve RMS hardcodeado: mide el
  input real de forma acotada y RAM-only o informa que no está disponible.
- `lab calibrate-voice` usa la cadena DSP canónica y, sin `--device`, compara un
  conjunto acotado/deduplicado de fuentes observables. Expone RMS/peak/SNR por
  etapa, clipping, ganancia, falsos VAD y fuente efectiva sin persistir PCM.
- El calibrador físico compara por defecto 30/75/100 cm y perfiles
  `raw`/`noise_only`/`full`; Easy Effects queda como referencia externa sin
  doble preamp/AGC. La primera campaña nueva sobre USB Jieli reunió sólo cinco
  muestras a 75 cm, WER 0,5–1,0 y falsos triggers; queda registrada como
  inconclusa, sin promover configuración. Para equipos reciclados se prioriza el
  micrófono integrado/nativo de la placa, siempre sujeto a calificación física.
- `/audio` deja de prometer AEC o latencia Piper fija y elimina la escritura
  incorrecta de `amixer sset Master`: la medición Web sigue siendo backend-side,
  acotada y read-only. El form guarda explícitamente campos `audio.*` y
  `speech.*` bajo el handler combinado.
- STT conserva confidence real en bandas configurables; audio dudoso repregunta
  aunque produzca varias palabras y el piso de acciones sigue separado en 0.72.
- El habla incremental usa IDs de generación, serializa TTS no concurrente,
  descarta PCM stale y limita joins. Un turno interrumpido no se persiste como
  respuesta assistant completa; stop de playback y drain ONNX se miden aparte.
- `provider=auto` decide por modalidad, privacidad, complejidad, disponibilidad y
  elegibilidad realtime; las prioridades quedan para equivalentes/fallbacks.
- ModelPlanner ordena por calificación, evidencia y `quality_rank` dentro de la
  reserva segura y mantiene un fallback pequeño. Nuevo manifiesto/CLI de
  calificación no descarga pesos ni inventa hashes.
- Nuevo `ailen lab calibrate-voice` para matriz física WebRTC/Vosk y barge-in
  guiado, sin WAV/PCM persistente ni cambios automáticos de configuración.
- `demo ai` deja de inventar un backend local simulado cuando todos los backends
  están deshabilitados; degrada de forma explícita.
- El turno de voz conserva confianza STT real, motor, duración, identificador,
  origen barge-in, truncamiento y alternativas hasta Core. Las tools con efecto
  repreguntan ante audio dudoso/truncado; un barge-in completo sigue siendo
  ejecutable y una consulta de lectura no se bloquea por esa guarda.
- Conversación por voz solapa streaming real del LLM con segmentación segura y
  TTS/playback incremental en una cola bounded. Barge-in cancela frases futuras y
  evita concatenar el fallback de otro proveedor tras una salida parcial.
- Ollama y llama.cpp quedan tras una interfaz local común. Un llama.cpp propiedad
  de AILEN carga un GGUF verificado bajo demanda; el monitor puede liberar sólo
  modelos/runtimes ociosos bajo presión de memoria.
- Perfiles 4/8/16/32/64+ GB incorporan envelopes de contexto/modelo/RAM libre. Son
  límites de planificación con benchmark objetivo pendiente, no afirmaciones de
  realtime ni calidad.
- Saludos y charla abierta vuelven al LLM. La personalidad de instalación es una
  asistente general rioplatense y usa el taller sólo cuando el contexto es técnico.
- Integración de IA corregida para separar el producto local-first de los
  proveedores remotos opcionales. `ai.local.enabled=false` ahora impide discovery,
  construcción, arranque, prewarm, parser semántico y fallback local.
- `/ia` controla el proveedor preferido y prioridades reales, muestra selección
  versus última inferencia verificada, catálogos con procedencia, secrets
  separados y reinicio requerido. Cada remoto conserva una ruta propia.
- Requests externos privados se reconstruyen en el boundary de salida: sólo
  turno actual e instrucciones orales genéricas; sin historial, memoria,
  personalidad/persona, capabilities, tools, paths ni secretos.
- Los experimentos AGY NDJSON y OpenCode se conservaron como evidencia de
  rechazo: AGY fue funcional pero demasiado lento para voz en ASRock contendido;
  OpenCode Free produjo respuestas sin texto visible y 429.
- R6 Vertical 1 incorpora updates firmados en `LAB_SIMULATION`: manifiesto JSON
  estricto, Ed25519/OpenSSL sobre bytes exactos, fuente HTTPS bounded, downloader
  reanudable, CAS inmutable, journal atómico y aprobación efímera.
- Releases verificadas se extraen con política tar fail-closed, se preparan por
  rename atómico y atraviesan preflight/switch/probation/rollback mediante
  fronteras inyectadas. No se restauran ni bajan automáticamente schemas SQLite.
- Nuevo panel autenticado `/actualizaciones` y API CSRF consumen sólo DTOs del
  `UpdateAdminService`; no reciben paths/URLs/hashes ni ejecutan shell, tar o
  systemd. El lifecycle continúa aunque se cierre el navegador.
- Aceptación E2E sintética cubre activación sana, rollback de candidato unhealthy
  y reanudación ETag/Range con re-verificación y re-aprobación. Appliance mode
  permanece honestamente deshabilitado hasta implementar `ailen-updaterd` y
  validarlo físicamente; no se habilitan updates automáticos.
- Alineado versionado/documentación con el estado real: R1-R3C integrados,
  R4/R5 activos y 1145 tests como baseline completo actual tras retirar las
  superficies específicas de AGY/OpenCode; Ruff, mypy (164 módulos),
  diff-check y wheel limpio de 202 entradas permanecen en verde.
- `ADR-006` aceptado como baseline técnico provisional para 0.4.x; la elección definitiva de appliance sigue sujeta a benchmarks en hardware objetivo.
- Nuevo bloque R5B para un `FacePack` realista, versionado y extensible. Los videos H3 actuales son corpus crudo: no se integran al runtime ni al wheel hasta clasificación/recorte y diseño del motor.
- `facepack` pasa a ser el renderer lógico por defecto; `portrait` queda sólo como opción legacy manual y `pixel` como opción explícita para hardware muy limitado.
- Auditoría R5 distingue páginas conectadas de maquetas: memoria/diagnóstico/personalidad/vision/tools siguen abiertas hasta eliminar datos/defaults sintéticos y leer servicios reales.
- R5B incorpora `facepack` como default lógico: engine C++17 con C ABI, wrapper
  `ctypes`, pack externo versionado/checksummed y degradación limpia a headless.
  `portrait`/`pixel` permanecen sólo como elecciones manuales.
- Los 85 videos H3 fueron clasificados visualmente. Los MP4 siguen como materia
  prima fuera del wheel; runtime decodifica JPEG/libjpeg y nunca reproduce video.
- Estados persistentes usan scheduler no periódico de base/microacciones.
  La QA física demostró que recortar ojos o boca de un clip H3 y componerlos
  sobre otro cambia geometría/identidad aunque el tracking sea correcto.
  FacePack 1.6 conserva los gestos oculares y speech actuales como movimiento
  full-frame real; no mezcla rostros, no usa crossfade y retoma el affect
  semántico al terminar speech. ROI composable permanece soportado sólo para
  futuros assets realmente segmentables.
- Pack desktop-lab: 90.25 MB, 79 secuencias/2.888 frames lógicos/6 estados, 39 emociones,
  28 microacciones y 10 speech; benchmark ASRock y límites en ADR-012.
- Preflight valida ABI + FacePack independientemente de Tkinter y expone fallo
  recuperable como `WARN` con display facial deshabilitado, no como falso `PASS`.
- La lista dinámica del FacePack alimenta la allowlist de `FaceExpressionTool` y
  de emoción conversacional; Pack B puede exponer un id nuevo sin recompilar la
  librería ni duplicar el catálogo del renderer en Core.
- R5B ejecuta timing natural (`duration=0`), anchors/transiciones, prioridad,
  `gaze_compatible`, estilos de speech y retorno visual subordinado a Core. Los
  clips sin salida authored usan sus propios frames curados en reversa y comparten
  payload, evitando el salto abrupto sin sintetizar imágenes. ABI 1.4 suma copia
  bilinear segura y tracking de capas opcionales; captura excepciones y serializa cada handle.
- Validación física focal: `blink_double` dejó de deformar ojos al usar su clip
  completo; los diez `talk_*` dejaron de deformar labios/dientes y su seam es
  apenas perceptible a velocidad real.
- Gate histórico de R5B: 767 tests, Ruff y mypy (146 módulos AILEN + 6 del compilador)
  limpios; C++17 compila con warnings como errores, diff-check limpio y wheel de
  183 entradas/3.018.784 bytes inspeccionado sin MP4/FacePack/binarios nativos/raw H3.
- Gate integrado posterior: 1019 tests, Ruff, mypy en 157 archivos fuente y
  diff-check limpios; wheel de 195 entradas/3.069.600 bytes con updater/template
  presentes y sin modelos, multimedia, FacePack, binarios nativos, keys ni Lab.

### Release gate
- No crear tag/release hasta auditar el working tree, ejecutar suite completa + Ruff + mypy + `git diff --check`, construir/inspeccionar wheel y verificar ausencia de secretos/assets crudos.

- **R4 camera portability + persistent reminders (2026-08-24)**:
  - `[vision].camera_source` incorpora `auto|usb|rtsp`: USB/RTSP estrictos, auto V4L2-first con fallback RTSP; compatibilidad legacy sin permitir que el flag viejo sobreescriba selección explícita.
  - Debian Lab queda preparado para webcam USB reciclada; NC250 permanece como cámara RTSP opcional de LAN y sus credenciales no se persisten.
  - Nueva migración SQLite `0004_reminders`, `ReminderItem`, `RemindersTool`, `ReminderService` y `REMINDER_DUE`; recordatorios temporales ya no son secuestrados por `NotesTool`.
  - Scheduler publica eventos y el runner difiere TTS hasta un estado acústicamente seguro; prueba audible física pendiente.
  - Base Lab Debian migrada a schema 4. Cierre software actual: 521 tests, Ruff limpio, mypy limpio en 131 archivos y diff-check limpio.

- **Debian clean-install hardening + MPRIS music transport (2026-08-24)**:
  - `MprisMusicService` controla un reproductor MPRIS local mediante `playerctl` con `shell=False`, timeout y fail-closed; Lab lo cablea detrás de `MusicTool`.
  - Las búsquedas de canciones por texto libre se rechazan explícitamente hasta disponer de catálogo/proveedor; no se reinterpretan como archivo/URL.
  - `diagnose ai` y `demo ai` ejecutan migraciones SQLite antes de consultar presupuesto/`ai_usage`, corrigiendo un fallo visible sólo en instalaciones limpias.
  - Handoff de agentes actualizado a R3C/R4 para Gemini/OpenCode; el texto de Foundation quedó obsoleto.
  - Validación Debian: 503 tests pasan, 1 omitido; Ruff limpio con excepción local `EXE002` por montaje NTFS y mypy limpio en 129 archivos. Reproducción audible MPRIS sigue pendiente de prueba física.

- **Natural tool intent + NC250 lab discovery (2026-08-23)**:
  - Variantes naturales/ASR de reloj y notas; recuperación contextual de notas recientes sin LLM general.
  - Clarificación fail-safe para fragmentos ambiguos y parser semántico acotado por dominio.
  - `ai.local.intent_model` opcional; laboratorio usa 3B para intención y 9B para conversación, sin descargas implícitas.
  - NC250 descubierta vía Bonjour y RTSP H.264 720p + pista de audio verificados; credenciales permanecen fuera de configuración/documentación.
  - Suite actual: 491 tests; Ruff, mypy (129 archivos) y diff-check verdes.

Todos los cambios relevantes del proyecto se documentarán aquí.

El proyecto usa versionado semántico durante desarrollo, con prereleases cuando corresponda.

- **Voice Understanding / Semantic Tool Fallback — 2026-08-23**:
  - Auditoría de una sesión física real mostró 24 utterances, 22 transcripciones aceptadas y sólo 5 activaciones de tools; frases ASR como `hora es`, `notas tengo` y `nota comprar estaño mañana` caían innecesariamente al LLM.
  - `IntentResolver` ahora tolera variantes ASR frecuentes para hora, notas y volumen sin sumar latencia; `SttQualityEvaluator` repromptea fragmentos de una sola palabra demasiado ambiguos en vez de enviarlos al LLM.
  - Nuevo `SemanticToolIntentResolver`: usa exclusivamente un backend local confiable como parser JSON acotado cuando las reglas fallan. El modelo sólo puede proponer tools registradas, no-network y no-destructive; Core revalida argumentos y `ToolExecutor` mantiene toda la autoridad.
  - La resolución semántica se activa sólo para frases con indicios de tools/contexto corto, evitando una segunda inferencia para charla normal. En Ryzen 5 5500 + `qwen3.5:9b`, fallback contextual medido ~1.3-1.9 s; comandos deterministas comunes quedan ~1-15 ms.
  - Búsqueda de notas mejorada: phrase match primero y fallback por tokens significativos con LIKE escapado; consultas como `qué tengo que comprar mañana` recuperan `comprar estaño mañana`. `NotesTool.search` devuelve el contenido útil, no sólo el conteo.
  - Prompt conversacional reduce repetición: el estado de cámara es contexto silencioso salvo relevancia, no se repiten datos previos de rutina y se eliminan coletillas genéricas repetitivas al final de respuestas con contenido.
  - `ClockTool` corregido para hora local del sistema (`datetime.now().astimezone()`); antes respondía UTC.
  - Integración real sin efectos físicos: `hora es` -> ClockTool, `nota comprar estaño mañana` -> NotesTool, `notas tengo` -> NotesTool, `cosa tengo que comprar mañana` -> semantic local -> NotesTool, y `ajá un poquito más el volumen` -> VolumeTool.
  - Cierre de calidad: 487 tests, Ruff limpio, mypy limpio en 129 source files y `git diff --check` limpio antes del build final.

- **Cierre auditado post-oX Alpha — R3C / Vision / STT (2026-08-23)**:
  - Persistencia conversacional real cableada en `LabRunner`: cada sesión usa un `sess-*` SQLite propio, persiste turnos `user/assistant` después de construir el request para evitar duplicar el mensaje actual y cierra `ended_at` al apagar. Prueba multi-turn real con `qwen3.5:9b` recuperó correctamente contexto del turno anterior.
  - Política outbound para tools separada de la disponibilidad cloud mediante `[network].outbound_web_enabled`; un proveedor web ya no depende de que exista backend cloud.
  - `ToolExecutor` usa worker daemon para timeouts no destructivos; un timeout deja de bloquear shutdown, pero no puede matar de forma segura un hilo Python ya ejecutando. Tools `destructive=true` quedan fail-closed (`DESTRUCTIVE_EXECUTION_UNSUPPORTED`) hasta disponer de aislamiento cancelable.
  - `WebSearch` acota/sanitiza campos del proveedor y marca resultados como contenido web no confiable antes del LLM; `WebFetch` es HTTPS-only, bloquea credenciales embebidas, exige Content-Type permitido y mantiene defensas SSRF/redirect.
  - `MusicTool` deja de fingir reproducción: sin backend musical real devuelve `UNAVAILABLE`; `LocalMusicService` queda sólo como backend inyectable de prueba/estado. Volumen no inventa un nivel base si no puede leerlo y `SystemStatusTool` no expone rutas de disco.
  - Benchmark Vision corregido para no clonar métricas de frames no observados, agrega fase `uncontrolled` y auto-selección de cámara física como el Lab. Muestra no controlada posterior: `/dev/video1`, YuNet, 20 frames, inferencia ~9.8 ms avg; no se infiere precisión sin ground truth.
  - Benchmark STT rechaza engines desconocidos explícitamente y garantiza cleanup del backend de captura en grabación autorizada. Whisper.cpp sigue `NOT_INSTALLED`; no se descargó ningún modelo.
  - Cierre de calidad: 478 tests offline, Ruff limpio, mypy limpio en 128 source files y `git diff --check` limpio antes del build final.

- **Auditoría R3C + STT Quality + Vision YuNet Hardening**:
  - Corrección de defectos reales detectados en auditoría:
    - `ToolExecutor`: el timeout ya no bloquea al llamador hasta que la herramienta colgada termina (se elimina el `shutdown(wait=True)` implícito del context manager); se agregan gates de política para `requires_network` (denegación `NETWORK_UNAVAILABLE` sin conectividad) y `destructive` (requiere `confirm=true` explícita y prohibición en modos `SHOP`/`PUBLIC`).
    - Máquina de estados: `PROCESSING -> ATTENTION` ahora es transición válida; el runner ya no queda desincronizado tras cada conversación con rostro presente. `PROCESSING -> LISTENING` sigue prohibido (regresión testada).
    - `IntentResolver`: las notas creadas por voz conservan mayúsculas y puntuación originales; la query de `web_search` se extrae del texto crudo de forma insensible a mayúsculas y signos iniciales (antes quedaba desalineada con "¿" o inicial mayúscula); una búsqueda web explícita ("buscá en internet X") ya no es secuestrada por los filtros negativos conceptuales.
    - `MemoryRepository.get_session_messages()`: mantiene el fix "últimos N en orden cronológico" y agrega desempate por `rowid` cuando `created_at` colisiona.
    - Preflight: si `detector=yunet`, instancia realmente `FaceDetectorYN.create()` durante el chequeo (valida ONNX legible, no basta con que el archivo exista) y valida rango de `detector_score_threshold`; Haar valida carga real del cascade.
    - `WebFetchTool`: cierre explícito del body de `HTTPError` en redirecciones y errores.
  - Nuevos benchmarks reproducibles, CPU-first y sin descargas:
    - `ailen lab benchmark-vision`: mide latencia por frame del detector real (avg/p50/p95/max), tasa de detección, confianza avg/min y rangos de gaze por fase (`--phase empty|face|movement`), exporta JSON en `runtime/lab/vision_benchmarks/`. Sin GUI ni persistencia de frames.
    - `ailen lab benchmark-stt`: pasa el mismo WAV por múltiples motores (`--engines vosk,whisper_cpp`) comparando transcripto y latencia; WER propio con normalización española (minúsculas, puntuación básica, whitespace); soporta `--wav` repetible, `--reference`, `--record N --out ruta` (grabación sólo con autorización explícita) y `--json`. Motores o modelos ausentes reportan `NOT_INSTALLED`; nunca descarga.
    - Instrumentación de `OpenCvVisionBackend`: contadores `frames_processed` y `last_inference_ms`.
  - Mediciones físicas en host de desarrollo (Ryzen 5 5500, CPU): YuNet ~49 ms avg / p95 ~91 ms a 640x480 con confianza ~0.91-0.92 (válido a 5 FPS); Haar ~67 ms avg con picos >500 ms y sin confianza. Vosk small-es sobre utterance Piper: WER 0.143 en muestra única. Whisper.cpp: `NOT_INSTALLED` (sin descarga).
  - Suite ampliada a 468 tests offline; Ruff limpio, mypy limpio en 128 archivos fuente, diff-check limpio y wheel reproducible en verde.

- **R3C Product Behaviors + Controlled Tools + Safe Web Boundary**:
  - Implementación del subsistema de herramientas controladas `ToolRegistry` (`src/ailen/tools/registry.py`) con catálogo explícito por allowlist, prohibiendo importaciones dinámicas arbitrarias.
  - Implementación de `ToolExecutor` (`src/ailen/tools/executor.py`) aplicando validación de schemas de argumentos (`validate_args`), verificación de permisos por `SocialMode`, niveles de privacidad (`PrivacyLevel`), timeouts acotados por hilos, eventos en `EventBus` (`TOOL_REQUESTED`, `TOOL_COMPLETED`) y auditoría SQLite sanitizada con redacción de credenciales en `tool_events`.
  - Intent resolver determinista conservador `IntentResolver` (`src/ailen/tools/intent_resolver.py`) para extraer intenciones y argumentos estructurados (`clock`, `timer`, `volume`, `music_play`, `music_pause`, `music_resume`, `music_next`, `music_stop`, `music_status`, `notes_create`, `notes_list`, `system_status`, `web_search`), con filtrado estricto de casos negativos conceptuales (ej. "volumen de un cilindro", "batería de notebook", "explicar temporizador") para prevenir falsos positivos.
  - Herramientas locales iniciales:
    - `ClockTool` (`src/ailen/tools/builtin/clock.py`): hora y fecha con proveedor inyectable.
    - `TimerTool` y `TimerService` (`src/ailen/tools/builtin/timer.py`): temporizadores en memoria thread-safe con creación, listado y cancelación.
    - `VolumeTool` y `SystemAudioVolumeService` (`src/ailen/tools/builtin/volume.py`): control seguro de volumen en Linux Mint/Debian (`wpctl`/`pactl`/`amixer`, `shell=False`), reportando `UNAVAILABLE` si no hay backend sin fabricar éxitos sintéticos.
    - `MusicTool` y `LocalMusicService` (`src/ailen/tools/builtin/music.py`): máquina de estados de reproducción local controlada.
    - `NotesTool` (`src/ailen/tools/builtin/notes.py`) y migración SQLite 0003 (`src/ailen/infrastructure/sqlite/migrations/0003_notes.sql`): persistencia de notas con consultas SQL parametrizadas.
    - `SystemStatusTool` (`src/ailen/tools/builtin/system_status.py`): diagnóstico sanitizado de CPU, RAM, GPU, audio y disco sin exponer secretos ni rutas de usuario privadas.
  - Frontera de búsqueda y extracción web segura:
    - `WebSearchTool` y `WebSearchProvider` (`src/ailen/tools/builtin/web_search.py`): desacoplado de proveedor, con fallback por defecto `UnconfiguredWebSearchProvider` (`status="UNCONFIGURED"`), tiers de costo (`FREE`, `PAID`, `UNKNOWN`) y salida estructurada.
    - `WebFetchTool` y `WebFetchPolicy` (`src/ailen/tools/builtin/web_fetch.py`): HTTPS por defecto, límite de payload de 256 KiB, allowlist estricta de Content-Type, inspección paso a paso de redirecciones y defensas robustas contra SSRF (bloqueo de loopback, RFC1918, link-local y endpoints de metadata cloud).
  - Integración en `ConversationCoordinator` (`src/ailen/core/conversation.py`) y `LabRunner` (`src/ailen/runtime/runner.py`): las herramientas locales simples responden directamente (`RULE_ONLY_TOOL`) sin llamar al LLM; las búsquedas web con resultados inyectan snippets sanitizados al contexto del LLM para síntesis y emisión por voz TTS.
  - Documentos de investigación y arquitectura: `docs/research/CONTROLLED_TOOLS_ARCHITECTURE.md` y `docs/research/WEB_SEARCH_BOUNDARY.md`.
  - Suite de 430 tests pasando, Ruff limpio, mypy limpio sobre 126 archivos fuente, git diff-check limpio y construcción de wheel exitosa.
- **R3B.4 Adaptive Runtime + Voice Latency**:
  - Abstracción e implementación de `InferenceProfile` (`RULE_ONLY`, `FAST`, `BALANCED`, `QUALITY`) desacoplada de `DeviceProfile` para categorizar la capacidad local del nodo.
  - Selector determinista `recommend_inference_profile` (`src/ailen/models/inference_profile.py`) con soporte de primera clase para CPU-only (2 GB, 4 GB, 8 GB, 16+ GB) y escalonamiento de VRAM para GPUs modestas y potentes.
  - Política estricta de estabilidad de modelo y anti-hopping `ModelResidencyPolicy` (`src/ailen/ai/residency.py`) prohibiendo cambios dinámicos de modelo por consulta para evitar cold-starts y degradación de memoria.
  - Residencia Ollama derivada del perfil (`QUALITY=30m`, `BALANCED=15m`, `FAST=5m`, `RULE_ONLY=0`) y `think=false` exclusivamente en `OllamaNativeBackend`; el backend OpenAI-compatible genérico permanece libre de campos específicos de proveedor.
  - Arnés de benchmark de inferencia local reproducible `ModelBenchmarkRunner` (`src/ailen/runtime/model_benchmark.py`) y comando `ailen lab benchmark-ai` evaluando modelos ya instalados en Ollama y reportando candidatos ausentes como `NOT_INSTALLED` sin descargas automáticas.
  - Incorporación de candidatos en `ModelCatalog` (`llama-3.2-3b-instruct`, `qwen3.5-4b-instruct`, `gemma-3-4b-instruct`, `qwen2.5-3b-instruct`, `qwen3.5-9b-instruct`) con `downloadable=False`.
  - Normalización de texto para voz `normalize_text_for_speech` (`src/ailen/audio/speech_text.py`) limpiando encabezados Markdown, bloques de código, URLs, emojis y viñetas sin alterar el texto original de la respuesta de IA.
  - Perfiles de VAD configurables (`conservative` 700ms, `normal` 500ms, `fast` 350ms) en `UtteranceCollector` (`src/ailen/audio/vad.py`).
  - Evaluador heurístico de calidad STT `SttQualityEvaluator` (`src/ailen/audio/stt_quality.py`) y política de reprompt ante transcripciones vacías o ruido sin fabricar niveles de confianza sintéticos.
  - Métrica TTFAR conectada de `VOICE_ENDED` al primer PCM enviado a playback; `SPEECH_STARTED` ya no se emite antes de sintetizar audio.
  - Clasificador conservador `classify_fast_path_intent` preparado para R3C; reconoce comandos inequívocos sin ejecutar tools todavía y evita falsos positivos como “volumen de un cilindro” o preguntas técnicas de batería.
  - `RecommendedDeployment` reutiliza la recomendación canónica de hardware, no inventa un modelo antes de `ModelPlanner` y mantiene costos externos como desconocidos hasta configurar proveedor/precio.
  - Documentos de investigación y benchmark: `docs/research/ADAPTIVE_INFERENCE_2026.md` y `docs/benchmarks/LOCAL_MODEL_COMPARISON.md`.
  - Piper usa la API Python `AudioChunk` cuando está disponible, mantiene la voz cargada, reproduce por chunks y conserva el CLI como fallback; Lab precalienta Piper antes de abrir el micrófono.
  - El backend genérico nunca expone `reasoning_content` como respuesta y no admite payloads específicos de proveedor implícitos.
  - Cierre auditado: 387 tests pasando, Ruff limpio, mypy limpio sobre 114 archivos fuente, diff-check y wheel reproducible en verde.
- **Vision physical validation follow-up (2026-08-23)**:
  - Webcam reciclada USB validada en `/dev/video1`; presencia/gaze físicos pasan.
  - `[vision]` limitado a `opencv-python-headless<5` mientras el backend use Haar Cascade.
  - Preflight valida `CascadeClassifier` + cascade asset; `demo vision` falla correctamente si backend no abre.
  - Auto-selección de cámara física cuando la ruta configurada no existe; histéresis de presencia y eventos de transición corregidos.
  - Suite actual: 432 tests, Ruff/mypy/diff-check verdes.
- **R3B.3 First Physical Lab Validation & Speech Asset Subsystem**:
  - Implementación del catálogo declarativo e inmutable de modelos de voz `SpeechAssetCatalog` (`src/ailen/speech/catalog.py`) con modelos verificados criptográficamente para 2026: Vosk Spanish (`vosk-model-small-es-0.42`), Whisper.cpp (`whisper-ggml-tiny`, `whisper-ggml-base`), y voces Piper en español (`es_ES-davefx-medium`, `es_AR-daniela-high`, `es_ES-sharvard-medium`, `es_ES-carlfm-x_low`) junto con sus configuraciones `.json`.
  - Política estricta de metadata: el género de las voces se declara explícitamente desde la metadata oficial de los datasets y nunca se infiere a partir de nombres de personas.
  - Almacén de modelos de voz seguro `SpeechAssetStore` (`src/ailen/speech/store.py`) en `~/.local/share/ailen/speech/{stt,tts}/` con validación exhaustiva `path.is_relative_to` contra vulnerabilidades de path traversal.
  - Descargador seguro `SpeechAssetDownloader` (`src/ailen/speech/downloader.py`) con streaming HTTPS, preflight de espacio en disco, comprobación SHA-256 fail-closed y extracción de ZIPs con protección estricta contra Zip-Slip.
  - Asistente interactivo `ailen lab prepare-speech [--yes]` (`src/ailen/speech/prepare.py`) para inspeccionar, descargar y validar modelos Vosk y voces Piper.
  - Generador de configuración aislada `ailen lab config init` (`src/ailen/runtime/lab_config.py`) para emitir `runtime/lab/ailen-lab.toml` sin modificar la configuración canónica `config/ailen.toml`.
  - Verificador exhaustivo de preparación física `LabPreflightChecker` (`src/ailen/runtime/preflight.py`) con categorización de requerimientos obligatorios vs opcionales (`ailen lab preflight`), evaluando Face GUI, bibliotecas de visión, cámaras V4L2 físicas, audio ALSA, binarios STT/TTS y estado del runtime local de IA.
  - Comandos CLI de gestión de voz y diagnóstico físico: `ailen speech list`, `ailen speech plan`, `ailen speech fetch`, `ailen speech verify`, `ailen lab audio-devices`, `ailen lab cameras`.
  - Protección de privacidad en logs de consola de `LabRunner`: transcripciones y respuestas se resumen con longitud y métricas sin exponer texto privado completo de forma espontánea.
  - Documentos de investigación y prueba: `docs/research/SPEECH_ASSET_CATALOG_2026.md`, `docs/testing/FIRST_PHYSICAL_LAB_REPORT.md` (reportando estado `NOT_READY_FOR_LIVE_TEST` / `PARTIAL` en host Asrock) y actualización de `docs/testing/MINT_LIVE_LAB_CHECKLIST.md`.
  - Suite de 344 tests unitarios e integración pasando en 20.89s, ruff y mypy limpios sobre 107 archivos fuente.
  - Auditoría final R3B.3: Vosk verifica fail-closed contra el ZIP SHA-256 autoritativo; el downloader valida tamaño exacto, redirects HTTPS y extracción ZIP transaccional con límites.
  - `lab audio-devices` separa hardware físico (`arecord/aplay -l`) de plugins/routing ALSA; el preflight ya no cuenta `null`, `pulse`, `pipewire`, etc. como micrófonos físicos.
  - `demo vad` y `demo stt` fallan ante micrófono real no disponible; el audio sintético sólo se activa con `--simulate`.
  - Metadata de género Piper corregida a `unknown` cuando el model card no la declara de forma inequívoca; AILEN no la infiere por nombres.
  - La configuración LAB mantiene `AILEN` separado del personaje (`display_name = "Asistente"`) y Piper se resuelve también dentro del virtualenv activo.
- **R3B.2 Live Lab Integration**:
  - Regla estricta "No Silent Fakes": `Fake*` sólo se permiten cuando se pasa explícitamente `--simulate`. Si falta un backend o modelo real, el estado reportado es `MISSING_MODEL`, `UNAVAILABLE` o `DISABLED`.
  - Factoría desacoplada `LabComponentFactory` (`src/ailen/runtime/factory.py`) para resolver componentes físicos de Face, Vision, Audio ALSA, STT (Vosk/Whisper), TTS (Piper) y AI Backends (Ollama/llama.cpp).
  - Cableado interactivo completo de extremo a extremo en `LabRunner` (`src/ailen/runtime/runner.py`) con `EventBus` (`TRANSCRIPT_READY`), `AudioInteractionCoordinator`, `ConversationCoordinator`, `StateManager` y `SocialEngine`.
  - Serialización de interacciones de vuelo único (`_interaction_lock`) para evitar colisiones y superposición de turnos conversacionales o inferencias concurrentes.
  - Soporte de inventario de modelos en tiempo de ejecución `RuntimeModelInventory` para endpoints Ollama `/api/tags` y OpenAI `/v1/models`.
  - Gestor de runtimes locales gestionados `ManagedLlamaRuntime` (`src/ailen/runtime/managed.py`) con loopback seguro `127.0.0.1` y control estricto de propiedad de procesos (`owned_by_ailen`).
  - Asistente de preparación `ailen lab prepare-ai` con soporte para selección de propósito (`ModelPurpose.SANITY`, `BALANCED`, `QUALITY`), verificación y arranque.
  - Telemetría estructurada en vivo `LabSessionMetrics` (`src/ailen/runtime/metrics.py`) y exportación a `runtime/lab/session_<timestamp>.json`.
  - `LabDoctor` con salida estructurada `--json` y diagnósticos no invasivos con remediaciones explícitas.
  - Auditoría ChatGPT R3B.2: el audio live sólo se cablea con I/O + STT + TTS reales; `--simulate` es el único camino Fake.
  - Resolución estricta del modelo de runtime: Ollama ya no selecciona arbitrariamente el primer modelo instalado ni hace fuzzy-match por familia; un alias debe ser explícito y exacto.
  - `LabRunner` puede iniciar/poseer un `llama-server` temporal sólo con GGUF instalado y SHA verificado; dry-run nunca inicia procesos y `prepare-ai --start-runtime` sólo realiza un smoke/health check y lo detiene.
  - Restore de políticas R3A en Live Lab: `SecretResolver`, BudgetPolicy, trust de LAN y restricciones cloud se propagan al `ConversationCoordinator`.
  - Métricas corregidas: latencia AI tomada del backend (sin TTS/playback), tokens desconocidos permanecen `None`, latencia TTS y transiciones de presencia se registran desde EventBus.
  - La voz configurada (`speech.tts_voice`) se propaga al TTS real y los estados Face/Core permanecen `PROCESSING` durante inferencia hasta volver a `ATTENTION/IDLE`.
  - Suite completa auditada de 324 tests unitarios offline pasando, ruff limpio, mypy en 100 archivos fuente y build de wheel exitoso.
- **R3B.1 Lab Stabilization**: HardwareCapabilityReport multiplataforma, adapters Linux/Windows defensivos, ModelCatalog/Planner/Store/Downloader, RuntimeManager, `ailen lab inspect/start/doctor/benchmark` y gestión segura de modelos locales.
- Auditoría final R3B.1: `src/ailen/models/` y `src/ailen/runtime/` quedan trackeables; planner accionable limitado a artefactos verificados; ModelStore de Lab usa ruta de usuario; downloader no sobrescribe artefactos existentes corruptos; estado `LAB READY` sólo se muestra cuando todos los componentes habilitados están listos.
- Verificación externa 2026-08-21 de Qwen 3.5 0.8B Q4_0/Q8_0 contra punteros oficiales de Hugging Face.

- **R3B Lab Mode, Hardware Capability Report V2, Model Catalog, Adaptive Model Planner, Secure Downloader y Runtime Manager (R3B.1 Lab Stabilization)**:
  - Detección de hardware multiplataforma limpia (`src/ailen/hardware/`) sin fabricar dispositivos sintéticos, con adaptadores `LinuxHardwareAdapter` (con conteo multi-socket de physical cores y DRM cards seguras con `backend=None`), `WindowsHardwareAdapter` (parsers CIM con `csv.reader` tolerando comas/quotes y reportando `None` para CPU flags y VRAM libre no medidos) y `FakeHardwareAdapter`.
  - Manejo defensivo ante mediciones de hardware ausentes: `HARDWARE_RAM_UNKNOWN` y `LOCAL_PLAN_BLOCKED_INSUFFICIENT_EVIDENCE` ante memoria no medida.
  - Catálogo declarativo e inmutable de modelos GGUF `ModelCatalog` (`src/ailen/models/catalog.py`) con modelos Qwen 3.5 0.8B (Q4_0 / Q8_0) verificados con Hugging Face Git LFS 2026 y modelos antiguos preservados como metadata con `downloadable=False`.
  - Planificador adaptativo `ModelPlanner` (`src/ailen/models/planner.py`) con validación de fracciones en `(0, 1]`, capping de `desired_context`, verificación de espacio en disco previo y respeto de requerimientos de CPU también en el camino de GPU offload.
  - Almacén de modelos `ModelStore` (`src/ailen/models/store.py`) con sanitización regex estricta y comprobación `path.is_relative_to(base_dir)` contra path traversal.
  - Descargador seguro `ModelDownloader` (`src/ailen/models/downloader.py`) con HTTPS obligatorio, rechazo de downgrade HTTP en redirecciones, límite estricto de tamaño antes y durante el streaming, verificación SHA-256 fail-closed y renombre atómico.
  - Gestor de runtimes desacoplados `LocalRuntimeManager` (`src/ailen/runtime/manager.py`) capaz de detectar `llama-server`, `llama serve` y `Ollama`, reportando `DEGRADED` ante respuestas HTTP 404.
  - `LabRunner` real (`src/ailen/runtime/runner.py`) para orquestación no invasiva de componentes en modo laboratorio (Face, Vision, Audio, STT, TTS, AI) con reporte de tabla inicial, soporte para `--headless`, `--no-camera`, `--no-audio`, `--no-ai`, `--duration` y cleanup ante Ctrl+C sin terminar runtimes externos.
  - `LabDoctor` no invasivo (`src/ailen/runtime/doctor.py`) con diagnóstico `PASS`/`WARN`/`FAIL`/`SKIP` (`ailen lab doctor`).
  - Comandos CLI nuevos: `ailen lab inspect [--json]`, `ailen lab start [--dry-run]`, `ailen lab doctor`, `ailen lab benchmark`, `ailen models list [--json]`, `ailen models plan [--json]`, `ailen models fetch <model_id> [-y]`, `ailen models verify <model_id>`.
  - Suite de 292 tests unitarios offline pasando, ruff limpio, mypy en 95 archivos fuente y build de wheel verificado.
- **R3A AI Router Híbrido, Políticas de Privacidad Outbound, Presupuesto Cloud y Proveedores Local/LAN/Cloud**:
  - Router determinista de IA `RuleBasedRouter` con soporte para todos los perfiles de hardware (`SATELLITE`, `CLOUD`, `HYBRID`, `LOCAL`, `LAN_BRAIN`), cadenas de fallback explícitas y códigos de razón canónicos (`RULE_ONLY_INTENT`, `CLOUD_FAST_PATH`, `CLOUD_BUDGET_EXCEEDED`, `PRIVATE_REMOTE_BLOCKED`, `ALL_BACKENDS_UNAVAILABLE`, etc.).
  - Política de privacidad outbound `OutboundPrivacyPolicy` fail-closed: `RESTRICTED`/`PRIVATE` nunca se rebajan silenciosamente a `PUBLIC`; Cloud y LAN no confiable quedan bloqueados fuera del LLM.
  - `SecretResolver` para API keys desde variables de entorno o archivos owner-only; en POSIX rechaza archivos accesibles por grupo/mundo y Cloud falla cerrado sin credencial/configuración suficiente.
  - `BudgetPolicy` circuit breaker: `0 USD` significa no gastar, `None` significa sin límite interno y precios cloud desconocidos no se interpretan como cero; los precios vigentes deben configurarse explícitamente.
  - Constructor de contexto `AiContextBuilder` que produce prompts mínimos acotados en caracteres y tokens, integrando memorias y datos de negocio filtrados por `SocialPrivacyPolicy` y `OutboundPrivacyPolicy` (`src/ailen/ai/context.py`).
  - Cliente HTTP genérico OpenAI-compatible `GenericOpenAiBackend` construido exclusivamente con la librería estándar de Python (`urllib.request`), con timeouts estrictos, manejo de errores de red y parseo resiliente de respuestas y tool calls (`src/ailen/ai/http_backend.py`).
  - Implementación histórica R3A de `LocalAiBackend`, `LanBrainAiBackend` y `CloudAiBackend`; R4 retiró el backend Cloud monolítico y lo sustituyó por remotos nombrados.
  - Orquestador de inferencia `AiOrchestrator` que ejecuta la secuencia de backends primario y fallbacks, registra telemetría de tokens/costo en SQLite y publica eventos en `EventBus` (`src/ailen/ai/orchestrator.py`).
  - Coordinador conversacional end-to-end `ConversationCoordinator` conectando `Transcript` STT -> `AiContextBuilder` -> `RuleBasedRouter` -> `AiOrchestrator` -> `AudioInteractionCoordinator.speak()` (`src/ailen/core/conversation.py`).
  - Configuración histórica `[ai.cloud]`; R4 la migra de forma fail-closed a `[ai.remote.providers.<id>]` y el esquema activo ya no la expone.
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

- Lab físico de voz: PipeWire como routing compartido en Mint, Piper resuelto desde virtualenv, migraciones SQLite antes de memoria, gate durante PROCESSING/TTS, backend Ollama nativo `/api/chat` con thinking desactivado y keep-alive, normalización de texto para TTS y timeout de playback proporcional a la duración.
- Validación física end-to-end con auricular/micrófono USB G600: Vosk -> qwen3.5:9b -> Piper -> reproducción real.
- Flujo de wake del `InteractionCoordinator`: presencia durante `SLEEP` ahora produce `WAKE` antes de permitir un saludo posterior, en lugar de perder el estado de sueño al transicionar.
- Login administrativo ahora verifica realmente **usuario + contraseña**; el usuario persistido dejó de ser un dato decorativo.
- SQLite restringe el archivo de datos a modo `0600` en POSIX porque contiene memoria privada y material derivado de credenciales.
- `SettingsService.update()` usa semántica de patch parcial; la traducción de checkboxes HTML ausentes a `false` pertenece a la capa Web.
- Una ruta explícita de configuración o `AILEN_CONFIG` inexistente falla de forma visible en lugar de caer silenciosamente a defaults.
- Cookie de sesión sin `Max-Age` duplicado/hardcodeado; el TTL autoritativo queda en `AuthService`.

### Decisions

- ADR-010 acepta inferencia adaptativa por hardware, modelo estable por sesión y tools/Web controlados por Core; la RTX 3060 queda explícitamente como hardware de laboratorio, no requisito del producto.
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
