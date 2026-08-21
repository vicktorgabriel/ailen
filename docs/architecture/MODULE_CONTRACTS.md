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
```

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
cloud_allowed
budget_state
latency_preference
```

### `RoutePlan`

```text
primary_backend
fallback_backends[]
reason_code
context_budget
request_timeout
```

Los `reason_code` deben ser registrables para entender por qué una consulta fue a cloud.

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
```

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
```

`SpeechOutput` puede ser stream o referencia temporal, según implementación.

## 13. Audio device service

Responsabilidades:

- enumerar captura/reproducción;
- seleccionar dispositivo;
- niveles;
- reproducir voz/música;
- ducking;
- evitar feedback en la medida posible.

No decide qué texto hablar.

## 14. Face

```text
FaceController.set_state(state)
FaceController.set_gaze(x, y)
FaceController.set_speech_level(level)
FaceController.set_expression(expression)
FaceController.sleep()
FaceController.wake()
```

Face no accede a SQLite, AI ni web.

## 15. Tool

Cada tool implementa:

```text
name
schema
permissions
execute(validated_args, ToolContext) -> ToolResult
```

### `ToolResult`

```text
success
summary
data
error_code?
```

Prohibido exponer shell general como tool.

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
UpdateService
```

## 17. Updater

```text
check() -> UpdateInfo
prepare(version) -> PreparedRelease
activate(prepared_release) -> ActivationResult
rollback() -> RollbackResult
```

Updater no puede borrar `/var/lib/ailen` ni sobrescribir config persistente.

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
