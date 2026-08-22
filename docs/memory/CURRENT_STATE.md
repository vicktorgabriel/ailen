# Estado actual — AILEN

**Fecha:** 2026-08-22
**Versión:** `0.1.0-dev.0`  
**Fase:** R3B.4 Adaptive Runtime + Voice Latency auditado e integrado. Hardware real selecciona `InferenceProfile` (`RULE_ONLY`, `FAST`, `BALANCED`, `QUALITY`) y alimenta `ModelPlanner`; Ollama usa backend nativo con `think=false` y residencia por perfil. Benchmark corregido: `qwen3.5:9b` ~1.76 s promedio en batería larga / ~42.6 tok/s y `qwen2.5-coder:3b` ~0.57 s / ~127 tok/s; los turnos físicos cortos del 9B siguen típicamente ~0.55–0.85 s. Piper usa API Python por chunks, cachea/precalienta la voz y mantiene fallback CLI. TTFAR está conectado al primer PCM enviado a playback; STT dudoso repregunta antes del LLM. Fast-path sólo prepara clasificación para R3C, todavía no ejecuta tools. Audio conversation PASS real con G600; cámara/Face siguen pendientes.

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
- `VisionDebouncer` temporal para presencia física basado en `presence_debounce_seconds`;
- Backend de cámara POC `OpenCvVisionBackend` con Haar cascade a 5 FPS / 320px y degradación limpia;
- Formato canónico de audio: PCM 16-bit signed LE, mono, 16000 Hz (`src/ailen/audio/pcm.py`) con RMS matemático puro;
- VAD en Python puro (`EnergyVad`) con umbral configurable y hangover; benchmark lógico DEV documentado sin extrapolar porcentaje de CPU a hardware objetivo;
- `UtteranceCollector` con defaults actuales de pre-roll 200 ms, mínimo de habla 250 ms, silencio final 700 ms y corte máximo 15 s;
- Compuerta Half-Duplex `AudioTurnGate` con cooldown acústico para prevenir auto-transcripción y feedback de parlantes;
- Backends I/O reales ALSA (`AlsaAudioInputBackend`, `AlsaAudioOutputBackend`, `AlsaDeviceEnumerator`) y fakes para CI/tests;
- Backend STT local offline `VoskSttBackend` (extra `[stt-vosk]`) y alternativa `WhisperCppSttBackend` (`whisper-cli` actual, nombres legacy best-effort); no inventan confidence cuando el motor no lo provee;
- Backend TTS local offline `PiperTtsBackend` compatible con el CLI actual: WAV temporal, extracción de PCM/sample-rate/canales reales y control de velocidad/volumen;
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

`R3C — Product Behaviors + Controlled Tools + Web`: implementar acciones locales allowlisted (hora, timer, volumen, música, notas, status) y acceso web mediante tools controladas por Core. La cámara/Face física de R3B.3 permanece como validación pendiente paralela cuando haya cámara disponible; no bloquea el avance del pipeline de voz ya validado.

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
- Falta para cerrar validación física global: cámara + Vision/Face. Después corresponde comparar perfil rápido 4B frente a 9B y mejorar robustez STT.

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
