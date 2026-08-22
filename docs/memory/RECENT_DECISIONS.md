### R3B.3 — validación MIC-ONLY y verdad de audio

- La falta de cámara no bloquea una evidencia física parcial: `MIC PASS` valida únicamente micrófono -> ALSA -> VAD -> STT real. Face/Vision quedan pendientes.
- Los endpoints de plugins ALSA no demuestran hardware físico; `arecord/aplay -l` es la fuente del preflight para cards/devices y la señal se confirma únicamente ejecutando VAD/STT.
- Las demos físicas no pueden caer silenciosamente a audio sintético. `--simulate` debe ser explícito.
- Vosk sólo se considera verificado si el ZIP descargado conserva y pasa el SHA-256 del catálogo; una carpeta extraída por sí sola no prueba integridad.
- El género de una voz no se deduce del nombre del dataset/voice. Si la fuente oficial no lo declara inequívocamente, se registra `unknown`.

# Decisiones recientes — AILEN

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
