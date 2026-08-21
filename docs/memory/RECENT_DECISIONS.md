# Decisiones recientes — AILEN

## 2026-08-21

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
