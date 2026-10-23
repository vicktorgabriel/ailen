# Handoff para agentes — AILEN

> Documento operativo para Codex Sol Max, Codex Luna y otros agentes de desarrollo. OpenCode/AGY pueden aparecer en antecedentes históricos, pero no son proveedores runtime de AILEN. Debe leerse junto con `AGENTS.md` antes de modificar el repositorio.

## 1. Estado

AILEN está en `0.4.0-dev.0` y ya tiene un runtime funcional de laboratorio: Foundation/Core/Web, persistencia SQLite, Face/Vision, Audio/VAD/STT/TTS, AI Router adaptativo, R3C Controlled Tools, recordatorios, local Ollama/llama.cpp, LAN Brain y remotos HTTP nombrados. AGY/Antigravity y OpenCode están retirados del producto. OpenAI/Anthropic/DeepSeek/Kimi/MiniMax son presets no probados hasta disponer de clave/modelo y benchmark consentido. El baseline vigente es de 1164 tests, Ruff limpio, mypy limpio en 168 módulos y wheel limpio de 211 entradas; usar siempre el gate más reciente de `CURRENT_STATE.md`. El provisioning exige evidencia separada por hardware/modelo/runtime y no infiere runtime ni GPU offload desde compatibilidad declarada. FacePack 1.6 es default, falla a headless y nunca selecciona `portrait`/`pixel` automáticamente. Los agentes deben partir de `docs/memory/CURRENT_STATE.md` y `TASKS.md`; no deben reconstruir Foundation ni asumir que los bloques R1-R3 siguen pendientes.

## 1.1 Continuidad del thread Codex

- Thread canónico: `01a03a1f-e86e-7213-9581-af295af5c7f1`. Todos los trabajos de AILEN deben reanudar ese mismo chat, también cuando se alterna entre Sol Max y Luna.
- Sol Max: agente principal para arquitectura, cambios transversales y auditoría final.
- Luna (`gpt-6-luna`, esfuerzo alto): implementación de módulos acotados y correcciones sobre el thread canónico. Sus prompts deben ordenar tests y revisión del diff; una migración extensa se cierra con revisión de Sol.
- Reanudación: `scripts/resume_codex_ailen.sh sol` o `scripts/resume_codex_ailen.sh luna`. No usar `codex fork` ni crear una sesión nueva salvo autorización expresa.

## 1.2 AGY (Gemini) y OpenCode (DeepSeek free)

Agentes auxiliares de desarrollo por orden del propietario (no runtime del producto). Invocación y reglas en `AGENTS.md` (AGY con `gemini-3.8-flash-high`; OpenCode con modelo gratuito o, si se agotó, OpenCode Go).

## 2. Lectura obligatoria

En este orden:

1. `AGENTS.md`
2. `REGLAMENTO.md`
3. `docs/memory/CURRENT_STATE.md`
4. `docs/context/PRODUCT.md`
5. `docs/context/PRODUCT_BEHAVIOR.md`
6. `docs/context/PLAN_MAESTRO.md`
7. `docs/context/IMPLEMENTATION_PLAN.md`
8. `ARCHITECTURE.md`
9. `docs/architecture/MODULE_CONTRACTS.md`
10. `ROADMAP.md`
11. ADRs relacionados.

## 3. Restricciones críticas

No hacer:

- commits;
- push;
- borrar trabajo ajeno;
- introducir Docker/microservicios;
- meter personalidad dentro de un prompt estático como autoridad;
- acoplar el Core a OpenAI/Gemini/Ollama u otro proveedor;
- dar shell general al LLM;
- crear base vectorial;
- implementar reconocimiento facial obligatorio;
- comenzar updater o packaging productivo antes del Core/health;
- asumir requisitos de RAM sin benchmark;
- desarmar hardware;
- incluir claves, datos reales o memorias privadas.

Si una decisión estructural no está resuelta, crear/proponer ADR y dejar implementación desacoplada.

## 4. Prioridad actual

Trabajar sobre R4 y deudas verificables sin reabrir bloques cerrados:

```text
1. consolidar el working tree 0.4.0-dev.0 y mantener documentación/versionado sincronizados;
2. ejecutar en hardware reciclado la calificación local y la matriz de voz sobre el micrófono integrado/nativo de cada placa; ASRock/USB/Easy Effects sirven sólo como laboratorio. No guardar PCM ni promover modelos o micrófonos por detección;
3. terminar R5 Web Admin con datos reales: completar personalidad, visión, tools, rostro y sistema/setup; memoria explícita y diagnóstico ya consumen servicios reales sin acoplar handlers a infraestructura;
4. continuar R5B desde ADR-012 y el pack desktop de 79 secuencias: `facepack` es
   default y falla a headless; falta validar DLL/release packaging, perfiles LOW
   y una sesión conversacional completa con PCM/Vision reales;
5. preparar R6 Appliance Debian 13 minimal, systemd/watchdog y packaging reproducible;
6. conservar tests, seguridad, privacidad y límites de hardware como gates de cada entrega.
```

En Debian de desarrollo se permite implementar y probar software, pero no declarar hardware físico validado sin evidencia real. Codex Sol Max y Codex Luna son agentes de desarrollo; Gemini/OpenCode/AGY pueden figurar en documentos históricos, pero ninguno es proveedor conversacional runtime por ese solo hecho. Los agentes no hacen commit/push ni cambian arquitectura sin ADR o coordinación explícita.


> **Nota:** las secciones de carriles Foundation/Web/POC que siguen se conservan como referencia histórica de responsabilidades. No representan trabajo pendiente salvo que `TASKS.md` abra explícitamente una regresión o refactor.

## 5. Carril A — Foundation/Core

Un agente puede tomar exclusivamente este carril.

### Entregables

- `pyproject.toml` y tooling inicial si Python se confirma como baseline provisional;
- paquete importable `src/ailen`;
- CLI;
- versión centralizada;
- modelos de dominio básicos;
- config + `schema_version`;
- logging estructurado/redactado;
- runtime state;
- hardware diagnostics best-effort;
- SQLite + migraciones baseline;
- tests unitarios.

### No tocar

- templates/UI web más allá de contrato mínimo;
- implementación real de Face/Vision/STT/TTS;
- proveedor cloud real;
- updater.

### Criterio de cierre

- ejecución sin hardware especial;
- errores legibles;
- tests verdes;
- sin efectos laterales en imports;
- docs actualizadas si cambia estructura.

## 6. Carril B — Web/Contracts/Mocks

Otro agente puede trabajar en paralelo.

### Entregables

- web server skeleton ligero;
- login placeholder seguro o auth service baseline;
- dashboard responsive mínimo;
- endpoints de status/config usando servicios, no acceso directo a SQLite;
- templates base;
- contratos/adapters fake para AI, audio, vision y tools;
- fixtures para dashboard y pruebas;
- tests web aislados.

### No tocar

- hardware diagnostics internos;
- migraciones SQLite del carril A salvo coordinación explícita;
- backend real cloud/audio/vision;
- framework frontend pesado/SPA.

### Criterio de cierre

- se puede levantar web con datos fake;
- responsive básico móvil/escritorio;
- login no usa contraseña hardcodeada en producción;
- status consume una interfaz clara;
- tests no dependen de Internet.

## 7. Carril C — Investigación/benchmark, no integración

Un tercer agente puede investigar sin tocar foundation central.

Crear documentación/POCs aislados para:

- Face: SDL2 vs entorno gráfico mínimo;
- STT español;
- TTS español;
- VAD/wake word;
- local LLM pequeño;
- RAM/CPU esperada.

Los resultados deben ir a `docs/research/` o POCs claramente aislados. No convertir una prueba en dependencia productiva sin ADR.

## 8. Contratos que deben respetarse

Consultar `docs/architecture/MODULE_CONTRACTS.md`.

Reglas resumidas:

- Web usa servicios de aplicación;
- Face no accede a memoria/AI;
- Vision entrega observaciones normalizadas;
- AI Router elige backend;
- Core no conoce marcas/modelos concretos;
- Memory retorna modelos, no rows SQLite;
- tools tienen schema/permissions/timeout;
- updater nunca toca datos persistentes.

## 9. Estructura orientativa

No es dogma, pero se prefiere:

```text
src/ailen/
  app/
  core/
  domain/
  infrastructure/
  services/
  adapters/
  ai/
  audio/
  vision/
  face/
  memory/
  tools/
  web/
```

Mantener archivos pequeños y responsabilidades claras.

## 10. Convenciones de desarrollo

- typing explícito en APIs públicas;
- dataclasses/Pydantic/modelos equivalentes donde aporten valor;
- no usar `dict[str, Any]` como contrato principal entre capas;
- timeouts en I/O externo;
- dependencias opcionales para hardware/backends pesados;
- imports de módulos opcionales deben fallar de forma controlada;
- logs sin secretos;
- fixtures anonimizados/sintéticos;
- tests deterministas.

## 11. Validaciones antes de entregar cambios

El agente debe informar:

- archivos creados/modificados;
- decisiones tomadas;
- tests ejecutados;
- riesgos/pendientes;
- si tocó un ADR;
- si detectó conflicto con documentación.

No debe afirmar que hardware real fue validado si no se ejecutó físicamente.

## 12. Qué debe revisar ChatGPT después

Cuando otro agente termine, la revisión debe enfocarse en:

1. coherencia con identidad separada del LLM;
2. dependencias y consumo potencial;
3. separación de capas;
4. seguridad del panel;
5. uso correcto de SQLite/config;
6. tests;
7. ausencia de secretos;
8. compatibilidad con hardware limitado;
9. cambios no documentados;
10. diff completo antes de commit.

## 13. Entrega ideal para la primera revisión

La mejor primera entrega de agentes es una base aburrida pero sólida:

- CLI;
- configuración;
- status;
- DB;
- web skeleton;
- mocks;
- tests.

No se valora agregar muchas funciones antes de tener estos cimientos.
