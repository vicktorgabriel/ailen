# Arquitectura de Herramientas Controladas — AILEN

**Fecha:** 2026-08-23  
**Hito:** R3C Product Behaviors + Controlled Tools + Web  
**Estado:** Integrado / Baseline  
**Referencia:** ADR-010, `MODULE_CONTRACTS.md` sección 15

---

## 1. Principio Fundamental

En AILEN, **el LLM nunca ejecuta acciones directamente ni recibe acceso irrestricto al sistema operativo o la red**.

Toda acción física o local (hora, temporizadores, volumen, música, notas, estado del sistema) se ejecuta a través de herramientas fuertemente tipadas y controladas por el Core mediante un registro de allowlist (`ToolRegistry`) y un ejecutor con validación estricta de políticas (`ToolExecutor`).

```text
[Voz / Texto]
     │
     ▼
[IntentResolver] ── (Determinista / Fast-path) ──┐
     │                                            │
     ▼ (Chat conceptual)                          ▼ (Acción simple)
[AI ContextBuilder]                          [ToolExecutor]
     │                                            ├── Validación de registro
     ▼                                            ├── Validación de schema de argumentos
[RuleBasedRouter]                                 ├── Validación de SocialMode
     │                                            ├── Validación de PrivacyLevel
     ▼                                            ├── Timeout estricto
[AiOrchestrator]                                  └── Publicación en EventBus / SQLite
     │                                            │
     │◄─── (Resultados estructurados si web) ─────┘
     ▼
[TTS / SpeechOutput]
```

---

## 2. Componentes Principales

### 2.1 ToolRegistry (`src/ailen/tools/registry.py`)
Mantiene un catálogo en memoria de herramientas registradas. Prohíbe la importación dinámica arbitraria de módulos. Cada herramienta implementa el protocolo `Tool`:
- `name`: Identificador único y canónico.
- `description`: Resumen legible del propósito.
- `schema`: Declaración de tipos, rangos y valores por defecto de argumentos.
- `allowed_modes`: Conjunto de modos sociales (`SocialMode`) permitidos.
- `privacy_level`: Clasificación de privacidad (`PrivacyLevel`).
- `requires_network`: Indicador booleano de acceso a red externa.
- `destructive`: Indicador booleano de mutaciones irreversibles.
- `timeout_seconds`: Límite máximo de tiempo de ejecución.

### 2.2 ToolExecutor (`src/ailen/tools/executor.py`)
Encapsula la ejecución de herramientas aplicando barreras de seguridad en capas:
1. **Verificación de Registro**: Rechaza herramientas no registradas con código `TOOL_NOT_FOUND`.
2. **Control de Modo Social**: Deniega herramientas en modos no autorizados (ej. notas privadas en `PUBLIC`/`SHOP` o herramientas en `SLEEP`) con código `TOOL_DENIED`.
3. **Control de Privacidad**: Bloquea herramientas `PRIVATE` cuando el contexto es público.
4. **Gate de Red**: Deniega herramientas `requires_network=true` (`NETWORK_UNAVAILABLE`) cuando `ToolContext.internet_available=false`.
5. **Gate de Destructividad**: Herramientas `destructive=true` requieren confirmación explícita y están prohibidas en `SHOP`/`PUBLIC`; además R3C las bloquea con `DESTRUCTIVE_EXECUTION_UNSUPPORTED` incluso confirmadas hasta disponer de un executor aislado/cancelable. Los timeouts por hilo de tools no destructivas devuelven control al Core, pero no son hard-cancel de una operación ya iniciada.
6. **Validación de Argumentos**: Valida tipos, mínimos, máximos, longitudes y enums con `validate_args()`.
7. **Aislamiento Temporal (Timeout)**: Ejecuta mediante worker pool dedicado; ante timeout devuelve control inmediatamente al llamador (shutdown sin esperar el hilo) y emite `TOOL_TIMEOUT`.
8. **Auditoría y Eventos**: Emite `TOOL_REQUESTED` y `TOOL_COMPLETED` en el `EventBus` y registra un log sanitizado en la tabla `tool_events` de SQLite.

### 2.3 IntentResolver (`src/ailen/tools/intent_resolver.py`)
Mecanismo determinista basado en reglas para extraer intenciones y argumentos estructurados a partir de texto de usuario.

**Falsos positivos son peores que falsos negativos:**
Preguntas explicativas o conceptuales como:
- *"¿Cuál es el volumen de un cilindro?"*
- *"¿Qué batería usa esta notebook?"*
- *"Explicame qué es un temporizador"*
son filtradas explícitamente y canalizadas hacia el flujo conversacional del LLM sin ejecutar herramientas locales por error.

---

## 3. Catálogo de Herramientas Iniciales (R3C)

| Herramienta | Modos Permitidos | Privacidad | Red | Timeout | Descripción |
|---|---|---|---|---|---|
| `clock` | Todos | PUBLIC | No | 2.0s | Hora y fecha actual formateada. |
| `timer` | HOME, WORKSHOP, PRIVATE | PRIVATE | No | 2.0s | Temporizadores en memoria (`create`, `list`, `cancel`). |
| `volume` | Todos | PUBLIC | No | 2.0s | Control seguro de audio (`wpctl`/`pactl`/`amixer`). |
| `music` | HOME, WORKSHOP, PRIVATE | PUBLIC | No | 2.0s | Máquina de estados de reproducción local simulada. |
| `notes` | HOME, WORKSHOP, PRIVATE | PRIVATE | No | 2.0s | Persistencia de notas en SQLite con queries parametrizadas. |
| `system_status` | HOME, WORKSHOP, PRIVATE | RESTRICTED | No | 3.0s | Diagnóstico sanitizado de CPU, RAM, GPU y audio. |
| `web_search` | Todos | PUBLIC | Sí | 6.0s | Búsqueda web estructurada desacoplada de proveedor. |
| `web_fetch` | HOME, WORKSHOP, PRIVATE | PUBLIC | Sí | 6.0s | Extracción web segura con protección anti-SSRF. |

---

## 4. Política de Audio y Volumen Seguro

En Linux Mint y Debian appliance:
- Queda terminantemente prohibido el uso de `shell=True`.
- La herramienta `volume` detecta binarios del sistema en orden: `wpctl` (PipeWire), `pactl` (PulseAudio), `amixer` (ALSA).
- Si no existe ningún backend disponible o el comando falla, la herramienta devuelve `status_code="UNAVAILABLE"` y `success=False`. **Nunca se inventa un éxito sintético.**


### Política de red

La autorización de red para tools se controla mediante `[network].outbound_web_enabled` y es independiente de que exista o no un backend cloud de IA. Un LLM local puede usar una tool web configurada sin habilitar cloud, y habilitar cloud no concede red automáticamente a las tools.

### Música

`MusicTool` define el contrato y routing, pero el backend por defecto es fail-closed (`UNAVAILABLE`). `LocalMusicService` es un backend in-memory de pruebas/estado y no debe confundirse con reproducción audible.
