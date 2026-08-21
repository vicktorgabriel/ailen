# R1 — Trabajo paralelo sugerido

> Preparado para usar Gemini y OpenCode en paralelo sin superposición importante.

## Regla general

Antes de tocar archivos, cada agente debe leer `AGENTS.md` y `docs/operations/AGENT_HANDOFF.md`.

Ningún agente debe hacer commit ni push. El propietario/ChatGPT revisará el diff antes del primer commit.

## Agente 1 — Foundation/Core

### Alcance

Crear el foundation ejecutable del proyecto.

### Archivos/áreas preferidas

```text
pyproject.toml
src/ailen/__init__.py
src/ailen/__main__.py
src/ailen/domain/
src/ailen/core/
src/ailen/infrastructure/
src/ailen/memory/
src/ailen/services/
config/
tests/unit/
```

### Tareas

1. Proponer/usar Python como baseline provisional únicamente si no contradice ADR-006; registrar la decisión si agrega dependencias relevantes.
2. Crear paquete importable y CLI.
3. Implementar versión única.
4. Implementar configuración tipada con `schema_version` y ejemplo versionado.
5. Implementar logging estructurado con redacción.
6. Implementar modelos `RuntimeState`/health básicos.
7. Implementar `ailen diagnose hardware` best-effort sin requerir librerías pesadas.
8. Crear SQLite manager y mecanismo de migraciones baseline.
9. Crear tablas iniciales mínimas necesarias para sesiones/mensajes/meta; el resto puede dejarse como migraciones siguientes si simplifica el primer slice.
10. Crear tests ejecutables sin Internet/hardware especial.

### No hacer

- no UI web real;
- no Face real;
- no OpenCV real;
- no STT/TTS real;
- no proveedor cloud real;
- no Ollama/llama.cpp real;
- no updater;
- no systemd todavía salvo documentación/mock.

### Resultado esperado

```text
python -m ailen --help
python -m ailen diagnose hardware
```

más tests verdes.

## Agente 2 — Web/Mocks/Contracts

### Alcance

Crear panel web skeleton y backends falsos usando los contratos documentados.

### Archivos/áreas preferidas

```text
src/ailen/web/
src/ailen/adapters/
src/ailen/ai/
src/ailen/audio/
src/ailen/vision/
src/ailen/face/
src/ailen/tools/
tests/web/
tests/fakes/
```

Puede agregar modelos compartidos únicamente coordinándose con lo ya creado por Foundation.

### Tareas

1. Elegir un servidor web ligero; si la elección condiciona arquitectura, actualizar/proponer ADR-006.
2. Crear app web sin SPA pesada.
3. Crear layout responsive mobile-first.
4. Crear dashboard usando un `StatusService` fake/interface.
5. Crear login/auth baseline seguro o, si depende de Foundation, dejar interfaz + implementación fake clara.
6. Crear páginas skeleton para Comercio, IA, Personalidad, Audio/Cámara y Sistema.
7. Crear protocols/interfaces + fakes para AI, STT, TTS, Vision y Tools alineados con `MODULE_CONTRACTS.md`.
8. Crear tests sin Internet.
9. No acceder directamente a SQLite desde handlers/templates.

### No hacer

- no hardware diagnostics;
- no tocar migraciones reales salvo coordinación;
- no API cloud real;
- no vision/audio real;
- no framework frontend pesado;
- no API keys hardcodeadas.

### Resultado esperado

Web local levantable con datos sintéticos y responsive desde teléfono/desktop.

## Reglas para evitar conflictos

- Foundation es dueño temporal de `pyproject.toml`, config, DB/migrations, domain/runtime.
- Web es dueño temporal de `src/ailen/web` y fakes de adapters.
- Si Web necesita una dependencia, documentarla y evitar editar `pyproject.toml` simultáneamente; informar el cambio requerido.
- Si ambos necesitan un modelo compartido, colocarlo en `domain/` sólo una vez y documentar el contrato.
- No renombrar carpetas centrales sin coordinación.
- No reformatear archivos no relacionados.

## Integración posterior

Después de ambos trabajos:

1. revisar `git diff` completo;
2. resolver imports/modelos duplicados;
3. decidir framework/dependencias en ADR-006;
4. unir `StatusService` real con dashboard;
5. asegurar que `ailen serve` levante Core + Web;
6. ejecutar suite completa;
7. revisar consumo base;
8. actualizar `TASKS.md`, `CURRENT_STATE.md` y `CHANGELOG.md`;
9. recién entonces preparar primer commit.

## Prompt corto para Agente 1

```text
Estás trabajando en AILEN, un asistente físico para hardware reciclado. Lee primero AGENTS.md y docs/operations/AGENT_HANDOFF.md, luego PRODUCT_BEHAVIOR.md, IMPLEMENTATION_PLAN.md, ARCHITECTURE.md, MODULE_CONTRACTS.md y TASKS.md. Toma exclusivamente el carril Foundation/Core definido en docs/operations/R1_PARALLEL_WORK.md. Crea el foundation ejecutable, config, logging, runtime/health, diagnóstico de hardware, SQLite/migraciones y tests. No implementes Face/Vision/STT/TTS/LLM/cloud/updater reales. No hagas commit ni push. Al terminar informa archivos cambiados, tests, decisiones y pendientes.
```

## Prompt corto para Agente 2

```text
Estás trabajando en AILEN, un asistente físico para hardware reciclado. Lee primero AGENTS.md y docs/operations/AGENT_HANDOFF.md, luego PRODUCT_BEHAVIOR.md, IMPLEMENTATION_PLAN.md, ARCHITECTURE.md, MODULE_CONTRACTS.md y TASKS.md. Toma exclusivamente el carril Web/Mocks/Contracts definido en docs/operations/R1_PARALLEL_WORK.md. Crea web skeleton responsive, auth/status abstraídos, páginas skeleton y fakes/interfaces AI/STT/TTS/Vision/Tools. No implementes hardware/AI reales, no toques migraciones/core salvo necesidad coordinada, no uses SPA pesada. No hagas commit ni push. Al terminar informa archivos cambiados, tests, decisiones y pendientes.
```
