# Contratos de módulos — AILEN

> Contratos conceptuales para permitir trabajo paralelo sin acoplar implementaciones. Los nombres concretos de clases pueden cambiar, pero las responsabilidades no deben mezclarse sin ADR.

## 1. Principio

Los módulos intercambian modelos internos estables. Ningún adaptador externo debe filtrar directamente objetos de una librería, proveedor cloud o framework hacia Core, Face o Web.

## 2. Identidad y sesión

### `AssistantIdentity`

Campos conceptuales:

```text
identity_id
name
created_at
personality_seed
active_personality_version
```

No contiene credenciales cloud ni permisos de sistema.

### `ConversationSession`

```text
session_id
started_at
ended_at?
mode
participant_hint?
source_node_id
```

## 3. Estado runtime

### `RuntimeState`

```text
version
node_id
profile
assistant_state
uptime_seconds
internet_status
lan_brain_status
cloud_status
camera_status
microphone_status
speaker_status
memory_status
last_error_code?
updated_at
```

Debe ser seguro para mostrar por web sin redacción adicional de secretos.

## 4. Eventos del Core

Modelo conceptual:

```text
Event(
    event_id,
    type,
    timestamp,
    payload,
    source,
    correlation_id?
)
```

Eventos importantes:

- `PRESENCE_DETECTED`
- `PRESENCE_LOST`
- `WAKE_DETECTED`
- `SPEECH_CAPTURED`
- `TRANSCRIPT_READY`
- `INTENT_RESOLVED`
- `TOOL_REQUESTED`
- `TOOL_COMPLETED`
- `INFERENCE_REQUESTED`
- `INFERENCE_COMPLETED`
- `SPEECH_STARTED`
- `SPEECH_FINISHED`
- `STATE_CHANGED`
- `ERROR`

Los eventos no deben contener audio crudo o imágenes completas salvo una referencia explícita administrada por storage.

## 5. AI backend

Interfaz conceptual:

```text
AiBackend.health() -> BackendHealth
AiBackend.capabilities() -> BackendCapabilities
AiBackend.generate(AiRequest) -> AiResponse
StreamingAiBackend.generate_stream(AiRequest, on_text_delta) -> AiResponse
```

El callback incremental puede devolver `false` para pedir cancelación. Un
adapter sólo declara `supports_streaming` si entrega deltas antes de completar la
respuesta. Ollama, llama.cpp administrado, LAN y externos permanecen detrás de
este mismo límite; Core no inicia procesos ni conoce formatos GGUF.

### `AiRequest`

```text
request_id
system_context
messages
retrieved_memory
mode
allowed_tools
max_output_tokens
timeout_seconds
privacy_level
metadata
```

### `AiResponse`

```text
text
tool_calls[]
finish_reason
usage
latency_ms
provider
model
```

### `AiUsage`

```text
input_tokens?
output_tokens?
estimated_cost?
currency?
```

El Router es quien decide el backend. Core no selecciona nombres de modelos directamente.

## 6. AI Router

Interfaz conceptual:

```text
route(RouteRequest) -> RoutePlan
```

### `RouteRequest`

```text
intent
complexity
profile
privacy_level
internet_available
lan_brain_available
local_backend_available
external_allowed
allow_sanitized_external_prompts
remote_backends[]
budget_state
latency_preference
preferred_backend
backend_priorities
realtime_eligible_backends
acoustic_confidence?
utterance_interrupted
utterance_truncated
```

### `RoutePlan`

```text
primary_backend
fallback_backends[]
reason_code
context_budget
request_timeout
```

Los `reason_code` deben ser registrables para entender por qué una consulta fue
a local, LAN o a un `remote:<provider_id>` concreto.

### `ProvisioningPlan`

La instalación consume un único plan declarativo producido por hardware,
catálogo y evidencia target-specific:

```text
hardware_class / hardware_tier / topology
runtime / runtime_reason
execution_device
primary_model_id? / fallback_model_id? / candidate_model_ids[]
context_tokens / gpu_layers
reserved_system_ram_mb
estimated_model_ram_mb / estimated_model_vram_mb
download_size_bytes / artifact_url / artifact_sha256 / license_name
qualification_status / auto_download_allowed
required_assets[] / consent_actions[] / alternatives[] / reason_codes[]
```

Un consumidor no puede ejecutar `consent_actions` si
`auto_download_allowed=false`. Un override manual no cambia la calificación ni
la seguridad de memoria. El plan no contiene secretos ni inicia descargas.

La evidencia de instalación se indexa, como mínimo, por
`(hardware_class, model_id, runtime)`. Compatibilidad declarada por un descriptor
no califica un runtime: el plan sólo puede seleccionar uno con registro
`qualified` para esa clase y modelo. `execution_device` y `gpu_layers` también
proceden de la ejecución medida; un registro anterior que no los declara se
interpreta conservadoramente como CPU con cero capas GPU. El contrato actual
sólo admite CPU/`0` o CUDA/`all`; offload parcial queda bloqueado hasta contar
con implementación y evidencia específicas.

La selección activada fija `ai.local.runtime=ollama|llama_cpp`. El factory no
puede usar otro runtime sano como sustituto y sólo admite un modelo automático
si su descriptor ya llega `qualified`. `auto` queda reservado a overrides Lab
explícitos, no a transferir evidencia entre runtimes.

## 7. Memory service

Interfaz conceptual:

```text
start_session(...)
end_session(...)
store_message(...)
remember(...)
search_memories(...)
get_recent_context(...)
store_business_fact(...)
store_personality_event(...)
store_ai_usage(...)
store_tool_event(...)
```

Los retornos son modelos de dominio, no filas SQLite.

## 8. Personality service

```text
get_state(identity_id) -> PersonalityState
observe(event) -> PersonalityDelta?
apply_delta(delta)
freeze()
unfreeze()
reset(seed?)
```

### Restricción

`PersonalityService` no puede modificar permisos, tools, privacidad, configuración de red ni presupuesto cloud.

## 9. Social engine

```text
evaluate(SocialContext) -> SocialAction[]
```

### `SocialContext`

```text
mode
presence_state
conversation_active
last_greeting_at
people_count_estimate
sleep_state
user_preference
```

### `SocialAction`

Ejemplos:

```text
LOOK_AT
GREET
WAKE
SLEEP
STAY_SILENT
CHANGE_EXPRESSION
```

## 10. Vision

Interfaz conceptual:

```text
VisionBackend.start()
VisionBackend.stop()
VisionBackend.health()
VisionBackend.get_latest_presence() -> PresenceObservation
```

`VisionHealth` diferencia gestión/configuración de cámara de transporte y análisis:

```text
status
detail
stream_has_frames
frames_processed
frame_read_failures
last_valid_frame_at?
capture_thread_alive?
last_inference_ms?
```

`HEALTHY` exige frames válidos recientes; abrir un socket RTSP o tener configuración
no alcanza. El control HTTP específico de una cámara vive detrás de
`CameraControl` y se ejecuta antes de abrir el stream cuando hay un modo inicial.

### `PresenceObservation`

```text
present
faces_count
primary_x_normalized?
primary_y_normalized?
confidence?
timestamp
```

Face recibe observaciones normalizadas, no frames de cámara.

## 11. STT

```text
SttBackend.health()
SttBackend.transcribe(AudioSegment) -> Transcript
```

### `Transcript`

```text
text
language
confidence?
latency_ms
engine
audio_duration_ms
utterance_id?
interrupted
truncated
alternatives[]
```

`confidence` es evidencia del motor STT y puede ser desconocida. No se reemplaza
por confianza de intención. Cada alternativa conserva su propio texto/confianza.
`interrupted` indica que el turno nació de un barge-in; `truncated` indica que la
captura finalizó por el límite máximo y puede faltar texto. Antes de ejecutar una
tool con efecto, Core exige turno no truncado, confianza
acústica configurada e intención inequívoca; si no, solicita repetición.

`SttQualityEvaluator` aplica umbrales configurables y ordenados:

```text
[0, noise_max)              -> noise
[noise_max, conversation)   -> doubtful / repregunta
[conversation, action)      -> conversation
[action, 1]                 -> action
confidence=None             -> unknown
```

Una frase de varias palabras no evita la repregunta si la confianza acústica es
extremadamente baja. Sólo se selecciona una alternativa cuando el motor la
entregó realmente y supera el piso conversacional.

## 12. TTS

```text
TtsBackend.health()
TtsBackend.synthesize(SpeechRequest) -> SpeechOutput
```

### `SpeechRequest`

```text
text
voice_id
rate?
volume?
emotion?
expressiveness?
```

`SpeechOutput` puede ser stream o referencia temporal, según implementación.
Los backends incrementales pueden exponer `synthesize_chunks()`; cada latencia de
chunk debe medirse sin confundir síntesis con reproducción.

## 13. Audio device service

Responsabilidades:

- enumerar captura/reproducción;
- seleccionar dispositivo;
- niveles;
- reproducir voz/música;
- ducking;
- evitar feedback en la medida posible.

No decide qué texto hablar.

Una fuente PipeWire explícita tiene ID `pipewire:<node>` y debe llegar como
target a `pw-record`. En cambio, `pipewire` sin sufijo delega la selección al
default nativo de PipeWire y no depende de `pactl`; nunca se inventa un target.
El backend expone `effective_device` para telemetría: el nombre exacto queda
disponible para targets explícitos y `pipewire` informa honestamente que usó el
default nativo. La cadena canónica conserva formato/duración S16LE:

```text
physical/virtual source
-> optional WebRTC noise suppression
-> capture_gain_db
-> noise-gated bounded smoothed AGC
-> limiter/clipping metrics
-> VAD -> STT
```

El AGC no incrementa ganancia cuando el RMS de entrada está por debajo de
`auto_gain_noise_gate_rms`: sostiene brevemente la ganancia de voz y luego la
reduce con el release configurado. La calibración de silencio propone ese gate
desde el p95 raw; mostrar la propuesta no la persiste. La telemetría observa
`mic_raw` antes de DSP, cada salida intermedia y `mic_clean` final, y conserva
sólo escalares. La calibración recibe frames sólo en memoria y persiste
únicamente fuente, RMS/peak por etapa, SNR aproximado, clipping, VAD y
WER/CER/confianza. Nunca persiste PCM. AGC/noise suppression no se declaran AEC.
Sin override, el harness selecciona un conjunto bounded de fuentes observables
(default, PipeWire físicas y Easy Effects Source), excluye monitores y deduplica;
`--device` conserva un único target exacto. El snapshot registra estado y
volumen observado, pero no escribe controles del sistema. La medición Web corta
es sólo piso/nivel acotado del input configurado, no sustituye la matriz guiada
de distancia/SNR/WER. La ganancia física sólo puede cambiarse sobre un control
de captura identificado, con readback y consentimiento explícito; nunca sobre
`Master` de salida.

```text
AudioOutputBackend.play(..., cancel_event?)
AudioOutputBackend.stop()
```

El token de cancelación evita iniciar un chunk cuyo turno ya fue interrumpido.
`stop()` debe poder finalizar la reproducción activa desde otro thread. El camino
normal de STT queda bloqueado durante TTS, pero el detector acotado de barge-in
sigue leyendo micrófono y conserva los frames del usuario.
Para TTS incremental, el coordinador puede sintetizar como máximo un chunk futuro
mientras reproduce el actual. La cancelación no espera esa síntesis: libera el
turno y descarta cualquier resultado tardío antes de playback.
El coordinador también acepta una secuencia incremental de `SpeechRequest` dentro
de un único turno/gate cancelable. Un segmentador del Core emite sólo frases
pronunciables; metadata facial, texto parcial de una respuesta fallida y chunks
posteriores al barge-in nunca se pronuncian.

El lifecycle usa IDs monotónicos por generación. Cancelar invalida resultados
posteriores y detiene playback; no promete cancelar una llamada ONNX ya activa.
El backend TTS se serializa cuando no declara concurrencia segura y el fin de su
drenaje obsoleto se informa aparte. `SPEECH_SYNTHESIS_DRAINED` se publica antes
de retirar el trabajo del contador de drains y antes de que otro turno entre al
backend serializado. Una generación vieja nunca puede restaurar estado
facial/gate ni reproducir sobre una nueva. Una respuesta assistant interrumpida
no se persiste como turno completo.

## 14. Face

```text
FaceController.set_state(state)
FaceController.set_gaze(x, y)
FaceController.set_speech_level(level)
FaceController.set_expression(expression, duration_seconds=5.0)
FaceController.available_expressions -> tuple[str, ...]
FaceController.sleep()
FaceController.wake()
FaceController.is_display_active() -> bool
```

Face no accede a SQLite, AI ni web.
Las expresiones externas pertenecen a una allowlist y son overlays transitorios;
los estados críticos (`SLEEP`, `ERROR`, `DEGRADED`) conservan prioridad.
`set_speech_level()` entrega una intensidad acotada, no una coordenada de boca
estática. Un overlay expresivo modifica ojos/cejas/forma base, pero no debe
congelar esa articulación. El renderer nunca recibe PCM ni depende de TTS/audio.

El backend FacePack normaliza el contrato hacia una C ABI:

```text
state       -> persistent state scheduler
expression  -> bounded pack sequence over the current state
gaze        -> pack-declared microaction; composable only when a compatible ROI exists
speech      -> independent pack speech sequence, full-frame or compatible mouth ROI
```

`SPEAKING` no es una emoción. Un pack con mouth ROI puede componerla sobre la
expresión; el pack H3 actual usa talk full-frame para evitar deformación y retoma
la expresión de Core al cesar speech. Los ids dinámicos,
frames, paths, anchors y archivos pertenecen al FacePack/engine; ningún LLM los
controla directamente. `available_expressions` proyecta la allowlist confiable
del renderer activo hacia el schema de `FaceExpressionTool` y la metadata
conversacional; los ids se normalizan a un vocabulario ASCII acotado. Por eso un
pack nuevo puede ampliar expresiones sin recompilar la librería ni mantener una
segunda lista del renderer en Core. El wrapper valida el pack bajo un root local
confiable y degrada a un `NullFaceController` headless si falta la librería/pack
o falla magic, ABI, offsets, límites, checksums o decode durante runtime. Nunca
selecciona `portrait` automáticamente. Los MP4 no forman parte de este contrato
runtime.

## 15. Tool

Cada tool implementa:

```text
name
schema
permissions
execute(validated_args, ToolContext) -> ToolResult
```

Una tool que participa del routing semántico puede declarar `intent_hints` y
`intent_guidance`. Sólo el texto actual abre el gate mediante hints; el historial
no lo abre. Core incluye únicamente la guía de las tools candidatas y siempre
valida la propuesta contra `schema` antes de ejecutar.

### `ToolResult`

```text
success
summary
data
error_code?
```

Prohibido exponer shell general como tool.

Para WebSearch, el request puede declarar `category=text|news` y frescura
`day|week|month`. Un resultado fechado expone `published_at`; Core conserva esa
metadata al proyectar evidencia al LLM. Una búsqueda sin resultados es éxito con
lista vacía, mientras timeout o fallo del proveedor permanecen errores explícitos.

## 16. Web admin

Web consume servicios de aplicación, nunca modifica SQLite o config cruda directamente desde handlers.

Áreas del contrato:

```text
AuthService
SettingsService
StatusService
BusinessKnowledgeService
PersonalityAdminService
MemoryAdminService
UpdateAdminService
```

`MemoryAdmin` proyecta `MemoryPage`/`MemoryItem` y permite listado paginado,
lectura por ID, alta/edición/borrado individual y exportación acotada. El
repositorio posee el SQL parametrizado; la Web sólo autentica, valida CSRF y
renderiza. El alcance default es PUBLIC; incluir PRIVATE/RESTRICTED en pantalla
/exportación requiere opt-in explícito del admin, independiente del modo social.
Guardar/borrar/exportar exige confirmación. No expone purga, paths, credenciales,
notas, recordatorios ni mensajes como si fueran recuerdos explícitos.

`DiagnosticsAdmin` entrega `DiagnosticsSnapshot`: salud del proceso actual,
checks de disponibilidad y escalares de la última sesión finalizada. GET no
arranca LabDoctor; `run_checks()` exige acción administrativa POST+CSRF y evita
concurrencia. El lector de reportes tiene root inyectado, tamaño/cantidad
acotados y rechazo de symlinks; sólo proyecta fecha y métricas numéricas finitas
allowlisted. `execution_mode=real` indica backends no simulados, no certificación
física. Reportes legacy/simulados nunca se promueven a medición real. No comparte
logs, paths, errores internos ni contenido conversacional.

`UpdateAdminService` proyecta sólo DTOs acotados. La Web no recibe URLs de
artefactos, hashes de confianza, paths locales ni primitivas de extracción,
procesos o servicios.

## 17. Updater

```text
snapshot() -> UpdateAdminSnapshot
check() -> UpdateCommandResult
plan(release_id) -> UpdateCommandResult(operation_id, approval_token)
start_download(release_id, approval_token) -> UpdateCommandResult
status(operation_id) -> OperationStatus
cancel(operation_id) -> UpdateCommandResult
activate(operation_id) -> UpdateCommandResult
rollback() -> UpdateCommandResult
```

El token de aprobación es efímero, de un solo uso y no se persiste. Un proceso
nuevo sólo reanuda una transferencia interrumpida después de volver a obtener y
verificar el manifiesto firmado y emitir una aprobación nueva.

El manifiesto JSON exacto se autentica con Ed25519 antes del parseo. El
manifiesto firmado declara SHA-256, tamaño comprimido/expandido, plataforma y
media type de cada artefacto. Downloader, CAS y extractor revalidan tamaño/hash
en sus respectivas fronteras. El journal persiste una máquina de estados
estricta y sólo admite un worker/activación por instancia.

`LocalUpdateService` es el orquestador no privilegiado. `ReleasePreparer` y
`ReleaseActivationBoundary` son contratos inyectados. En el Lab actual el
controller de activación es sólo una simulación en memoria y raíces temporales;
solicitar modo Appliance devuelve `UNAVAILABLE`. El futuro `ailen-updaterd`
implementará la frontera mínima privilegiada para switch de release y control de
servicio, sin exponer shell general a Core o Web.

Updater no puede borrar `/var/lib/ailen`, restaurar/downgradear automáticamente
la base, sobrescribir config persistente ni mutar paths elegidos por una request.
La activación exige compatibilidad forward/rollback declarada por schema, switch
atómico, probation de salud y retorno a la release anterior si el candidato
falla.

## 18. Device profile

Perfiles lógicos iniciales:

- `SATELLITE`
- `CLOUD`
- `HYBRID`
- `LOCAL`
- `LAN_BRAIN`

Un perfil habilita/cambia defaults; no debe llenar el código de `if model == SF20BA`.

La detección de hardware produce una recomendación. El administrador puede forzar un perfil compatible.

## 19. Errores

Errores internos deben usar códigos estables, por ejemplo:

```text
AI_TIMEOUT
AI_BUDGET_EXCEEDED
CLOUD_OFFLINE
LAN_BRAIN_OFFLINE
STT_UNAVAILABLE
TTS_UNAVAILABLE
CAMERA_UNAVAILABLE
AUDIO_DEVICE_MISSING
MEMORY_ERROR
CONFIG_INVALID
TOOL_DENIED
TOOL_TIMEOUT
```

La UI puede traducir esos códigos a mensajes humanos.

## 20. Logging

Toda operación relevante puede registrar:

```text
timestamp
level
component
event
correlation_id
latency_ms?
result?
```

No registrar:

- passwords;
- API keys;
- audio crudo;
- imágenes;
- prompts completos con memoria privada por defecto;
- contenido completo de conversaciones en logs operativos.

El historial conversacional pertenece a Memory, no al logger.
