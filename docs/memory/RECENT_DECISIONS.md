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
- **CPU-only es ciudadano de primera clase**: `recommend_inference_profile()` maneja deterministamente 2 GB (RULE_ONLY/SATELLITE), 4 GB (RULE_ONLY conservador por defecto, FAST con opt-in), 8 GB (FAST CPU) y 16+ GB (BALANCED CPU), sin asumir la existencia de GPU a menos que esté físicamente medida.
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
- Se adopta arquitectura híbrida: reglas/tools locales + LLM local opcional + LAN Brain opcional + API cloud rápida.
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
