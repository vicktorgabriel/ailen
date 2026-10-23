## Agente de Core y voz en vivo — 2026-10-23

- Visión de producto reafirmada: asistente tipo Alexa para equipos modestos, con
  LLM local cuantizado/híbrido según hardware y, si el equipo no lo sostiene,
  proveedor externo con voz en vivo. Debe poder ejecutar herramientas locales y de
  red, navegar y modificar archivos locales siguiendo instrucciones.
- ADR-014 (Accepted): el agente corre en Core con niveles N1 tools, N2 archivos
  en raíces autorizadas, N3 navegador aislado; N4 shell/computer-use general queda
  fuera. Acciones destructivas o con efecto externo piden confirmación humana.
- ADR-015 (Accepted): ruta opcional `remote_realtime:<id>` por WebSocket; Core
  conserva identidad, memoria y tools (function-calling hacia `ToolExecutor`).
- AGY (Gemini) y OpenCode (DeepSeek free) se usan como agentes auxiliares de
  desarrollo, obligatoriamente para delegar auditorías, revisión y tareas acotadas
  y ahorrar tokens del agente principal. No son proveedores runtime.
- Auditoría delegada 2026-10-23 (AGY + OpenCode): 2 hallazgos reales corregidos
  (query en log de BrokenPipe; `execution_mode` con todos los backends apagados).
  Pendientes de baja prioridad: allowlist explícita en export de memoria, ruta
  absoluta de `reports_dir`, `LabDoctor` con timeout/worker, mensajes fijos en
  ValueError, redirect conservando alcance y tests HTTP de 409/503 en
  `/diagnostico/run`. Descartado: "Todos (142)" es aserción negativa válida.
- R5 cierre de vistas (2026-10-23): cada vista tiene `web/<x>_view.py` con
  `<x>_context(cfg)`; `app.py` solo cablea y aplica `_flash`. Sin SettingsService se
  usan los defaults de Core. Estado en vivo de tools/visión/personalidad evolucionada
  requiere servicios inyectados desde el runtime (siguiente trabajo).
- Regla de proceso: todo cambio, decisión y delegación se documenta en el mismo
  lote de trabajo (ver AGENTS.md y REGLAMENTO.md).

### R4 — remotos nombrados, provisioning por hardware y captura medible (2026-09-01)

## R5: administración real y procedencia del diagnóstico — 2026-10-02

- Memoria Web administra recuerdos explícitos mediante servicio/repositorio;
  sólo públicos por defecto. El admin debe seleccionar acceso privado y
  confirmar cambios/exportaciones. No se incorpora purga masiva ni se mezclan
  notas, recordatorios o conversaciones en la exportación.
- Diagnóstico distingue health de `serve`, comprobaciones LabDoctor a pedido
  y mediciones de sesión Lab finalizada. No inferir health de otro proceso ni
  convertir reportes simulados/legacy en mediciones reales.
- Se amplía ADR-005 y MODULE_CONTRACTS sin cambiar esquema SQLite ni agregar
  dependencias runtime. Siguiente trabajo: resto de vistas R5 con datos reales;
  pruebas físicas y Appliance permanecen abiertos.


- **Runtime local calificado, no inferido**: `HardwareQualificationStore`
  conserva evidencia independiente por `(hardware_class, model_id, runtime)`.
  `ProvisioningPlanner` ya no sustituye el runtime medido por el preferido de la
  recomendación. CPU/CUDA y `gpu_layers` salen de esa misma evidencia; offload
  parcial queda bloqueado hasta implementarlo y medirlo.
- **Retiro de agentes CLI**: AGY/Antigravity y OpenCode dejan de ser proveedores
  runtime. Las configuraciones antiguas migran a `auto` con warning y nunca
  construyen esos clientes. La evidencia histórica de ~6,7 s TTFT e
  invalid/429 se conserva como razón `RETIRED/REJECTED`.
- **Provider Manager**: remotos independientes `remote:<id>` con secretos,
  prioridades, health, presupuesto, catálogo y cooldown propios. Se implementan
  OpenAI Responses SSE (`store=false`), Chat Completions SSE y Anthropic
  Messages SSE; ningún adapter anuncia tools/reasoning no implementados.
- **Presets no son soporte**: OpenAI, Anthropic, DeepSeek, Kimi y MiniMax sólo
  aportan protocolo/endpoint/secret slot. Modelo, salud, TTFT, costo y
  `voice_realtime_eligible` requieren catálogo/selección y prueba consentida;
  no se hicieron requests pagas en esta pasada.
- **Región y catálogo fail-closed**: Kimi global usa `api.moonshot.ai/v1` y
  MiniMax internacional `api.minimax.io/v1`; ninguna variante china se activa
  por defecto. Sólo OpenAI declara catálogo `live` probado contra `/v1/models`;
  los demás presets quedan `manual` hasta implementar y verificar su consulta
  oficial específica.
- **Provisioning automático**: el modelo no pertenece al perfil Lab. El reporte
  real de hardware más evidencia calificada por clase produce un plan declarativo
  con runtime, contexto, offload, reservas, hash/licencia y consentimiento. Un
  candidato nunca se instala en silencio y ASRock no califica 4/8 GB. Desde
  16 GB no existe un techo fijo de 6 GB: 16/32/64+ reservan margen proporcional
  y el mejor artefacto calificado que entra puede escalar con RAM/VRAM real.
  El runtime elegido queda vinculado a su evidencia y no se sustituye por otro
  runtime saludable durante el arranque.
- **Activación estable y consentida**: `ProvisioningPlan` no queda como informe
  descartable. Tras verificar el artefacto exacto, `prepare-ai
  --activate-selection` puede escribir un manifiesto atómico `0600` ligado a
  hardware/modelo/runtime/contexto/offload/hash. El runner lo consume sólo con
  local habilitado y sin override, y falla cerrado ante drift o corrupción; no
  replanifica ni cambia de modelo por turno.
- **Captura honesta**: `audio.input_volume` decorativo se retira. La cadena es
  source -> NS opcional -> gain dB -> AGC bounded con gate/hold/release -> limiter ->
  VAD/STT; preserva S16LE. `pipewire:<node>` usa target explícito y `pipewire`
  usa el default nativo sin depender de `pactl`. El calibrador mide
  silencio/voz/SNR/clipping/WER en RAM, propone el gate desde silencio y no
  guarda PCM ni cambia config sin confirmación.
- **Observabilidad de audio causal**: `mic_raw` se mide antes de DSP, cada etapa
  se mide después y `mic_clean` representa sólo la salida final. Un drenaje TTS
  cancelado publica su evento antes de quedar en cero y antes de que el siguiente
  turno entre al backend no concurrente.
- **ASRock observado**: `default` resolvió a USB Composite/Jieli, no G600;
  Easy Effects Source estaba a 42%/-22,87 dB. Son hechos de inventario, no una
  recomendación de fuente. AGC/NS no equivalen a AEC.
- **Comparación guiada, no controles globales**: sin `--device`, el harness
  selecciona default/fuentes PipeWire físicas/Easy Effects de forma bounded y
  deduplicada; un override usa sólo el target pedido. Persiste escalares por
  etapa y el snapshot de rutas, nunca PCM. Web no toca `amixer Master`, no
  promete AEC ni muestra una latencia Piper fija sin medición.
- **Distancia y perfiles comparables**: la matriz física usa 30/75/100 cm,
  silencio previo y perfiles `raw`, `noise_only` y `full`. Easy Effects es una
  referencia de laboratorio `external_reference`, nunca requisito ni doble DSP.
- **Campaña USB inconclusa**: `voice-20260901T084132Z-1cfb53` sólo reunió cinco
  muestras a 75 cm. Jieli dio WER 1,0 raw y 0,5 procesado, con falsos triggers en
  varias configuraciones; Easy Effects dio WER 0,5 en una única muestra. No se
  promueve fuente, gain, AGC, VAD ni perfil a configuración activa.
- **Micrófono de las unidades recicladas**: se prioriza el dispositivo
  integrado/nativo de la placa. Debe calificarse por endpoint y unidad; no se
  presupone bueno por ser interno. USB/G600/Easy Effects quedan opcionales para
  diagnóstico o comparación y nunca se instalan como requisito.

### R6 — Vertical 1 de updates firmados y recuperables (2026-08-31)

- **Trust antes de acción**: bytes exactos del manifiesto JSON se verifican con
  firma Ed25519/OpenSSL antes del parseo. Tamaño, SHA-256, plataforma, media type
  y expansión de cada artefacto pertenecen al contenido firmado.
- **Lifecycle recuperable**: downloader bounded/cancelable/reanudable, CAS
  inmutable, journal atómico, aprobación efímera y un worker. Una interrupción
  sólo se reanuda tras fetch, firma y aprobación nuevos con ETag/Range compatible.
- **Activación**: extracción tar fail-closed, preparación atómica, switch,
  probation y rollback se ejecutan detrás de contratos inyectados. SQLite no se
  restaura ni baja de schema automáticamente; la compatibilidad rollback se
  valida antes de mutar servicio.
- **Frontera actual**: sólo `LAB_SIMULATION`, raíces inyectadas y controller
  in-memory. El modo Appliance queda `UNAVAILABLE` hasta implementar
  `ailen-updaterd`; no se invoca systemd ni se escriben `/opt`/`/var/lib` reales.
- **Administración**: `/actualizaciones` y sus APIs usan auth, CSRF, allowlist
  exacta y DTOs redacted. Web no ejecuta downloader/tar/shell ni controla paths.
- **Evidencia**: aceptación firmada sin Internet demuestra éxito, rollback de
  candidato unhealthy y resume tras interrupción. Pipeline de firma productivo,
  bundle offline, power-loss y appliance físico siguen pendientes (ADR-013).
- **Gate integrado**: 1019 tests, Ruff, mypy en 157 archivos fuente y diff-check
  limpios. Wheel de 195 entradas/3.069.600 bytes incluye updater/Web y excluye
  modelos, multimedia, FacePack, binarios nativos, keys y artefactos Lab.

### R5B — calidad authored sobre composición H3 incompatible, FacePack 1.6 (2026-08-31)

- **Evidencia física**: las secuencias H3 completas eran limpias, pero componer
  ojos/cejas o boca de un clip sobre otra emoción producía doble contorno y
  deformación de identidad. Más tracking/feather eliminó bordes, no la causa.
- **Decisión de pack**: el desktop pack 0.7.0 usa full-frame para sus 28
  microacciones y 10 speech sources. Speech conserva categoría/selección propia,
  sustituye temporalmente sólo la imagen y al cesar retoma el affect de Core; no
  se transforma en emoción ni risa.
- **Capacidad futura**: FacePack 1.6/engine ABI 1.4 todavía acepta mouth/upper ROI
  para assets realmente preparados como capas. No se declara composabilidad falsa
  para los videos H3 existentes.
- **Prueba física**: `blink_double` quedó limpio; los diez `talk_*` mejoraron
  labios/dientes y el seam casi no se percibe a velocidad real.
- **Costo ASRock**: pack 90.247.218 bytes/2.888 frames; RSS incremental 3,79 MiB,
  speech 0,920 ms avg/1,485 ms p95 y 2,560% de un core. Runtime sigue sin MP4.

### R5B — movimiento authored, tracking de capas y retornos FacePack 1.4 (2026-08-31)

- **Causa visual confirmada**: normalizar cada frame full-frame inmovilizaba la
  cara mientras el cuerpo H3 seguía moviéndose; el borde reflectado duplicaba la
  figura en los laterales. Full-frame ahora usa un transform fijo del frame de
  entrada y fondo oscuro constante, preservando el movimiento authored.
- **Tracking real**: el formato 1.4 codifica por frame la transformación
  canonical->cara actual. El engine aplica ojos/cejas/boca con traslación,
  rotación y escala sobre la cabeza real. La boca usa ROI de reemplazo alineada;
  el delta de luminancia anterior deformaba dientes y labios.
- **Retorno sin doble rostro**: los clips que terminaban en pose recorren frames
  curados reales en reversa. Payloads JPEG idénticos comparten offset, por lo que
  2.867 frames lógicos ocupan 64.852.548 bytes. No hay crossfade ni frames H3
  regenerados.
- **Presentación**: ABI 1.4 agrega copia bilinear segura. A 720/1080 reduce bloques,
  pero una fuente 480×480 no puede adquirir detalle nuevo. `copy_frame` es la
  ruta concurrente canónica; el getter raw sólo conserva compatibilidad mediante
  snapshot thread-local y destroy exige quiescencia del caller.
- **Evidencia**: pack determinista SHA-256
  `657abff40e76b37fb83ee0813683c48b99dfd592eec21096d93f4cc2df98ba29`;
  765 tests verdes. El usuario confirmó el movimiento full-frame corregido;
  falta observar físicamente el regreso y la boca tracked del showcase final.

### R5B — expansión completa y composición delta FacePack 1.2 (2026-08-30)

- **Corpus útil**: el pack desktop pasa de 23 a 79 secuencias y 2.522 frames,
  con 39 emociones listables, 28 microacciones, 10 speech y 6 estados. Usa 76
  fuentes; 2/27 quedan fuera por redundancia, 28/64/82 por review inseguro y
  39/83–85 por descarte. La segunda revisión promovió 76 a `crying` utilizable.
- **Capas reales**: ojos/cejas/gaze y boca se compilan como deltas ROI centrados,
  normalizados offline por ojos/nariz. Speech usa luminancia/dead-zone para no
  transferir piel, mandíbula o color de otro clip. La composición runtime es
  base/emoción + upper-face delta + mouth delta, sin crossfade ni MP4.
- **Metadata ejecutada**: anchors/transition, prioridad, `gaze_compatible`,
  estilos de speech y retorno visual compatible tienen efecto real. Core sigue
  siendo autoridad de `AssistantState`; `return_state` no lo modifica.
- **ABI/default**: formato/ABI 1.2, exports `noexcept`, errores traducidos, mutex
  por handle y strings thread-local. `facepack` es default. Fallo => headless;
  `portrait` y `pixel` sólo se eligen manualmente.
- **Evidencia**: pack determinista SHA-256
  `04eecd4d72f3c8bef4c2a3d37d2df788156cf904ceef1bd0c80edec3164382c7`;
  84.775.628 bytes. ASRock contendido: 0,691% de un core idle, 2,303% por capas,
  0,745 ms update+copy promedio/1,237 ms p95. Suite completa: 742 tests; Ruff,
  mypy 145+6, C++ warnings-as-errors, diff-check y wheel limpios. Validación
  conversacional física y DLL Windows siguen abiertas.

### R5B — auditoría post-Codex de FacePack (2026-08-30)

- **Failover en caliente**: el controller de FacePack queda detrás de un wrapper estable que conserva la misma referencia para Core/Audio/Vision/Tools y desactiva el display facial ante fallos nativos fatales durante la sesión. Errores semánticos no fatales (`NOT_FOUND`, `BUSY`) no disparan fallback ni ocultan bugs.
- **Timing natural**: `duration_seconds=0` significa timing propio del renderer. FacePack ya no estira automáticamente expresiones cortas a 5 o 7.5 segundos; el renderer portrait conserva su duración histórica cuando recibe 0.
- **Metadata v1**: `return_state`, transiciones, prioridad y `gaze_compatible` permanecen metadata validada/advisory en este slice; Core sigue siendo autoridad del estado persistente. No se declara funcionalidad que el engine aún no ejecuta.
- **Alcance en ese corte**: la auditoría visual cubría 85 fuentes y el pack era un vertical slice de 23 secuencias/603 frames/11 emociones. La sección superior registra la expansión posterior.
- **Gate de ese corte**: 730 tests, Ruff, mypy (145 + 6 módulos), C++17 warnings clean, diff-check y wheel 0.4.0.dev0 sin multimedia/binarios nativos embebidos.

### Consolidación 0.4.0-dev.0 y slice FacePack nativo (2026-08-30)

- **Versión de desarrollo**: el estado del proyecto pasa de `0.1.0-dev.0` a `0.4.0-dev.0` para reflejar R1-R3C integrados y el trabajo actual en R4/R5. No implica release/tag: primero se requiere auditoría del working tree, suite completa y wheel limpio.
- **H3 es corpus, no runtime**: los 85 MP4 se inspeccionaron visualmente y se conservan sin cambios como materia prima fuera del wheel. La clasificación completa vive en `h3_classification.json`; el engine nunca reproduce MP4.
- **Engine separado del contenido**: ADR-012 adopta C++17 con C ABI (`libailen_face_engine.so` / `ailen_face_engine.dll`) y `.facepack` binario externo. Magic, ABI, offsets, límites y CRC fallan limpio. Agregar una emoción recompila sólo el pack; Pack A -> Pack B fue probado con la misma `.so`.
- **Allowlist dinámica, autoridad en Core**: el controller filtra ids canónicos del pack y los entrega al schema de `FaceExpressionTool` y a la metadata afectiva. El LLM sólo elige dentro de esa lista; nunca controla assets/frames, y una emoción nueva no exige mantener una lista paralela del renderer.
- **Estados y speech son capas distintas**: estados persistentes usan base + espera variable + microacción + retorno, no loops de clips. Speech usa una mouth ROI alineada offline y no reemplaza la emoción activa; `SPEAKING` conserva `happy`/la expresión vigente.
- **Representación v1**: JPEG Q90 por frame fue 4.8x menor que el delta lossless muestreado, ofrece acceso aleatorio y requiere sólo libjpeg en runtime. FFmpeg/OpenCV/YuNet quedan restringidos al compilador offline.
- **Fallbacks y promoción**: falta DLL Windows y hardware LOW. `facepack` es el default lógico; fallo deshabilita el display. `portrait` queda renderer legacy manual y `pixel` opción explícita para hardware/display excepcionalmente limitado.
- **Health/preflight separado**: tener Tkinter no prueba que el engine esté disponible. El preflight carga ABI + pack y sólo entonces marca `Native FacePack` como `PASS`; fallas recuperables quedan en `WARN` y el display facial se deshabilita hasta reparar engine/pack.
- **Benchmark ASRock**: pack 27.06 MB, RSS incremental 3.50 MiB, pack load 55.43 ms, update animado 0.59 ms avg / 1.25 ms p95. Engine 0.65%/1.84% de un core idle/animado; Tk real 2.30%/13.62% con speech a 30 FPS. No extrapolar.
- **Cierre verificable**: 727 tests en verde, Ruff limpio, mypy limpio en 144 módulos AILEN + 6 de tools/facepack, diff-check limpio y wheel inspeccionado sin MP4, FacePack ni librerías nativas.

### R4 — External Provider Runtime Manager & Autoservicio `/ia` (2026-08-29, histórico; sustituido el 2026-09-01)

- **Abstracción `ExternalProviderRuntime` y `ExternalRuntimeManager`**: Desacopla la administración del ciclo de vida del cliente instalado (`detect()`, `version()`, `auth_status()`, `diagnostic()`, `list_models()`, `install()`, `update()`, `begin_login()`) de la generación de inferencia conversacional (`AiProvider`).
- **Auditoría física y runtime Google Antigravity (`agy` v1.1.22)**: Detección automática en `~/.local/bin/agy`, parseo de versión, verificación de autenticación contra `agy models`, acciones de inicio/renovación de sesión y actualización del cliente con timeouts estrictos y comandos en allowlist sin shell libre.
- **Autoservicio completo desde `/ia`**: Endpoints protegidos por CSRF (`/api/ai/runtime/status`, `/api/ai/runtime/login`, `/api/ai/runtime/update`, `/api/ai/runtime/install`, `/api/ai/models`, `/api/ai/test-provider`) que permiten auditar, renovar sesión y actualizar clientes directamente desde el panel web con mensajes de error limpios y comprensibles (sin tracebacks ni errnos crudos).
- **Manejo de Rate Limits (HTTP 429)**: `GenericOpenAiBackend` y `OpenCodeProvider` mapean 429 a `finish_reason="rate_limited"` y estado `RATE_LIMITED` / `DEGRADED`, permitiendo al router degradar limpiamente en cascada sin colapsar AILÉN.
- **Validación física end-to-end**: Confirmada ejecución en equipo host: `agy v1.1.22`, `gemini-3.7-flash-low`, latencia medida (~5.4-5.6s), turno conversacional completo con aislamiento estricto de memorias privadas (`PRIVATE Core` -> `SANITIZED_REMOTE` -> `Antigravity` -> `respuesta`).
- **Suite de pruebas extendida**: 697 tests pasando en verde; Ruff y mypy (142 archivos) limpios.

### R4 — Proveedores Externos Configurables, Almacén Seguro 0600 y Panel Web Admin de IA (2026-08-28, histórico; sustituido el 2026-09-01)

- **Abstracción `AiProvider` desacoplada del LLM**: Estandariza metadatos, capacidades, health, y `test_connection()`. Google Antigravity (`agy`), OpenCode Zen y endpoints OpenAI-compatible son ciudadanos de primera clase junto a Ollama local.
- **Google Antigravity en modo headless sandbox**: `AntigravityProvider` invoca `agy` con `--disable-slash-commands --sandbox` como modelo conversacional puro sin permisos de ejecución ni manipulación de archivos.
- **Almacén seguro con permisos 0600**: `SecretResolver` persiste claves en `data/secrets/` con permisos `0600` (POSIX) mediante escritura atómica temporal y directorio `0700`. Archivos con permisos de grupo/mundo son rechazados. Ninguna clave entra a `ailen.toml` ni SQLite.
- **Modo remoto en Tier 4 GB sin runtime local activo**: `ai.local.enabled = false`
  es estado de primer nivel. Preflight y Lab Runner reconocen `AI Inference:
  READY via <proveedor>` sin tocar Ollama. Esta decisión conserva un modo de
  instalación válido; no elimina el requisito posterior de ofrecer un perfil
  autónomo local medido para el producto 4/8 GB.
- **Panel Web Admin de IA (`/ia`) y APIs AJAX**: Incluye tarjetas interactivas de proveedores, selector de prioridades de fallback, guardado de claves en almacén seguro (`POST /api/ai/set-secret`) y prueba de latencia (`POST /api/ai/test-provider`) protegidos por CSRF.
- **Suite de pruebas extendida**: 670 tests pasando en verde, ruff y mypy limpios (141 archivos).

### R3C — Product Behaviors, Controlled Tools & Safe Web Boundary


- **Timeout de herramientas no bloqueante**: `ToolExecutor` ejecuta cada tool en un worker pool sin context manager; ante timeout se devuelve control inmediatamente (`shutdown(wait=False, cancel_futures=True)`). Un tool colgado ya no congela la conversación hasta que su hilo muere.
- **Gates explícitos de red y destructividad en tools**: tools con `requires_network=true` se deniegan con `NETWORK_UNAVAILABLE` cuando no hay conectividad (`ToolContext.internet_available`, cableado desde ConversationCoordinator). Tools `destructive=true` requieren `confirm=true` explícito y están prohibidos en SHOP/PUBLIC. Hoy ningún tool builtin es destructivo; el gate queda cerrado por defecto.
- **PROCESSING -> ATTENTION válida; PROCESSING -> LISTENING prohibida**: tras cada conversación el runner vuelve a ATTENTION (rostro presente) o IDLE sin desincronizar StateManager y Face. La raza PROCESSING->LISTENING sigue bloqueada por la máquina de estados con regresión testada.
- **Notas por voz preservan casing original**: `IntentResolver` extrae el contenido del texto crudo (colapsando whitespace, quitando signos iniciales) en vez del texto lowercased; la query de web_search se extrae igual para evitar desalineación por "¿" o mayúscula inicial.
- **Búsqueda web explícita prevalece sobre negativos conceptuales**: "buscá en internet el volumen de un cilindro" es una orden inequívoca de búsqueda y va a `web_search`; los negativos ("volumen de un cilindro") siguen bloqueando fast-paths locales. Preferencia por falso negativo se mantiene salvo orden explícita del usuario.
- **Preflight YuNet fail-closed real**: con `detector=yunet` el preflight instancia `FaceDetectorYN.create()` (valida ONNX legible) y exige score threshold en (0,1]. PASS nunca proviene sólo de la existencia del archivo. Haar valida carga efectiva del cascade y permanece experimental.
- **Benchmark vision CPU-first (`ailen lab benchmark-vision`)**: mide latencia por frame del detector real sobre cámara física sin GUI ni persistencia de frames. El operador etiqueta la fase (`--phase empty|face|movement`); el sistema NO infiere falsos positivos sin ground truth. YuNet medido ~49 ms avg / p95 ~91 ms a 5 FPS en CPU (Ryzen 5 5500) — apto para hardware objetivo; RTX 3060 no es requisito.
- **Benchmark STT multi-motor (`ailen lab benchmark-stt`)**: mismo WAV -> múltiples motores; WER propio con normalización española (lowercase, puntuación básica, whitespace; acentos preservados); sin referencia no se inventa accuracy; motores ausentes = `NOT_INSTALLED`; jamás descarga modelos. Grabación por micrófono sólo con `--record N --out ruta` explícitos.
- **Limitación conocida SSRF**: la validación DNS de `WebFetchPolicy` ocurre antes de conectar; un atacante con DNS rebinding podría eludirla entre validación y conexión. Mitigación futura: transporte con IP fijada/pinning. Documentado como deuda en WEB_SEARCH_BOUNDARY.md.

- **El LLM nunca ejecuta acciones directamente**: Todo control del sistema operativo (audio, timer, hora, música, notas, status) se ejecuta mediante herramientas fuertemente tipadas y validadas por el Core (`ToolRegistry` y `ToolExecutor`).
- **Filtrado estricto de falsos positivos en IntentResolver**: Los falsos positivos son peores que los falsos negativos. Consultas conceptuales o explicativas (ej. "¿cuál es el volumen de un cilindro?", "¿qué batería usa esta notebook?", "explicame qué es un temporizador") son filtradas y dirigidas exclusivamente al flujo conversacional del LLM.
- **Acciones simples responden sin LLM (`RULE_ONLY_TOOL`)**: Para órdenes locales directas ("subí el volumen", "qué hora es", "poné un temporizador"), el sistema ejecuta la herramienta y devuelve la respuesta formateada directamente, ahorrando tiempo de inferencia y consumo de hardware.
- **Frontera de búsqueda web desacoplada de proveedor**: `WebSearchTool` utiliza la interfaz `WebSearchProvider`. Si no hay motor configurado, `UnconfiguredWebSearchProvider` devuelve `status="UNCONFIGURED"` de forma limpia sin intentar scraping frágil. Los resultados válidos se sanitizan antes de inyectarse al LLM para su síntesis.
- **Defensas Anti-SSRF obligatorias en `WebFetchTool`**: `WebFetchPolicy` valida esquema HTTPS, resuelve DNS y verifica que todas las direcciones IP de destino no pertenezcan a loopback, RFC1918, link-local o endpoints de metadata cloud (`169.254.169.254`, `metadata.google.internal`). Las redirecciones se inspeccionan una a una (máximo 3) y se impone un límite de payload de 256 KiB con allowlist de Content-Type (`text/html`, `application/json`, etc.).
- **Persistencia de notas en SQLite**: Las notas de usuario se almacenan en la tabla `notes` con consultas parametrizadas, protegiendo el sistema de inyecciones SQL.
- **Auditoría con redacción de secretos**: Todo evento de herramienta se registra en SQLite `tool_events` y en `EventBus` con redacción automática de contraseñas, tokens y claves de API.

### R3B.4 — Adaptive Runtime, Model Residency & Voice Latency

- **InferenceProfile desacoplado de DeviceProfile**: `DeviceProfile` define la topología (`SATELLITE`, `CLOUD`, `HYBRID`, `LOCAL`, `LAN_BRAIN`), mientras que `InferenceProfile` define la capacidad local recomendada (`RULE_ONLY`, `FAST`, `BALANCED`, `QUALITY`).
- **CPU-only es ciudadano de primera clase**: `recommend_inference_profile()`
  maneja determinísticamente 2 GB (RULE_ONLY/SATELLITE), 4 GB (FAST sólo si el
  envelope medido deja margen), 8 GB (FAST CPU) y 16/32/64+ GB con presupuesto
  dinámico, sin
  asumir GPU. El cambio posterior reemplaza el antiguo default RULE_ONLY de 4 GB;
  sigue exigiendo benchmark objetivo antes de declarar soporte.
- **Prohibición Estricta de Model Hopping**: Una sesión mantiene un modelo primario estable (`ModelResidencyPolicy`). Se prohíbe alternar modelos dinámicamente por consulta (ej. 3B -> 9B -> 3B) para prevenir cold-starts, latencias impredecibles y degradación de memoria. Cambios permitidos sólo en: `STARTUP`, `PROFILE_CHANGE`, `BACKEND_FAILOVER`, `ADMIN_OVERRIDE`, `NEW_SESSION`.
- **Residencia de Modelos Configurable**: El tiempo de `keep_alive` para Ollama se deriva del perfil (`30m` en QUALITY, `15m` en BALANCED, `5m` en FAST, `0` en RULE_ONLY) y es configurable.
- **Benchmark local veraz (`ailen lab benchmark-ai`)**: Ollama se mide por su API nativa con `think=false`; `FIRST` no se etiqueta como cold-start y TOK/s sólo se reporta si el runtime entrega duración/conteo de generación. Candidatos ausentes siguen `NOT_INSTALLED` sin descargas.
- **Normalización de Texto para Voz (`normalize_text_for_speech`)**: Proyecta texto limpio para Piper TTS eliminando sintaxis Markdown, code fences, URLs y emojis decorativos, sin alterar el texto original de la respuesta de IA.
- **TTFAR operacional**: mide desde `VOICE_ENDED` hasta el primer PCM que AILEN entrega al backend de playback. Es proxy de primer audio audible, no una medición física del DAC/auricular.
- **Perfiles VAD y Calidad STT Heurística**: Perfiles `conservative` (700ms), `normal` (500ms) y `fast` (350ms) en `UtteranceCollector`. Heurística `SttQualityEvaluator` para reprompt ante transcripciones vacías o ruido sin inventar falsos niveles de confianza.
- **Fast-Path conservador preparado para R3C**: sólo clasifica órdenes inequívocas; no ejecuta tools todavía. Frases ambiguas/técnicas se mantienen en chat para evitar acciones incorrectas.
- **Piper Python cacheado/chunked**: la API instalada sí expone `AudioChunk`; AILEN cachea la voz, precalienta al iniciar Lab y reproduce chunks por oración mediante esa única ruta canónica.
- **No razonamiento interno como respuesta**: `reasoning_content` nunca se promueve a texto visible/TTS en el backend genérico.
- **Preferencia de recursos conservadora**: la preferencia del usuario puede bajar el perfil, nunca superar lo permitido por hardware medido; ModelPlanner elige el menor footprint que satisface el nivel solicitado.


### R3B.3 — MIC PASS físico en G600

- El 21 de agosto de 2026 se validó físicamente el micrófono USB **G600** en Linux Mint.
- Endpoint ALSA confirmado: `plughw:CARD=G600,DEV=0`; PipeWire lo expone como `G600 Mono`.
- La cadena real `micrófono -> ALSA -> VAD -> Vosk -> transcripción` produjo texto y queda marcada `MIC PASS`.
- La ausencia de cámara no invalida este subhito; Vision/Face permanece pendiente.

### R3B.3 — validación MIC-ONLY y verdad de audio

- La falta de cámara no bloquea una evidencia física parcial: `MIC PASS` valida únicamente micrófono -> ALSA -> VAD -> STT real. Face/Vision quedan pendientes.
- Los endpoints de plugins ALSA no demuestran hardware físico; `arecord/aplay -l` es la fuente del preflight para cards/devices y la señal se confirma únicamente ejecutando VAD/STT.
- Las demos físicas no pueden caer silenciosamente a audio sintético. `--simulate` debe ser explícito.
- Vosk sólo se considera verificado si el ZIP descargado conserva y pasa el SHA-256 del catálogo; una carpeta extraída por sí sola no prueba integridad.
- El género de una voz no se deduce del nombre del dataset/voice. Si la fuente oficial no lo declara inequívocamente, se registra `unknown`.

# Decisiones recientes — AILEN

## 2026-08-26

### Latencia conversacional y actualidad Web

- Las palabras aisladas `día`, `hora` y `fecha` ya no abren el parser de Clock;
  sus hints son frases de intención. `qué día es hoy` usa además formato `date`,
  no `time`.
- `AiContextBuilder` no emite un bloque de capacidades cuando la lista está vacía
  y consolidó reglas equivalentes de voz/seguridad. Una traza casual bajó de 444
  a 398 tokens de entrada y de 2.095 s a 1.777 s, con semantic `attempted=false`;
  el ahorro total incluye variación de longitud de salida y no se atribuye entero
  al prompt.
- La guía de interpretación vive en la tool y sólo se inyecta para candidatas. La
  guía de Notes dejó de viajar en consultas Web; el parser medido bajó 416 -> 318
  tokens antes de sumar el schema explícito de noticias.
- WebSearch usa tres resultados por defecto porque el resumen sólo conserva tres.
  DDGS midió mediana 2.766 s con cinco y 1.515 s con tres (tres muestras por grupo),
  con variabilidad externa.
- La prueba posterior corrigió una conclusión previa: snippets Web sin fecha sí
  permitían una inferencia temporal falsa. `news` transporta `published_at`, acepta
  frescura day/week/month y trata ausencia de resultados como vacío normal. No se
  permite que el resumen sustituya timestamps ausentes con conocimiento del modelo.
- El routing Web implícito aún agrega una inferencia qwen de ~1.4–1.7 s. Eliminarla
  requiere evaluar el router estructurado pendiente; no se ocultó con timeouts ni
  una lista central creciente de keywords.

## 2026-08-25

### Auditoría de regresiones físicas ASRock

- El parser semántico sólo usa `intent_hints` declarados por cada tool. Se quitaron
  disparadores temporales genéricos de WebSearch porque `hoy`, `ahora` o `último`
  agregaban una inferencia qwen completa a comentarios cotidianos.
- El historial puede desambiguar una tool sólo después de que el texto actual
  coincide con hints declarados; ya no activa el parser por ser un reply corto.
  `muy bien` después de Clock midió semantic 0.3 ms (`attempted=false`) y turno
  textual completo 1.354 s con qwen3.5:9b bajo la carga observada.
- Una consulta externa implícita usó DDGS real y luego síntesis local: semantic
  1.564 s, tool 4.669 s, main LLM 2.386 s y total texto 8.644 s. Una validación
  posterior detectó que snippets sin fecha aún podían inducir cronología falsa;
  la decisión fechada de 2026-08-26 reemplaza esa conclusión de calidad.
- La telemetría de conversación registra timestamps monotónicos de resolver
  determinista/semántico, tool, construcción de contexto, prompt-eval, generación,
  primer PCM, chunks, `aplay` y total del turno. Las métricas AI separan evaluación
  de prompt, generación y carga cuando Ollama las reporta.
- La captura PipeWire fija período/buffer derivados de `frame_ms`; el VAD no usa
  hangover como evidencia inicial; barge-in propaga un token de cancelación hasta
  `AudioOutputBackend` y conserva frames durante blockers/cooldown.
- CameraControl, RTSP con frames, detector y presencia estable ya no comparten un
  READY optimista. La NC250 fue verificada en NIGHT; RTSP HD entregó frames y YuNet
  ejecutó, mientras que presencia depende de que haya un rostro en cuadro.
- Las expresiones permitidas son overlays transitorios sobre el estado. El modelo
  conversacional todavía no produce metadata expresiva; ese contrato requiere una
  decisión estructural separada y no se reemplaza con keywords de contenido.
- El renderer pixel aceptado físicamente usa 4 px a 800x480, contornos escalonados,
  iris/pupila y tres tonos. Once gestos conservan articulación durante `SPEAKING`;
  la demo aislada a 30 FPS midió 2.1% CPU de proceso y 25.9 MB RSS en ASRock.
- El prompt de voz se compactó manteniendo límites de memoria, tools y actualidad.
  Qwen sigue mostrando variabilidad de estilo; la validación conversacional física
  y el prefetch cancelable de Piper permanecen pendientes.
- Notas y recordatorios persistentes se anuncian sólo cuando SQLite está disponible;
  se eliminó el guardado volátil de notas que podía confirmar éxito y perder datos al
  reiniciar.

## 2026-08-24

### R4: cámaras intercambiables + recordatorios persistentes

- **Fuente de cámara explícita y portable:** `[vision].camera_source = "auto"|"usb"|"rtsp"`. USB y RTSP son modos estrictos; `auto` prioriza V4L2 y sólo usa RTSP como fallback configurado. La compatibilidad `network_camera_preferred` se resuelve al cargar configs legacy; nunca debe sobreescribir una selección nueva explícita. Credenciales RTSP siguen exclusivamente en ENV.
- **NC250 no define el hardware del producto:** es una cámara RTSP opcional disponible por LAN. Debian puede usar una webcam USB reciclada sin modificar código; esto mantiene AILEN armable con periféricos heterogéneos. Ninguna cámara se marca físicamente validada en Debian hasta conectarla/probarla.
- **Notas, timers y recordatorios son conceptos distintos:** notas = persistencia sin vencimiento; timers = duración efímera en memoria; recordatorios = persistencia SQLite con tiempo explícito UTC. Un `recordá que...` sin anclaje temporal conserva compatibilidad como nota; un `recordame ... en 20 minutos`/`mañana a las HH:MM` usa `RemindersTool`.
- **Scheduler sin audio directo:** `ReminderService` publica `REMINDER_DUE`; `LabRunner` encola el anuncio y sólo inicia Piper cuando el estado es IDLE/ATTENTION y no hay interacción activa. La validación audible sigue siendo requisito físico.
- **Ruff EXE002 sobre fuseblk:** la excepción se limita mediante `per-file-ignores` a `src/**/*.py`, `tests/**/*.py` y `tools/**/*.py`; no se desactiva globalmente.

### R4 software en Debian: MPRIS + instalación limpia

- El backend musical real se implementa como transporte MPRIS mediante `playerctl`, sin dependencia Python/DBus pesada, sin `shell=True` y sin permitir que una query de usuario se convierta en ruta, URL o comando.
- `MusicTool()` conserva fail-closed por defecto; `LabRunner` inyecta `MprisMusicService`. Si `playerctl` o un player MPRIS no están disponibles, el resultado sigue siendo `UNAVAILABLE`. La validación audible física sigue pendiente.
- Los entrypoints de AI que dependen de `BudgetPolicy` deben ejecutar migraciones SQLite antes de consultar `ai_usage`; una base ya existente en el host no puede ser una precondición oculta.
- Gemini/OpenCode deben leer el estado R3C/R4 actual y no reconstruir Foundation; se corrigieron los handoffs obsoletos.

## 2026-08-21

### R3B.3 First Physical Lab Validation & Speech Asset Subsystem

- **Catálogo Declarativo Criptográfico de Modelos de Voz (`SpeechAssetCatalog`)**: Todo modelo STT y voz TTS se declara de forma inmutable con URL HTTPS, tamaño exacto en bytes, SHA-256 de 64 hex, licencia y referencia de dataset. Se verificaron para 2026: Vosk Spanish (`vosk-model-small-es-0.42`), Whisper.cpp (`whisper-ggml-tiny`, `whisper-ggml-base`), y voces Piper en español (`es_ES-davefx-medium`, `es_AR-daniela-high`, `es_ES-sharvard-medium`, `es_ES-carlfm-x_low`) junto con sus `.onnx.json`.
- **Prohibición de Deducción de Género por Nombre**: El género de las voces Piper se toma exclusivamente de la metadata oficial del dataset (OpenSLR 61, Harvard, etc.) o se asigna como `unknown` (multi-speaker). Queda prohibido inferir el género a partir de nombres de personas.
- **Seguridad en Almacén y Descargas de Habla (`SpeechAssetStore` & `SpeechAssetDownloader`)**: Almacenamiento en `~/.local/share/ailen/speech/{stt,tts}/` con validación estricta contra path traversal (`is_relative_to`) y fail-closed ante checksum mismatch. Extracción de archivos comprimidos (`.zip` de Vosk) con protección rigurosa contra vulnerabilidades Zip-Slip.
- **Aislamiento de Configuración de Laboratorio (`init_lab_config`)**: El comando `ailen lab config init` genera `runtime/lab/ailen-lab.toml` (gitignored), permitiendo configurar periféricos y modelos locales de prueba sin alterar la configuración canónica `config/ailen.toml`.
- **Verificador Preflight Integral de Preparación Física (`LabPreflightChecker`)**: Evalúa requisitos obligatorios (`[REQ]`) y opcionales (`[OPT]`) antes de una prueba en vivo (`ailen lab preflight`), auditando Face GUI (Tkinter), bibliotecas y cámaras físicas de visión (V4L2), dispositivos de captura y reproducción de audio ALSA, binarios y modelos STT/TTS, y disponibilidad del runtime local de IA.
- **Protección de Privacidad en Consola de Laboratorio**: `LabRunner` emite métricas de longitud y latencia en turnos de conversación (`[stt]` y `[ai]`), evitando volcar el texto completo de transcripciones o respuestas privadas a la salida estándar o logs por defecto.
- **Evaluación del Host Asrock**: El preflight reportó `NOT_READY_FOR_LIVE_TEST` de manera honesta y descriptiva, guiando con precisión la remediación de dependencias del sistema operativo (`python3-tk`), virtuales (`.[vision,stt-vosk]`) y periféricos antes de iniciar la sesión interactiva en vivo.

### R3B.2 Live Lab — auditoría final

- Live Lab no puede instanciar `AudioInteractionCoordinator` con STT/TTS ausentes, porque sus defaults Fake son válidos sólo para tests; fuera de `--simulate` la cadena speech se crea únicamente con backends reales completos.
- La selección de modelos de runtimes existentes es exacta y explícita. Ollama no puede sustituir el modelo planificado por el primer modelo de su inventario ni usar aliases de otra familia/tamaño.
- Un GGUF verificado puede iniciar un `llama-server` temporal propiedad de `LabRunner`; se fija loopback, alias exacto del model_id y cleanup por ownership. `--dry-run` nunca inicia procesos.
- `prepare-ai --start-runtime` es un smoke/health check temporal y detiene su proceso antes de salir; el proceso de la sesión real pertenece a `lab start`.
- Live Lab reutiliza BudgetPolicy, SecretResolver, LAN trust y privacidad R3A; no crea un camino alternativo menos seguro.
- Métricas nunca convierten tokens no reportados en cero y separan latencia de inferencia de TTS/playback.
- R3B.2 queda "software-wired/auditado", no "hardware validado". La primera validación física Mint se separa como R3B.3 antes de R3C.


### R3B.2 Live Lab Integration — cableado conversacional físico

- **Regla Absoluta "No Silent Fakes"**: En Lab Mode real (`ailen lab start` sin `--simulate`), los adaptadores `FakeSttBackend`, `FakeTtsBackend`, `FakeAiBackend`, `FakeVisionBackend` y `FakeAudioBackend` quedan prohibidos. Si falta un componente, se reporta `MISSING_MODEL`, `UNAVAILABLE` o `DISABLED`. `--simulate` es el único modo que permite backends sintéticos con fines de desarrollo/UI offline.
- **Factoría de Componentes Desacoplada (`LabComponentFactory`)**: Aísla la resolución de periféricos y modelos reales de la orquestación del runner, retornando instancias y metadatos estructurados `ComponentStatus`.
- **Single-Flight Interaction Lock y Half-Duplex**: Para evitar inferencias concurrentes o respuestas de voz superpuestas, se implementó un candado atómico que procesa un solo turno conversacional a la vez. El micrófono es inhibido durante la locución (`AudioTurnGate`).
- **Mapeo e Inventario de Modelos en Ollama (`RuntimeModelInventory`)**: Consulta endpoints `/api/tags` y `/v1/models` de Ollama/llama.cpp para verificar modelos cargados sin asumir que el inventario local de GGUFs coincide con los tags de Ollama. Se soportan alias explícitos (`runtime_aliases`).
- **Runtime Local Gestionado y Ownership de Procesos (`ManagedLlamaRuntime`)**: AILEN puede iniciar y gestionar su propio proceso `llama-server` o `llama serve` en `127.0.0.1`. Sólo finaliza procesos si fueron iniciados por AILEN (`owned_by_ailen=True`), respetando servidores preexistentes como Ollama.
- **Workflow `prepare-ai` y Propósito de Modelos (`ModelPurpose`)**: Introduce intenciones de ejecución `SANITY` (validación de pipeline con menor footprint), `BALANCED` (equilibrio óptimo) y `QUALITY` (máxima capacidad dentro de márgenes de seguridad). El comando `ailen lab prepare-ai` guía la inspección, descarga explícita y arranque de runtime.
- **Telemetría y Métricas en Vivo (`LabSessionMetrics`)**: Recolecta métricas reales de latencia STT/AI/TTS, conteo de tokens y transiciones sin inventar valores no medidos, exportando el resumen a `runtime/lab/session_<timestamp>.json`.
- **LabDoctor Mejorado**: Proporciona diagnósticos no invasivos con remediaciones explícitas y opción de salida estructurada `--json`.


### Proyecto

- Se fija `AILEN` como nombre estable del proyecto/plataforma en `/mnt/hdd4tb/repo/ailen`.
- AILEN significa **Asistente Inteligente Local, Evolutivo y Natural**.
- El nombre visible del personaje, su voz y su apariencia serán configurables por instalación.
- Antes de comercialización formal queda pendiente únicamente la verificación marcaria/legal del nombre.
- La disciplina documental seguirá un esquema similar al usado en AndesKey: arquitectura, roadmap, changelog, memoria de estado, ADRs y reglas para agentes.

### Producto

- El producto será un asistente físico para hogar, taller y comercio, no un chatbot de escritorio.
- El rostro será 2D, liviano y expresivo.
- Cámara = ojos, micrófono = oído, parlantes = voz.
- No se necesita una app móvil nativa: la administración será por web responsive en LAN.

### Lab Mode y Model Management Adaptativo (R3B y R3B.1 Lab Stabilization)

- **Detección de Hardware Multiplataforma y Verdad de Hardware**: Se separó la detección en `src/ailen/hardware/` con adaptadores dedicados (`LinuxHardwareAdapter`, `WindowsHardwareAdapter`, `FakeHardwareAdapter`). Se eliminó definitivamente la fabricación de flags o capacidades sintéticas. Si un periférico o flag no fue medido explícitamente (ej. flags de CPU o VRAM disponible en Windows CIM), se reporta `None` (`UNKNOWN`) y no se asume AVX2 o VRAM libre.
- **Manejo Defensivo de Hardware no Medido**: Si la RAM total o disponible no se puede medir (`total_bytes == 0`), el recomendador y planificador emiten `HARDWARE_RAM_UNKNOWN` y `LOCAL_PLAN_BLOCKED_INSUFFICIENT_EVIDENCE` sin convertir falsamente el nodo a Satellite.
- **Modelos GGUF 2026 Verificados con Git LFS**: Se incorporaron al catálogo y se verificaron contra Hugging Face Git LFS (`ggml-org/Qwen3.5-0.8B-GGUF`) los modelos `qwen3.5-0.8b-q4_0` (SHA: `57d19977...`, 563,036,064 bytes) y `qwen3.5-0.8b-q8_0` (SHA: `37ae482d...`, 833,592,096 bytes) con `downloadable=True`. Los modelos no verificados permanecen con `downloadable=False` como metadata histórica.
- **ModelPlanner con Verificación Integral de Disco y CPU**: Valida fracciones de RAM y VRAM en `(0, 1]`, acota `desired_context` al soportado por el descriptor, comprueba espacio en disco libre ($disk \ge descriptor.disk\_size + 100MB$) y respeta requerimientos de CPU también en el camino de GPU offload.
- **Seguridad en ModelStore y ModelDownloader**: `ModelStore` previene path traversal validando IDs con regex estricta y comprobando `path.is_relative_to(base_dir)`. `ModelDownloader` exige HTTPS, prohíbe degradación de HTTPS a HTTP en redirecciones, limita tamaños antes y durante el streaming, y limpia archivos temporales ante cualquier error (fail-closed).
- **Runtimes Desacoplados y Salud Rigurosa (`LocalRuntimeManager`)**: Distingue estados `INSTALLED`, `RUNNING`, `HEALTHY`, `DEGRADED`, `UNAVAILABLE`. Un código HTTP 404 en `/models` indica servidor alcanzable pero no listo, retornando `DEGRADED` (nunca `HEALTHY`). Detecta `llama-server`, `llama serve` y `ollama`.
- **LabRunner Real y LabDoctor No Invasivo**: `LabRunner` inicializa periféricos (Face, Vision, Audio ALSA, STT, TTS, AI), muestra tabla de estado inicial (`READY`, `DEGRADED`, `MISSING_MODEL`, `DISABLED`), soporta flags (`--headless`, `--no-camera`, `--no-audio`, `--no-ai`, `--duration`) y maneja SIGINT/SIGTERM limpiamente sin terminar runtimes externos. `LabDoctor` ejecuta diagnósticos del sistema con salida estructurada `PASS`/`WARN`/`FAIL`/`SKIP`.

### IA e Inferencia Híbrida (R3A)

- **Router Determinista sin LLM**: El enrutamiento no consume tokens ni realiza inferencias. `RuleBasedRouter` evalúa perfil, intención, privacidad, conectividad y presupuesto; su benchmark DEV es reproducible y no se extrapola a hardware objetivo.
- **Outbound Privacy Inviolable**: `OutboundPrivacyPolicy` establece barreras estrictas de salida. Ningún dato `RESTRICTED`/`PRIVATE` se envía a cloud, y a LAN sólo si el nodo es confiable. La auditoría R3A eliminó la sanitización que rebajaba un request bloqueado a `PUBLIC`: ahora falla cerrado con `PermissionError`.
- **Circuit Breaker Económico**: `BudgetPolicy` consulta `ai_usage`. `0 USD` significa no gastar; sólo `None` representa sin límite interno. Los precios cloud no tienen defaults históricos: deben configurarse con valores vigentes y el uso desconocido no se registra como costo/token cero inventado.
- **Manejo Seguro de Credenciales**: `SecretResolver` prohíbe API keys en `ailen.toml`, SQLite o logs. Variables de entorno y archivos de secretos son admitidos; en POSIX, archivos con permisos para grupo/mundo se rechazan. Cloud falla cerrado si falta endpoint/model/credencial.
- **Cliente HTTP Genérico Desacoplado**: Se utiliza `GenericOpenAiBackend` construido con la librería estándar de Python (`urllib.request`), permitiendo interactuar con cualquier servidor OpenAI-compatible (llama.cpp server, Ollama, vLLM, LiteLLM, Groq, OpenRouter, etc.) sin librerías externas pesadas.
- **Orquestación y Coordinación End-to-End**: `AiOrchestrator` ejecuta la cadena de fallback (`primary` -> `fallbacks`), mientras que `ConversationCoordinator` unifica el ciclo completo `Transcript` -> `AiContextBuilder` -> `RuleBasedRouter` -> `AiOrchestrator` -> `AudioInteractionCoordinator.speak()`.

### IA

- La identidad del asistente vive en AILEN Core, no en el LLM.
- Se adopta arquitectura híbrida: reglas/tools locales + capacidad LLM local
  obligatoria del producto (activable por instalación) + LAN Brain opcional + API
  cloud rápida.
- Los modelos cloud están orientados a consultas breves, atención y síntesis; no se requiere razonamiento pesado por defecto.
- El router debe considerar costo, latencia, disponibilidad, privacidad y hardware.

### Hardware

- Banghó Zero G05 de 8 GB + M.2 500 GB será el primer prototipo real.
- Ryzen 5 5500 + 48 GB + RTX 3060 12 GB será laboratorio, no requisito del producto.
- SF20BA será plataforma objetivo para optimización, primero 8 GB y luego 4 GB.
- Equipos de 2 GB podrán ser Satellite/Cloud si las mediciones lo permiten.
- Equipos con pantalla rota pueden reutilizarse mediante monitor externo.

### Presencia física y Face (R2A)

- Se separa la capa lógica de animación (`FaceAnimator`) y los modelos de pose geométrica (`FacePose`) de cualquier biblioteca gráfica. El motor es determinista, corre sin pantalla y genera poses normalizadas (-1..1 / 0..1).
- Backend gráfico POC: se adopta `TkinterFaceController` como renderer interactivo de prueba, sin dependencia pip pero con requisito de `python3-tk` y un stack gráfico del sistema. No se fijan todavía cifras de RAM/CPU ni compatibilidad final de appliance hasta medir en hardware objetivo. `NullFaceController` mantiene soporte headless de primera clase.
- Detección de presencia POC: se utiliza clasificador Haar cascade de OpenCV a 5 FPS y 320px como dependencia opcional `[vision]`. Se prohíbe el reconocimiento de identidad, biometría y almacenamiento de imágenes.
- Debounce temporal (`VisionDebouncer`): se separa la observación instantánea de cámara del estado estable de presencia usando `vision.presence_debounce_seconds` (2.0s), previniendo falsos positivos de un solo frame y dropouts momentáneos.
- `InteractionCoordinator` integra la presencia debounced con `StateManager`, `SocialEngine` y actualiza la mirada (`gaze`) y expresiones en `FaceController`.

## 2026-08-29 — Retrato raster animado como estilo visual por defecto (histórico, supersedido por R5B)

- `face_style="portrait"` pasa a ser el estilo visual por defecto. El personaje se renderiza desde el retrato raster aprobado de AILEN en vez de intentar reproducirlo con geometría Tkinter.
- El asset fuente conservado es exactamente el PNG generado/aprobado, SHA-256 `d47611560b3ccc38c34ec4b65241280654f75eb86d54f697b5de7deb96d18584`; los frames de mirada, parpadeo y boca se derivan localmente de ese mismo asset y se empaquetan con el wheel.
- `FaceAnimator` y `FacePose` siguen siendo la autoridad de movimiento. El backend raster sólo proyecta sus valores sobre patches de ojos/boca y parallax, por lo que Vision, TTS y estados no se acoplan a la imagen.
- En ese corte, `pixel` y `vector` permanecían como estilos legacy/fallback. La
  política vigente está documentada arriba: FacePack default, fallo headless y
  renderers legacy únicamente por selección manual.

### Audio Local, VAD, STT y TTS (R2B)

- **Formato canónico**: se establece PCM 16-bit signed LE, 1 canal (mono), 16000 Hz en `ailen.audio.pcm`. Es el estándar de intercambio para VAD, STT, TTS y utilidades de energía.
- **Audio I/O**: en Debian 13 minimal se adopta ALSA (`arecord` y `aplay`) mediante subprocesos seguros con timeouts y pipes. Cero dependencias C adicionales en el Core. Para testing y CI se proveen backends `FakeAudioInputBackend` y `FakeAudioOutputBackend`.
- **VAD liviano y Utterance Collection**: `EnergyVad` en Python puro sin dependencias ML calcula RMS en frames de 20 ms; los benchmarks DEV se registran sin extrapolar porcentajes de CPU. `UtteranceCollector` usa defaults actuales de pre-roll 200 ms, mínimo de voz 250 ms, timeout de silencio 700 ms y corte máximo 15 s.
- **Half-Duplex obligatorio**: se crea `AudioTurnGate` con estados `LISTENING_ALLOWED` y `SPEAKING_BLOCKED` más settling cooldown acústico (200 ms) para evitar que el bot transcriba su propia voz o se auto-escuche.
- **STT local offline**: `VoskSttBackend` queda como candidato principal de hardware limitado y `WhisperCppSttBackend` como alternativa; `whisper-cli` es el nombre actual del binario y no se fabrican valores de confidence cuando el motor no los reporta.
- **TTS local y rostro**: `PiperTtsBackend` se adapta al CLI actual generando WAV temporal y extrayendo sample-rate/canales reales. El `AudioInteractionCoordinator` aplica por ahora un nivel RMS global durante el playback; lip-sync dinámico por chunks queda pendiente.
- **Coordinación de audio**: `AudioInteractionCoordinator` conecta el pipeline micrófono -> VAD -> STT -> EventBus y TTS -> Mouth Sync -> Speakers.
- **Benchmark y Hardware**: se crea `tools/benchmark_audio.py` con mediciones reproducibles en DEV machine (`docs/benchmarks/dev_audio_benchmark.md`), señalando explícitamente que la validación en hardware target (Banghó Zero G05 / SF20BA) queda pendiente de ejecución física.

### Web / Admin / Seguridad

- El panel web deja de depender de `AILEN_ADMIN_PASSWORD`: la credencial administrativa de **usuario + contraseña** es persistente en SQLite (tabla `admin_credentials`, migración 0002, fila única) y se gestiona con `ailen admin set-password` vía getpass (nunca password en argv). Detalle completo en `ADR-007-local-admin-auth.md`.
- KDF baseline del panel: PBKDF2-HMAC-SHA256 con 600k iteraciones (stdlib, OWASP-aligned), salt aleatorio de 16 bytes por credencial, comparación constant-time. Fail-closed: sin credencial configurada nadie autentica.
- Lockout por IP: 5 fallos en 5 minutos => bloqueo 5 minutos. Sesiones siguen efímeras en memoria (deuda aceptada).
- `web.host`/`web.port` NO son editables desde el panel: cambiar el bind en caliente puede exponer el panel o dejar afuera al operador; se administran por archivo/CLI y aplican al reiniciar.
- `SettingsService` con allowlist explícita como único camino Web -> configuración (MODULE_CONTRACTS §16): validación server-side completa antes de guardar, claves desconocidas rechazadas, escritura atómica del TOML; la vista `/config` no renderiza secretos.
- Hardening HTTP baseline del servidor stdlib: body máx. 1 MiB (413), métodos permitidos explícitos (405), POST sólo `application/x-www-form-urlencoded` (415), CSP `default-src 'self'`, Referrer-Policy, Cache-Control no-store, timeout de socket.
- Se agrega sección `[identity]` a la configuración (`display_name` default neutro "Asistente"): AILEN es marca/plataforma, nunca nombre hardcodeado del personaje.
- Auditoría de integración: se corrige wake desde `SLEEP`, se hace efectivo el username del login, SQLite pasa a `0600` en POSIX, SettingsService adopta patch parcial, y rutas de configuración explícitas inexistentes dejan de caer silenciosamente a defaults.

### Sistema base / Distribución

- ADR-008 acepta **Debian 13 stable amd64 netinst/minimal** como baseline del appliance.
- Se distinguen oficialmente **Lab Mode** y **Appliance Mode** (`docs/deployment/LAB_AND_APPLIANCE_MODES.md`). Linux Mint y Windows 11 son laboratorios: ejecutar AILEN no debe cambiar login, suspensión, shell, servicios ni reiniciar la PC. Debian dedicado sí será preparado por un provisionador idempotente que configure hardware, modelos, systemd, energía, primer boot y reinicio final tras health check.
- Lab y Appliance compartirán `HardwareCapabilityReport` + `ModelCatalog/ModelPlanner`; la descarga de modelos en laboratorio requiere consentimiento explícito y en appliance sólo puede ejecutar artefactos aprobados por manifest/hash.
- No se instala escritorio completo. Con el POC Tkinter, un nodo con pantalla usa sólo stack gráfico mínimo (Xorg/xinit/python3-tk); un nodo headless no instala X. Un futuro renderer SDL2/DRM-KMS podrá retirar Xorg sin cambiar Debian.
- Alpine queda como experimento futuro únicamente para Satellites extremos si un benchmark demuestra ventaja suficiente para justificar una segunda plataforma soportada.
- Las actualizaciones se diseñarán con releases versionadas, verificación, health check y rollback. Clientes: `stable`; prototipos: `beta`; desarrollo: `nightly`.
- Git local y remoto ya existen; commits sólo se realizan tras auditoría y no se hace push sin autorización explícita.

### Desarrollo paralelo

- Se documenta un primer slice `Foundation/Core + Web/Mocks` antes de integrar Face/Audio/AI reales.
- Gemini y OpenCode pueden trabajar en paralelo con áreas de propiedad temporal separadas para reducir conflictos.
- Ningún agente debe hacer commit/push; la integración se revisará completa antes del primer commit.
- `TASKS.md` es la cola inmediata y `docs/operations/R1_PARALLEL_WORK.md` contiene los prompts/alcances listos para usar.
- Face/STT/TTS/LLM reales se validarán por POC/benchmark antes de fijarlos como dependencia definitiva.
- **Lab de voz: PipeWire sobre acceso exclusivo `plughw`**: en Linux Mint, conversación simultánea de captura/reproducción usa el endpoint ALSA `pipewire`; `plughw` queda útil para diagnóstico físico pero puede bloquear playback mientras `arecord` mantiene abierto el G600.
- **Ollama nativo para conversación rápida**: cuando el runtime detectado es Ollama, AILEN usa `/api/chat` en loopback con `think=false` y keep-alive de 30 minutos en Lab. El shim OpenAI-compatible sigue disponible para runtimes genéricos, pero no es la vía preferida para modelos Qwen con thinking en conversación de voz.
- **Perfil de voz breve**: el Lab reduce silencio final a 500 ms y máximo de salida a 96 tokens. El texto TTS es una proyección normalizada de la respuesta (sin Markdown/URLs/código decorativo), no una mutación de la respuesta original.
- **AILEN sin GPU obligatoria**: la selección de inferencia se adapta al hardware. Equipos débiles conservan Core/tools y delegan a LAN/cloud; equipos capaces usan un modelo local pequeño/medio. La GPU de Asrock no define requisitos comerciales.
- **Sin model hopping por turno**: AILEN selecciona un modelo estable por nodo/sesión y lo mantiene residente de forma acotada; cambiar modelos por consulta penaliza cold-start y memoria.
- **Tools antes que LLM para acciones básicas**: música, volumen, timer, hora, notas y status se resuelven de forma determinista cuando el intent es claro. Web sólo mediante herramientas controladas por Core.

### Vision física y compatibilidad OpenCV — 2026-08-23

- Mientras el backend POC dependa de `CascadeClassifier`, `[vision]` queda limitado a OpenCV 4.x; OpenCV 5 mueve Haar a contrib y no es compatible con esta ruta actual.
- El preflight valida la API/cascade real, no sólo `import cv2`.
- Cámara configurada ausente puede reemplazarse por un endpoint V4L2 detectado automáticamente.
- Presencia usa histéresis: adquisición rápida con tolerancia a misses cortos y salida más lenta; eventos de presencia representan transiciones reales.

### Haar no autoriza afirmaciones visuales — 2026-08-23

- El backend Haar queda como experimental y sin autoridad para que el LLM afirme "te veo"/"te detecto".
- `profileface` se retira como fallback por falsos positivos observados.
- YuNet (`FaceDetectorYN`) se evalúa como detector facial CPU-first con confidence real; sólo se promoverá tras control negativo y pruebas físicas repetibles.

### YuNet promovido en Lab — 2026-08-23

- YuNet (`FaceDetectorYN`) se promueve como detector preferido del Lab actual tras control negativo limpio y detección facial con confidence ~0.92-0.95.
- Haar permanece como fallback experimental sin autoridad suficiente para afirmaciones visuales fuertes.
- `VisionConfig` ahora distingue detector, modelo y score threshold; el preflight valida el detector realmente configurado.
- La capacidad visual sigue limitada a rostro/presencia/posición aproximada; no hay reconocimiento de objetos ni comprensión multimodal de escena.

### Cierre auditado R3C post-oX Alpha — 2026-08-23

- Las tools de red usan una política outbound explícita (`network.outbound_web_enabled`) separada de cloud/LLM.
- Una tool destructiva no se ejecuta todavía aunque haya `confirm=true`: queda bloqueada hasta existir un executor aislado/cancelable.
- Los timeouts de tools no destructivas devuelven control mediante worker daemon, pero no equivalen a hard-cancel de una operación ya iniciada.
- La conversación de producción crea/cierra una sesión SQLite `sess-*` y persiste turnos al completarlos; `lab_*` queda reservado a telemetría.
- Datos de WebSearch son externos/no confiables: campos acotados, URLs saneadas y prompt injection tratado en system+turn context. WebFetch sólo HTTPS.
- `MusicTool` sin backend real debe devolver `UNAVAILABLE`; el backend in-memory no representa reproducción física.
- Benchmark Vision nunca duplica frames que no observó y permite fase `uncontrolled` cuando no existe ground truth.

### Semantic tool fallback local — 2026-08-23

- Las reglas deterministas siguen siendo la primera opción por latencia y seguridad.
- Cuando una frase parece comando pero no coincide con reglas, sólo el backend `local` puede actuar como parser semántico JSON; cloud/LAN/network tools no participan.
- El parser semántico nunca ejecuta: sólo propone una tool allowlisted y argumentos, que vuelven a pasar por schema + `ToolExecutor`.
- Los fragmentos STT vagos no deben resolverse inventando continuidad; se solicita repetición.
- Estado físico Vision es contexto silencioso y no una frase que el modelo deba repetir en cada respuesta.

### Intención semántica y periféricos de red — 2026-08-23

- Herramientas deterministas/contextuales tienen prioridad sobre el LLM conversacional; una frase ambigua de herramienta debe aclararse y no convertirse en una acción por inferencia agresiva.
- Se permite un modelo local auxiliar de intención (`ai.local.intent_model`) distinto del modelo conversacional. Debe estar ya instalado; no hay descarga implícita.
- En el laboratorio Asrock se usa `qwen2.5-coder:3b` para intención acotada y `qwen3.5:9b` para conversación.
- Las cámaras IP/RTSP son candidatas válidas de Vision/Audio; secretos de cámaras no deben aparecer en TOML, logs, SQLite ni documentación.

### Capacidades verificables y cámara de red — 2026-08-24

- Las preguntas sobre qué puede hacer AILEN no deben responderse por generación libre: Core describe únicamente herramientas registradas y capacidades físicas activas.
- El fallback semántico sólo se activa por pistas léxicas completas o contexto realmente relacionado; no por coincidencias de subcadenas accidentales.
- Las memorias de conversación se distinguen explícitamente de system prompt, metadatos y sensores para evitar recuerdos inventados.
- La NC250 se integra como fuente Vision RTSP preferida mediante host/ruta/usuario en config y contraseña sólo por variable de entorno. Nunca persistir credenciales de cámara en TOML, docs o logs.
- El micrófono RTSP de la NC250 queda validado como fuente técnica, pero no sustituye al `AudioInputBackend` hasta implementar captura remota con buffering/reconexión y pruebas VAD/STT.
- Para uso nocturno, preferir modo Auto de la cámara y validar por readback + prueba YuNet; no asumir IR activo sólo porque el hardware lo soporta.
### R4 — local-first objetivo y Provider Manager externo corregido (2026-08-31)

- **Producto, no ASRock**: el hardware vendido debe ejecutar un GGUF local
  cuantizado elegido y medido por tier. Las APIs son opcionales o una futura
  suscripción administrada. ASRock sólo verifica contratos y no demuestra 4/8 GB.
- **Desactivación real**: `ai.local.enabled=false` excluye discovery, backend,
  managed runtime, prewarm, intent model y fallback; no se consulta Ollama.
- **Prioridad efectiva**: `/ia` alimenta el orden real. Se intenta el preferido
  sano y luego prioridad; `cloud` es la única ruta para OpenAI-compatible.
- **Privacidad comprobada**: el boundary reconstruye cada intento remoto con el
  turno actual y metadata allowlisted. Tests de captura rechazan historial,
  memoria, personalidad, persona, capabilities, paths, tools y secretos.
- **Errores y cuota**: adapters normalizan timeout/rate limit/auth/model/network/
  unavailable/invalid response/internal; 429 respeta `Retry-After` acotado y
  activa cooldown antes del fallback.
- **Medición honesta**: AGY fue funcional pero demasiado lento para voz (primer
  texto 6,74 s avg, 8,88 s p95 bajo contención; spawn ~0,4 ms). OpenCode Free
  completó 1/4 antes de un 429. Ninguno se promueve por esa prueba.
- **Panel**: catálogo live/configured/known-fallback/manual, health e inferencia
  verificada se distinguen. Guardar requiere reinicio; no hay hot reload fingido.
- **Capacidad local obligatoria, estado local explícito**: el producto soporta
  operación completamente local; `ai.local.enabled=false` sigue significando que
  esa instalación no toca runtimes locales. No son afirmaciones contradictorias.
- **Una interfaz local**: Ollama y llama.cpp administrado implementan
  `AiBackend`/`StreamingAiBackend`. llama.cpp carga un GGUF verificado bajo
  demanda; la presión de RAM sólo libera un modelo/runtime ocioso y propio.
- **Envelopes, no promesas**: 4/8/16/32/64+ GB tienen presupuestos de modelo, contexto y
  piso libre canónicos. La elección final exige benchmark físico con todo el stack;
  el detector no transforma una ficha que entra en RAM en soporte declarado.
- **Evidencia STT hasta Core**: texto, confianza real, motor, duración,
  `utterance_id`, barge-in, truncamiento y alternativas forman el turno. Una tool
  mutante no se ejecuta con audio dudoso/truncado aunque el intent puntúe alto;
  un barge-in completo no se confunde con una frase cortada.
- **Llamada incremental**: deltas reales se segmentan en frases y alimentan una
  cola TTS de un elemento dentro de un único turno cancelable. Barge-in detiene
  nuevas frases; no se mezcla fallback detrás de una respuesta parcial ya oída.
- **Resolver no es chatbot**: charla, saludos, opiniones y humor llegan al LLM;
  respuestas deterministas quedan para tools/resultados verificables, errores
  operativos y repreguntas STT. Ailén es general y el taller es contexto, no
  identidad obligatoria.
- **Bandas STT explícitas**: confidence real se clasifica en ruido, dudoso,
  conversación y acción; `None` permanece desconocido. Longitud de texto no
  convierte audio de confianza extremadamente baja en conversación válida.
  Alternativas sólo se usan si vienen del motor y superan el umbral.
- **Cancelación generacional**: cada habla tiene `turn_id/generation_id`;
  playback se corta de inmediato y resultados TTS obsoletos se descartan.
  Piper/ONNX activo puede drenar bajo lock y se mide aparte. Assistant
  interrumpido no entra como respuesta completa en el contexto persistido.
- **`auto` adaptativo**: modalidad, privacidad, disponibilidad, complejidad y
  elegibilidad realtime eligen la clase de primary. Las prioridades no
  reemplazan esta política y sólo ordenan equivalentes/fallbacks. Preferencia
  explícita sigue siendo autoritativa si está permitida.
- **Calibración sin ficción**: `/audio` mide RMS real en RAM o falla
  honestamente. El harness `lab calibrate-voice` compara WebRTC 2/3 y
  380/500/600 ms y tiene un bloque barge-in real; no persiste PCM ni cambia
  thresholds.
- **Calificación local versionada**: catálogo `candidate/qualified/rejected`,
  manifest con artefacto/licencia/template/digest y evidencia de hardware. En
  el envelope seguro gana la mejor calidad aprobada, no siempre el menor
  footprint. Las bandas mayores a 0.8B siguen candidatas sin descargas ni hashes
  inventados.
- **AGY aislado no quedó mínimo**: un custom agent local a la carpeta Lab con
  `tools: []` siguió reportando el contexto amplio del CLI; una muestra pública
  consumió 17.425 input tokens y ~6,48 s wall. No se alteró configuración
  global; AGY permanece non-realtime para voz automática en esta ruta/version.
