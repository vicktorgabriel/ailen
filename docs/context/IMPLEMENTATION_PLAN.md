# Plan de implementación — AILEN

> Plan operativo para llevar el proyecto desde `0.1.0-dev.0` hasta el primer prototipo funcional. Este documento complementa `ROADMAP.md`: el roadmap define hitos; este archivo define el orden concreto de trabajo.

> **Estado 2026-08-30:** las fases A-H de este documento describen el camino histórico y su baseline ya está implementado. La ejecución inmediata vive en `TASKS.md` (R4/R5 + R5B FacePack) y `ROADMAP.md`; el siguiente bloque estructural no cerrado es Appliance Debian/Updater. No reconstruir Foundation/Core a partir de este plan.

## 1. Objetivo inmediato

Construir un prototipo end-to-end en la Banghó Zero G05 de 8 GB que pueda:

1. iniciar en Debian 13 minimal;
2. detectar y describir su hardware;
3. levantar AILEN Core;
4. exponer estado/health;
5. mostrar un rostro 2D simple;
6. capturar audio;
7. transcribir una frase;
8. generar una respuesta mediante un backend intercambiable;
9. reproducir TTS;
10. guardar la sesión en SQLite;
11. configurarse desde una UI web responsive;
12. continuar operando parcialmente sin Internet.

No se optimiza todavía para 4 GB/2 GB hasta tener este ciclo completo.

## 2. Regla de desarrollo

No desarrollar todos los subsistemas a la vez dentro de un único archivo o proceso monolítico sin contratos.

Sí se permite un monolito modular desplegado como pocos procesos/servicios.

Cada subsistema debe tener:

- interfaz clara;
- implementación baseline;
- fallback o error controlado;
- tests unitarios cuando sea posible;
- métricas mínimas;
- documentación de configuración.

## 3. Fase A — Bootstrap técnico

### A1. Estructura Python/stack base

Objetivo: crear el proyecto ejecutable sin comprometer todavía backends de audio/face/LLM.

Entregables esperados:

```text
pyproject.toml
src/ailen/
    __init__.py
    __main__.py
    app/
    core/
    domain/
    infrastructure/
    adapters/
    services/
    web/
    face/
    vision/
    audio/
    ai/
    memory/
    tools/
tests/
```

La estructura exacta puede ajustarse si el ADR técnico lo justifica.

Criterios de aceptación:

- `python -m ailen --help` funciona;
- import del paquete sin efectos laterales;
- versión se obtiene desde una fuente única;
- tests pueden ejecutarse sin cámara, micrófono ni GPU;
- ruff/formatter/type checking definidos si se adopta Python.

### A2. Configuración

Crear modelo de configuración con defaults seguros.

Secciones previstas:

- `node`;
- `profile`;
- `display`;
- `audio`;
- `vision`;
- `speech`;
- `ai`;
- `memory`;
- `personality`;
- `social`;
- `web`;
- `updates`;
- `logging`.

Config real local fuera de Git. Versionar sólo ejemplo/esquema.

Criterios:

- carga/validación determinista;
- error legible ante config inválida;
- secretos separables;
- migración futura contemplada mediante `schema_version`.

### A3. Runtime state y health

Definir estado mínimo observable:

```text
version
node_id
profile
pid
uptime
state
internet
lan_brain
cloud
memory
camera
microphone
speaker
last_error
```

Debe poder serializarse sin incluir secretos.

### A4. Hardware diagnostics

CLI inicial:

```text
ailen diagnose hardware
```

Detectar de forma best-effort:

- arquitectura;
- CPU;
- RAM total/disponible;
- almacenamiento;
- GPU si existe;
- displays;
- cámaras;
- dispositivos de captura/reproducción;
- red;
- Debian/kernel.

No asumir que ausencia de un dispositivo es fatal.

## 4. Fase B — Core y estado del personaje

### B1. Event loop / coordinator

El Core coordina eventos, no ejecuta operaciones bloqueantes en el hilo del rostro/UI.

Eventos iniciales sugeridos:

```text
PresenceDetected
PresenceLost
WakeWordDetected
SpeechCaptured
TranscriptReady
IntentResolved
ToolRequested
ToolCompleted
InferenceRequested
InferenceCompleted
SpeechStarted
SpeechFinished
SleepRequested
ErrorRaised
```

### B2. Estado del asistente

Máquina de estados baseline:

```text
BOOTING
  -> IDLE
      -> ATTENTION
      -> LISTENING
      -> THINKING
      -> TALKING
      -> IDLE
      -> SLEEP
```

Errores deben degradar componentes sin destruir el Core cuando sea posible.

### B3. Social Engine

Implementar antes que personalidad compleja:

- cooldown de saludo;
- modo social;
- iniciativa habilitada/deshabilitada;
- reglas `PUBLIC/PRIVATE`;
- evento de saludo por presencia;
- comportamiento silencioso cuando corresponde.

## 5. Fase C — Memoria baseline

### C1. SQLite

Esquema inicial sugerido:

- `schema_meta`;
- `sessions`;
- `messages`;
- `memories`;
- `business_facts`;
- `preferences`;
- `personality_state`;
- `personality_events`;
- `tool_events`;
- `ai_usage`;
- `system_events`.

Usar migraciones desde el primer esquema.

### C2. Recuperación

FTS5 para mensajes/memorias cuando esté disponible.

API conceptual:

```text
remember(...)
search_memories(query, scope, limit)
get_recent_context(session_id, limit)
store_message(...)
store_tool_event(...)
```

No enviar objetos SQLite directamente al LLM.

## 6. Fase D — AI Router

### D1. Contrato de backend

Todo proveedor debe implementar un contrato equivalente a:

```text
health()
capabilities()
generate(request) -> response
usage(response)
```

Backends previstos:

- deterministic/local intent;
- local LLM;
- LAN Brain;
- cloud provider.

### D2. Router v1

Decisión basada inicialmente en reglas claras, no en otro LLM pesado.

Entrada:

- intent;
- profile;
- privacy;
- online state;
- LAN state;
- cost policy;
- estimated complexity.

Salida:

- backend elegido;
- motivo;
- fallback order;
- max context;
- timeout.

### D3. Cloud

Implementar proveedor mediante interfaz genérica. No acoplar el Core a una marca/modelo específico.

Requisitos:

- timeout;
- retry limitado;
- métricas de tokens/costo;
- límite diario/mensual;
- contexto mínimo;
- redacción de secretos en logs.

### D4. Local/LAN

No es requisito del primer commit funcional, pero las interfaces deben permitir agregarlo sin reescribir sesiones, memoria o personality.

## 7. Fase E — Audio

### E1. Enumeración y selección

Primero lograr:

- listar micrófonos;
- listar salidas;
- seleccionar dispositivo;
- reproducir WAV de prueba;
- grabar muestra de prueba.

### E2. VAD / wake

Separar VAD de wake word conceptualmente.

El prototipo puede comenzar con push-to-talk/trigger de desarrollo si acelera validación, pero el objetivo de R2 es operación hands-free.

### E3. STT

Benchmarkear español en Banghó:

- latencia;
- RAM;
- CPU;
- WER subjetivo en ambiente de taller/local.

No fijar motor definitivo antes del benchmark.

### E4. TTS

Prioridades:

1. español natural suficiente;
2. baja latencia;
3. CPU/RAM moderada;
4. operación offline;
5. posibilidad de varias voces.

### E5. Playback mixer

Voz y música deben coordinarse:

- ducking opcional de música al hablar;
- evitar que TTS dispare STT;
- volumen independiente configurable.

## 8. Fase F — Face y Vision

### F1. Face POC

Antes de diseño artístico final:

- pantalla completa;
- fondo;
- dos ojos;
- pupilas;
- párpados;
- boca;
- estados animados;
- FPS limitado/configurable.

Objetivo de consumo: muy bajo en idle.

### F2. Vision POC

- abrir cámara;
- detectar cara/persona;
- emitir coordenadas normalizadas;
- debounce;
- FPS de cámara reducido cuando no hace falta precisión.

La visión no debe bloquear el render.

### F3. Integración

`Vision -> Presence -> Core -> Face`.

No permitir que Face lea directamente cámara o base de datos.

## 9. Fase G — Tools

Orden recomendado:

1. system time/status;
2. volume/playback;
3. notes;
4. timers/reminders;
5. business knowledge;
6. music;
7. web search/fetch;
8. weather.

Cada tool:

- schema explícito;
- validación de argumentos;
- permisos por modo;
- timeout;
- resultado estructurado;
- auditoría redactada.

## 10. Fase H — Web Admin

### H1. Baseline

Servidor local responsive sin SPA pesada.

Rutas/áreas mínimas:

- login/logout;
- dashboard;
- hardware;
- commerce;
- audio;
- vision;
- AI;
- personality;
- memory;
- system.

### H2. Seguridad

Desde la primera versión:

- password hash robusto;
- cookies `HttpOnly`/`SameSite` apropiadas;
- CSRF si aplica;
- rate limit/lockout;
- bind LAN configurable;
- no exponer secretos en HTML/API.

### H3. Setup inicial

Objetivo posterior del mismo módulo:

- primer usuario/admin;
- Wi-Fi/config básica;
- nombre del nodo;
- modo `SHOP/WORKSHOP/HOME`;
- datos del comercio;
- proveedor AI/presupuesto.

## 11. Fase I — Appliance Debian

Después de validar el ciclo desde desarrollo:

- usuario `ailen` dedicado;
- systemd;
- arranque directo;
- entorno gráfico mínimo para Face;
- watchdog;
- logs/rotación;
- política de energía;
- recuperación ante crash;
- SSH de mantenimiento opcional/documentado.

## 12. Fase J — Updater

No implementar updater antes de tener una app que arranque y reporte health.

Modelo objetivo:

```text
/opt/ailen/releases/<version>
/opt/ailen/current
/var/lib/ailen
/etc/ailen
/run/ailen
```

Secuencia:

1. consultar manifest;
2. descargar release;
3. verificar hash/firma;
4. instalar en nueva carpeta;
5. esperar estado seguro;
6. cambiar `current`;
7. reiniciar;
8. health check;
9. rollback si falla.

## 13. Fase K — Optimización por perfil

Sólo después de Banghó funcional.

### Banghó 8 GB

Perfil esperado: `HYBRID` o `LOCAL` liviano.

### SF20BA 8 GB

Medir y recortar dependencias.

### SF20BA 4 GB

Cloud-first + local pequeño si evidencia lo permite.

### 2 GB

`SATELLITE/CLOUD`; LLM local no obligatorio.

## 14. Trabajo paralelo recomendado

Para dos agentes simultáneos:

### Carril A — Foundation/Core

Puede crear:

- `pyproject.toml`;
- paquete base;
- config;
- logging;
- runtime state;
- hardware diagnostics;
- domain models;
- tests de foundation.

No debe implementar todavía audio/vision real.

### Carril B — Web/Contracts/Mocks

Puede crear:

- servidor web skeleton;
- templates responsive;
- auth model/mock;
- dashboard mock;
- contratos AI/audio/vision/tools;
- adapters fake;
- fixtures y tests aislados.

No debe acoplarse a un framework sin registrar la decisión técnica.

### Integración

Ambos carriles deben depender de contratos compartidos, no importar implementaciones entre sí.

## 15. Definition of Done del primer slice

Un primer slice integrable está completo cuando:

- instala dependencias en entorno de desarrollo;
- `ailen --help` funciona;
- `ailen diagnose hardware` funciona;
- `ailen serve` levanta Core + web dashboard;
- runtime state puede consultarse;
- config se valida;
- SQLite se crea/migra;
- no hay secretos en Git;
- tests básicos pasan;
- documentación de lo implementado está actualizada.

Todavía no exige rostro/audio/LLM real.

## 16. Definition of Done del prototipo Banghó

El prototipo de software previo al desarme está completo cuando, durante una prueba real:

1. inicia automáticamente;
2. muestra rostro;
3. detecta presencia;
4. escucha una pregunta;
5. transcribe;
6. resuelve local/tool/cloud según Router;
7. responde por voz;
8. guarda sesión;
9. panel web muestra estado;
10. reinicio conserva configuración/memoria;
11. pérdida de Internet no destruye el proceso;
12. logs permiten diagnosticar errores sin secretos.
