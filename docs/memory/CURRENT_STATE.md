# Estado actual — AILEN

**Fecha:** 2026-08-26
**Versión:** `0.1.0-dev.0`  
**Fase:** R4 activo sobre baseline R3C auditado. Tools allowlisted/routing determinista, memoria conversacional SQLite y Web boundary permanecen estables. R4 ya incorpora selección explícita de fuente de cámara (`auto|usb|rtsp`), recordatorios persistentes separados de notas/timers (migración 0004 + `REMINDER_DUE`), DDGS real y transporte MPRIS cableado en software. Web Admin, latencia WebSearch y reproducción musical audible siguen abiertos. En Debian están instalados Vosk + Whisper.cpp tiny/base para comparación; Vosk continúa baseline hasta prueba física suficiente. Suite actual: 591 tests; Ruff, mypy (135 archivos) y diff-check verdes.

## Auditoría física de regresiones ASRock — 2026-08-26

- Latencia: se confirmó doble inferencia en comentarios con palabras temporales
  genéricas. El routing semántico ahora usa sólo hints declarados; `hoy está
  fresco` vuelve a una inferencia. El historial ya no abre por sí solo el parser:
  `muy bien` tras Clock midió semantic 0.3 ms (`attempted=false`), 458 tokens de
  entrada, main LLM 1.340 s y turno texto total 1.354 s. La telemetría separa
  resolvers, tool, prompt-eval, generación, TTS/chunks, primer PCM y playback.
- Audio G600/PipeWire: período/buffer explícitos estabilizaron frames de 20 ms
  (p95 observado 128.6 -> 22.66 ms). Hangover ya no satisface por sí mismo
  `min_speech_ms`. El G600 produjo pulsos idle ~0.012–0.023 RMS que alargaban
  utterances hasta 15 s; threshold Lab 0.022 las cerró en 0.26–1.98 s. No es un
  default global y debe revalidarse con micrófono sano/voz baja.
- Barge-in: el token de cancelación llega hasta `aplay`, `stop()` funciona desde
  otro thread y los frames sobreviven processing/cooldown. Se observaron cortes
  de 0.2 ms durante conversación y el audio preservado produjo transcript correcto.
- NC250: gestión verificada en NIGHT=3 sin persistir credenciales. RTSP HD entregó
  frames recientes con thread vivo; YuNet, presencia raw/estable y Core llegaron a
  `present=true` con operador en cuadro. Un episodio de tres read timeouts degradó
  salud y reconectó la misma ruta correctamente. VGA no abrió en este firmware.
- Piper usa prefetch acotado de una oración. Los chunks integrados observados
  tuvieron `gap_ms=0`; en muestras aisladas el residual fue ~13–219 ms frente a
  ~1.36–1.43 s sin prefetch.
- WebSearch implícito funcionó por DDGS real y no cayó a generación libre, pero el
  turno textual midió 8.644 s: semantic 1.564 s, provider 4.669 s y resumen Qwen
  2.386 s. Tras limitar el default a los tres resultados que Core realmente usa y
  mover la guía específica a cada tool, una repetición midió 4.988 s: semantic
  1.374 s, provider 2.030 s y resumen 1.581 s. La red y la longitud generada varían;
  sigue siendo demasiado lento para voz y aún conserva dos inferencias seriales.
- Actualidad Web: `DDGS.text()` entregó snippets sin año y Qwen presentó por error
  Python 3.14 como futura. `WebSearchRequest` ahora separa `text|news`, acota
  frescura y propaga `published_at` desde `DDGS.news()`. Core descarta noticias sin
  timestamp válido o fuera de ventana, y «No results found» se normaliza como
  búsqueda vacía honesta. Una consulta ambigua por «Python» devolvió noticias
  fechadas de serpientes y el resumen las rechazó como irrelevantes; al especificar
  «lenguaje de programación Python», routing midió 1.807 s, DDGS 1.654 s y no hubo
  resultados válidos del día, sin síntesis posterior que inventara actualidad.
- Conversación textual: la frase casual con «día» registró deterministic 0.6 ms,
  semantic 0.5 ms con `attempted=false`, 398 tokens de entrada y turno total
  1.777 s. El bloque de capacidades vacío ya no entra al prompt. En seis muestras
  casuales la mediana fue 1.559 s y 42.5 tokens de salida; Qwen todavía agrega
  preguntas/ofertas de soporte de forma variable, por lo que naturalidad no se
  considera cerrada ni se aplicó un filtro que pueda borrar preguntas legítimas.
- Expresiones: estado y gesto transitorio están separados; TTS ya no borra el
  gesto explícito. El renderer pixel usa una malla de 4 px, contornos de dos
  escalones y tres tonos a 800x480; once gestos acotados tienen geometría propia
  y la boca articula aun bajo un gesto. Demo ASRock: 2.1% CPU de proceso y 25.9 MB
  RSS a 30 FPS. La revisión fue aceptada visualmente por el operador; no existe
  todavía metadata emocional espontánea desde el turno conversacional.
- Pendiente: repetir TTFAR/escucha con micrófono sano; optimizar navegación sin
  dos inferencias seriales; acotar respuestas todavía largas de Qwen y diseñar metadata
  expresiva conversacional sin dar control directo de UI al modelo.

## Actualización Debian / R4 software — 2026-08-24

- Vision deja de depender de un periférico concreto: `[vision].camera_source` admite `auto`, `usb` o `rtsp`. `usb` nunca cae silenciosamente a red, `rtsp` falla cerrado si falta configuración/secret y `auto` prioriza V4L2 antes de RTSP. Configs antiguas con `network_camera_preferred=true` se migran al cargar; la opción nueva explícita siempre prevalece. El Lab Debian queda en `camera_source="usb"`; la NC250 continúa como fuente RTSP opcional de red y no bloquea este host. La webcam reciclada USB aún no fue conectada/validada físicamente en Debian.
- Recordatorios persistentes R4: migración `0004_reminders`, `RemindersTool`, `ReminderService` y evento `REMINDER_DUE`. Frases con tiempo explícito (`en 20 minutos`, `mañana a las 10`, fecha/hora) se separan de notas atemporales y timers volátiles. El scheduler sólo publica eventos; el runner encola TTS hasta quedar en IDLE/ATTENTION para respetar half-duplex. La base Lab Debian ya está en schema 4; anuncio acústico real queda pendiente de prueba física.
- Debian Lab tiene Ollama 0.32.15 en el HDD de 4 TB y `qwen3.5:2b-q4_K_M` medido sobre RX 580 vía Vulkan (100% GPU, ~15.45 tok/s en benchmark corto). Vosk sigue STT activo; Whisper.cpp tiny/base están instalados y verificados para comparación física posterior.
- `MprisMusicService` implementa transporte local real sobre MPRIS mediante `playerctl`, con argv explícito, `shell=False`, timeout acotado y fail-closed cuando no existe backend/player. Lab lo registra detrás de `MusicTool`; las queries de texto libre no se reinterpretan como archivos o URLs.
- La reproducción musical audible todavía NO está validada físicamente en este host; el ítem R4 permanece abierto hasta probar un reproductor MPRIS real.
- Una instalación limpia en Debian reveló que `ailen diagnose ai` y `ailen demo ai` podían consultar `ai_usage` antes de ejecutar migraciones. Ambos caminos ahora migran SQLite antes de construir `BudgetPolicy`.
- Entorno Debian de desarrollo preparado con `.venv`, OpenCV/Piper y tooling. Suite: 503 tests pasan y 1 se omite por asset/hardware no presente; Ruff limpio ignorando únicamente `EXE002` causado por semántica de permisos del montaje NTFS, mypy limpio en 129 archivos y `git diff --check` limpio.
- `AGENTS.md` y `docs/operations/AGENT_HANDOFF.md` fueron actualizados para evitar que Gemini/OpenCode trabajen con el estado obsoleto de Foundation.

## Qué existe

- carpeta del proyecto creada en `/mnt/hdd4tb/repo/ailen`;
- definición del producto;
- plan maestro;
- arquitectura inicial;
- roadmap hasta 1.0.0;
- changelog y versionado inicial;
- reglas para agentes y contribución;
- estructura documental inspirada en AndesKey;
- comportamiento del producto documentado (`PRODUCT_BEHAVIOR.md`);
- plan de implementación operativo (`IMPLEMENTATION_PLAN.md`);
- contratos entre módulos (`MODULE_CONTRACTS.md`);
- task board de R1, R2A, R2B, R3A y R3B (`TASKS.md`);
- handoff específico para Gemini/OpenCode/Codex (`AGENT_HANDOFF.md`);
- matriz de aceptación verificable (`ACCEPTANCE_MATRIX.md`);
- carpetas preparadas para código, pruebas, scripts, empaquetado y releases.

- Foundation/Core ejecutable (`pyproject.toml`, CLI `ailen`, versión unificada);
- Sistema de configuración tipado con `schema_version` y plantilla versionada (`config/ailen.example.toml`);
- Logging estructurado con redacción automática de secretos y tokens;
- Diagnóstico de hardware best-effort (`ailen diagnose hardware`) y recomendador de perfiles;
- RuntimeState y HealthService observables;
- EventBus in-memory ligero con suscripciones tipadas, aislamiento de errores y correlation IDs;
- SocialEngine determinista con modos sociales (`HOME`, `WORKSHOP`, `SHOP`, `PUBLIC`, `PRIVATE`, `SLEEP`), cooldown y deduplicación por sesión de presencia;
- `SocialPrivacyPolicy` determinista fuera del LLM con aislamiento inviolable de memorias privadas en `PUBLIC` y `SHOP`;
- `InteractionCoordinator` orquestando ciclo de presencia física, transiciones de estado, decisiones sociales y publicación de eventos;
- `PersonalityBoundary` con límites inviolables sobre seguridad, herramientas y privacidad;
- Panel web utilizable desde celular: `SettingsService` con allowlist de campos administrables, vista `/config` responsive (GET/POST con CSRF, validación server-side, guardado atómico del TOML), identidad del personaje configurable (`[identity].display_name`, voz) separada de la marca AILEN;
- Autenticación administrativa persistente por usuario + contraseña en SQLite (migración `0002_admin_credentials`, ADR-007): PBKDF2-HMAC-SHA256 con 600k iteraciones, salt aleatorio, comparación constant-time, lockout por IP, fail-closed sin credencial; CLI `ailen admin set-password` vía getpass;
- Hardening HTTP baseline del panel: límite de body (413), métodos permitidos (405), Content-Type exigido en POST (415), CSP/Referrer-Policy/no-store, timeout de socket; fallos de diagnóstico no tiran abajo el panel;
- SQLite endurecida con permisos owner-only (`0600`) en POSIX porque contiene memoria privada y credencial administrativa derivada;
- `SettingsService.update()` usa semántica de patch parcial; la Web traduce checkboxes HTML ausentes a `false`;
- Motor lógico de rostro `FaceAnimator` y modelo `FacePose` agnóstico de renderer, con parpadeo no periódico, micro-movimientos y apertura de boca;
- Baseline de despliegue aceptado en ADR-008: Debian 13 stable amd64 netinst/minimal, sin entorno de escritorio; con Tkinter se usa sólo Xorg/xinit/python3-tk y los nodos headless no instalan X;
- Backend gráfico POC `TkinterFaceController` (sin dependencia pip, requiere `python3-tk`/stack gráfico del sistema) y `NullFaceController` para headless; consumo real pendiente de benchmark físico;
- `VisionDebouncer` con confirmación asimétrica de presencia/ausencia y gracia de dropout;
- Backend de cámara `OpenCvVisionBackend` con YuNet preferido en Lab para rostro/posición y Haar como alternativa experimental explícita;
- Formato canónico de audio: PCM 16-bit signed LE, mono, 16000 Hz (`src/ailen/audio/pcm.py`) con RMS matemático puro;
- VAD en Python puro (`EnergyVad`) con umbral configurable y hangover; benchmark lógico DEV documentado sin extrapolar porcentaje de CPU a hardware objetivo;
- `UtteranceCollector` con defaults actuales de pre-roll 200 ms, mínimo de habla 250 ms, silencio final 700 ms y corte máximo 15 s;
- `AudioTurnGate` bloquea STT normal durante processing/TTS; barge-in inspecciona RMS por separado, cancela playback y conserva audio de usuario;
- Backends I/O reales ALSA (`AlsaAudioInputBackend`, `AlsaAudioOutputBackend`, `AlsaDeviceEnumerator`) y fakes para CI/tests;
- Backend STT local offline `VoskSttBackend` (extra `[stt-vosk]`) y alternativa `WhisperCppSttBackend` (`whisper-cli` actual, nombres legacy best-effort); no inventan confidence cuando el motor no lo provee;
- Backend TTS local offline `PiperTtsBackend` por la API Python canónica, con voz cacheada y PCM incremental; no existe fallback CLI/WAV;
- `AudioInteractionCoordinator` integrando micrófono, turn gate, VAD, STT, TTS y un nivel de boca RMS básico durante playback;
- AI Router determinista `RuleBasedRouter` con soporte para todos los perfiles de hardware (`SATELLITE`, `CLOUD`, `HYBRID`, `LOCAL`, `LAN_BRAIN`), fallback explícito y reason codes estructurados (`RULE_ONLY_INTENT`, `CLOUD_FAST_PATH`, `CLOUD_BUDGET_EXCEEDED`, `PRIVATE_REMOTE_BLOCKED`, `ALL_BACKENDS_UNAVAILABLE`);
- `OutboundPrivacyPolicy` determinista que prohíbe el envío de información `RESTRICTED` y `PRIVATE` hacia Cloud / Internet o nodos LAN no confiables;
- `SecretResolver` seguro para API keys desde variables de entorno o archivos `0600`, con enmascaramiento total en logs y reportes;
- `BudgetPolicy` circuit breaker consultando la tabla `ai_usage` en SQLite para frenar cargos cloud automáticamente ante excesos diarios o mensuales;
- `AiContextBuilder` produciendo prompts mínimos acotados en caracteres y tokens, con filtrado de privacidad social y outbound;
- Cliente HTTP genérico OpenAI-compatible `GenericOpenAiBackend` con Python stdlib (`urllib.request`), con timeouts estrictos y parseo seguro;
- Backends `LocalAiBackend`, `LanBrainAiBackend` y `CloudAiBackend`;
- `AiOrchestrator` ejecutando la secuencia de fallback con degradación limpia y registro de telemetría en SQLite;
- `ConversationCoordinator` unificando Transcript STT -> Context -> Router -> Orchestrator -> TTS speak();
- Subsistema de Hardware Multiplataforma (`src/ailen/hardware/`): `LinuxHardwareAdapter`, `WindowsHardwareAdapter`, `FakeHardwareAdapter` y `HardwareDetector` produciendo `HardwareCapabilityReport` sin inventar capacidades sintéticas;
- `ModelCatalog` declarativo e inmutable (`src/ailen/models/catalog.py`) con soporte para `ModelPurpose` (`SANITY`, `BALANCED`, `QUALITY`), alias de runtime y modelos GGUF 2026 verificados con Git LFS (`qwen3.5-0.8b-q4_0`, `qwen3.5-0.8b-q8_0`);
- `ModelPlanner` adaptativo con márgenes de seguridad (60% RAM, 80% VRAM), comprobación de disco libre y CPU flags en GPU offload;
- `ModelStore` y `ModelDownloader` endurecidos contra path traversal, fail-closed con HTTPS forzado y renombre atómico;
- `RuntimeModelInventory` consultando modelos cargados en Ollama (`/api/tags`, `/v1/models`) y mapeando nombres/alias explícitos;
- `ManagedLlamaRuntime` gestionando el ciclo de vida de procesos `llama-server` / `llama serve` propios de AILEN con loopback estricto `127.0.0.1` y ownership de procesos respetado;
- `LabComponentFactory` (`src/ailen/runtime/factory.py`) con regla estricta "No Silent Fakes" (los fakes sólo se activan con `--simulate`);
- `LabRunner` (`src/ailen/runtime/runner.py`) con cableado end-to-end de hardware real (Face GUI Tkinter, Visión OpenCV, Audio ALSA, Vosk/Whisper STT, Piper TTS, AI Router), single-flight interaction lock y telemetría de sesión `LabSessionMetrics`;
- `LabDoctor` (`src/ailen/runtime/doctor.py`) con diagnósticos de solo lectura, remediaciones explícitas y salida `--json`;
- Comandos CLI operativos: `ailen lab inspect`, `ailen lab start [--simulate] [--fullscreen]`, `ailen lab doctor [--json]`, `ailen lab prepare-ai [--yes] [--start-runtime]`, `ailen lab benchmark`, `ailen models list`, `ailen models plan [--purpose]`, `ailen models fetch`, `ailen models verify`;
- Suite auditada en R3B.2: 324 tests pasando; `ruff`, `mypy` en 100 archivos fuente, `git diff --check` y build del wheel validados en verde.

## Qué NO existe todavía

- backend gráfico de producción nativo DRM/KMS para appliance sin X11 (actualmente POC Tkinter + Headless);
- servidor LAN Brain dedicado/discovery automático (existe el backend cliente LAN, no el servicio de fleet/brain final);
- updater;
- benchmarks físicos en hardware objetivo (Banghó Zero G05 / SF20BA).

## Hardware objetivo inmediato

### Prototipo

Banghó Zero G05:

- 8 GB RAM;
- M.2 500 GB;
- pantalla/cámara/audio integrados disponibles para el prototipo.

### Laboratorio

Linux Mint y Windows 11 se tratarán como **Lab Mode**: AILEN se levanta sin convertir el equipo en appliance ni cambiar login/suspensión/arranque. Allí se probarán rostro, logs, cámara, micrófono, STT/TTS, diagnóstico, selección/descarga de LLM y fluidez. La estrategia está documentada en `docs/deployment/LAB_AND_APPLIANCE_MODES.md`.

### Próximos objetivos

1. SF20BA 8 GB;
2. SF20BA 4 GB;
3. equipos 2 GB en modo Satellite/Cloud;
4. placas con pantalla rota usando monitor externo o modo sin pantalla.

## Próxima decisión técnica

Cerrar `ADR-006` o usarlo explícitamente como baseline provisional antes de integrar dependencias que condicionen el producto. Debe resolver mediante POC/benchmark:

- lenguaje/core;
- framework web;
- backend gráfico del rostro;
- STT/TTS baseline;
- persistencia;
- cómo encapsular proveedores LLM.

La base Foundation/Core/Web, Face/Vision, Audio/VAD/STT/TTS y R3A AI Router ya están integrados. Antes de profundizar Memory/Personality, el siguiente trabajo prepara el runtime de laboratorio y la selección automática de modelos locales.

## Próximo milestone

`R3C` queda implementado y auditado en su boundary actual. Próximo foco: medir STT real sobre frases G600 y comparar Vosk con Whisper.cpp cuando el operador autorice/instale sus assets; en paralelo falta backend musical físico y proveedor WebSearch real.

Trabajo inmediato definido en `TASKS.md` y `docs/operations/AGENT_HANDOFF.md`.

El repositorio Git local está inicializado en `main` y conectado a `git@github.com:vicktorgabriel/ailen.git`. El baseline auditado previo a R3B.4 es `2c2f6c3`. No se hace push sin autorización explícita.

## Riesgos conocidos

- latencia y consumo real en SF20BA aún desconocidos;
- compatibilidad gráfica sin X/Wayland aún no validada;
- STT/TTS óptimos por perfil aún no medidos;
- costo cloud estimado pero aún no medido con tráfico real;
- nombre `AILEN` fijado para proyecto/plataforma; queda pendiente sólo la verificación marcaria/legal antes de comercialización formal;
- soporte de equipos de 2 GB sujeto a pruebas reales.

## Actualización física R3B.3 — 2026-08-22

- `AUDIO CONVERSATION PASS` confirmado en Asrock/Linux Mint con G600 USB, sin simulación.
- Pipeline validado: micrófono -> VAD -> Vosk -> Router -> Ollama `qwen3.5:9b` -> Piper -> auricular.
- Mint Lab usa routing `pipewire` para evitar exclusión `arecord`/`aplay` sobre el mismo hardware USB.
- Ollama local usa backend nativo `/api/chat`, `think=false` y keep-alive de laboratorio para reducir cold-start; la identidad sigue viviendo en Core.
- Modo voz normaliza Markdown/URLs/símbolos antes de Piper y acota respuestas; defaults LAB: 500 ms de silencio final y 96 tokens máximos.
- Suite posterior a la validación: 349 tests; Ruff, mypy sobre 109 source files y diff-check verdes.
- Cámara YuNet y Face GUI Tkinter ya están disponibles en Lab; queda mejorar robustez STT y repetir Vision con una cámara mejor cuando esté disponible.

## Decisión adaptativa posterior al AUDIO CONVERSATION PASS — 2026-08-22

- La RTX 3060 de Asrock es sólo laboratorio; AILEN no requiere GPU.
- Se adopta ADR-010: inferencia adaptativa por hardware y tools controladas por Core.
- Perfiles objetivo: RULE_ONLY/SATELLITE, FAST, BALANCED y QUALITY; un modelo estable por nodo/sesión, sin cambiarlo por consulta.
- Acciones básicas (hora, timer, volumen, música, notas, status) deben ser deterministas; el LLM sólo interpreta cuando es necesario.
- Internet se implementará como `web_search`/`web_fetch` controlados, nunca como acceso irrestricto del LLM.
- Candidato FAST prioritario para benchmark: Llama 3.2 3B; alternativas Gemma 3 4B y Qwen3.5 4B con thinking desactivado.
- Próximo bloque: R3B.4 Adaptive Runtime + Voice Latency; luego R3C Product Behaviors + Controlled Tools + Web.
## Auditoría R3B.4 — 2026-08-22

- Se corrigió el benchmark para usar `/api/chat` nativo de Ollama; el shim OpenAI no se usa para `think=false`.
- `FIRST(ms)` es primer turno observado, no cold start; `TOK/S` sólo se informa con `eval_count/eval_duration` reales del runtime.
- Se eliminaron aliases peligrosos entre modelos distintos y se bloquea cualquier upshift de perfil por encima del hardware medido.
- El planner prefiere el menor footprint entre candidatos que ya satisfacen propósito/perfil.
- El backend OpenAI-compatible genérico no expone `reasoning_content` ni recibe controles específicos de Ollama.
- `RecommendedDeployment` reutiliza `HardwareDetector`; modelo y costo externo permanecen desconocidos hasta resolución/configuración real.

## Validación física Vision — 2026-08-23

- Webcam reciclada de notebook convertida a USB detectada como `HD Webcam`; stream usable `/dev/video1`.
- OpenCV 4.14.0 + Haar frontal/profile fallback; `/dev/video1` auto-seleccionado si `/dev/video0` no existe.
- `ailen demo vision` confirmó presencia y gaze variable; `lab start --headless` registró 211 observaciones y 2 transiciones reales en 12.34 s.
- Estado: `YUNET FACE DETECTION PASS` con la webcam reciclada actual. Tkinter/Face GUI disponibles. Haar queda experimental; YuNet es el detector preferido del Lab para rostro/posición, con limitación de estabilidad en baja luz/movimiento.

- YuNet 30 s controlado: tramo inicial sin persona limpio, rostro presente con confidence ~0.92-0.95 y gaze variable. PASS para face detection; objetos/escena siguen fuera de capacidad.

## Validación física Benchmarks — 2026-08-23

- `ailen lab benchmark-vision` (CPU, Ryzen 5 5500, 640x480, 5 FPS):
  - YuNet: 60/60 detecciones con rostro presente; latencia avg ~49 ms, p50 ~51 ms, p95 ~91 ms, max ~159 ms; confianza avg/min ~0.91/0.89; gaze x [+0.74,+0.85], y [-0.24,-0.22]. Aceptable a 5 FPS en CPU puro.
  - Haar (experimental): 40/40 con rostro presente pero avg ~67 ms con picos >500 ms y sin confianza calibrada.
  - Reportes JSON en `runtime/lab/vision_benchmarks/`; fases etiquetadas por el operador (`--phase`), sin inferencia de falsos positivos automática.
- `ailen lab benchmark-stt`: utterance generada con Piper ("Detecto un rostro frente a la cámara."), mismo WAV por motor:
  - Vosk small-es 0.42: OK, latencia ~407 ms, WER 0.143 (transcribió "detectó" en vez de "detecto"). Ejemplo del problema de calidad de Vosk.
  - whisper.cpp: `NOT_INSTALLED` (binario y modelo ggml ausentes); sin descarga automática.
- Limitación conocida web_fetch: validación DNS anti-SSRF es pre-conexión; DNS rebinding sofisticado requiere transporte con IP fijada (pendiente, documentado en WEB_SEARCH_BOUNDARY.md).

## Mejora de comprensión de voz — 2026-08-23

- Sesión física auditada: 24 utterances; Vosk aceptó 22, pero el problema principal fue el resolver demasiado literal.
- Fast path ampliado para ASR imperfecto (`hora es`, `notas tengo`, `nota ...`, variaciones de `más/menos volumen`).
- Nuevo fallback semántico local restringido: Qwen puede interpretar intención y proponer una tool local permitida, pero Core valida esquema/permisos y ejecuta. Network/destructive quedan fuera de este parser.
- Consultas contextuales de notas ya pueden recuperar contenido por tokens (`qué tengo que comprar mañana` -> `comprar estaño mañana`).
- Fragmentos vagos de una sola palabra se repreguntan para evitar que el LLM complete desde contexto viejo.
- Contexto Vision deja de ser saliente en cada respuesta; no debe repetirse la presencia salvo relevancia.
- ClockTool usa hora local del sistema, no UTC.
- Baseline de cierre: 487 tests; Ruff/mypy/diff-check verdes.
- Siguiente validación física: repetir la conversación de voz y medir cuántos turnos terminan en reprompt, tool determinista, semantic-tool y chat real. STT Vosk sigue siendo una limitación independiente y debe compararse con Whisper.cpp usando WER real G600.

## Comprensión natural + cámara NC250 — 2026-08-23

- Auditoría del historial físico confirmó que Notes sí persistía `comprar estaño mañana`; los fallos estaban en resolución de intención/contexto y en respuestas inventadas por el LLM general.
- IntentResolver acepta variantes naturales/ASR de hora y notas; follow-ups recientes de notas se resuelven localmente antes del LLM.
- Fragmentos ambiguos de dominio piden aclaración específica en vez de ejecutar o inventar continuidad.
- SemanticToolIntentResolver reduce la allowlist según dominio y usa timeout configurable.
- Lab separa `qwen2.5-coder:3b` como `intent_model` opcional del conversacional `qwen3.5:9b`; nunca descarga el modelo y vuelve al backend principal si no está instalado.
- Validación actual: 491 tests; Ruff limpio; mypy limpio en 129 archivos; diff-check limpio.
- TP-Link NC250 descubierta por Bonjour como `NC250-162889.local` / `192.168.1.157`. Panel HTTP local en 80; RTSP autenticado en 554 `/h264_hd.sdp` verificado con H.264 1280×720 + audio mono 8 kHz. Credenciales no se persisten en configuración/docs.

### Ajustes posteriores de inteligencia y NC250 — 2026-08-24

- Se corrigió un falso positivo del parser semántico: los hints ahora se comparan como términos léxicos completos, evitando que `dia` coincida dentro de palabras como `inmediato` y dispare herramientas sin intención real.
- Preguntas de capacidades (`qué podés hacer`, equivalentes) se responden desde el `ToolRegistry` y estado real de Core, sin permitir que el LLM invente funciones no instaladas.
- El contexto de memoria aclara que historial/memorias entregados por Core sí son memoria disponible, pero instrucciones del sistema, metadatos y sensores no deben narrarse como conversación previa.
- Se amplió el filtrado de cierres de voz genéricos para reducir repetición mecánica.
- Reproducción end-to-end de los fallos físicos previos ahora resuelve `hora es`, `ahora es`, creación/listado/búsqueda de notas y follow-ups de compra por tool local en ~9-22 ms.
- NC250 validada también como fuente de micrófono: RTSP expone audio PCMU mono 8 kHz y ffmpeg lo remuestreó a 16 kHz con señal física no nula. La integración como `AudioInputBackend` de AILEN sigue pendiente; por ahora el audio principal continúa por PipeWire/G600.
- `runtime/lab/ailen-lab.toml` quedó preparado para preferir la NC250 por RTSP con contraseña obtenida sólo desde `AILEN_CAMERA_PASSWORD`; el preflight y `lab start --headless` quedan READY con `rtsp://192.168.1.157:554/h264_hd.sdp` sin exponer credenciales.
- La NC250 continúa en `daynightmode=2` (Día). El firmware expone Auto=1, Día=2, Noche=3; la activación física de IR nocturno queda pendiente de pasar manualmente a Auto/Noche y repetir detección YuNet.
- Validación posterior: 501 tests; Ruff limpio; mypy limpio en 129 archivos; `git diff --check` limpio.
