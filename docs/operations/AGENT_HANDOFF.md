# Handoff para agentes — AILEN

> Documento operativo para Gemini, OpenCode, Codex u otros agentes. Debe leerse junto con `AGENTS.md` antes de modificar el repositorio.

## 1. Estado

AILEN está en `0.1.0-dev.0` y ya tiene un runtime funcional de laboratorio: Foundation/Core/Web, persistencia SQLite, Face/Vision, Audio/VAD/STT/TTS, AI Router adaptativo y R3C Controlled Tools. El baseline actual supera 500 tests. Los agentes deben partir de `docs/memory/CURRENT_STATE.md` y `TASKS.md`; no deben reconstruir Foundation ni asumir que los bloques R1-R3 siguen pendientes.

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
1. terminar backend musical local/MPRIS y validarlo físicamente cuando exista un reproductor disponible;
2. mantener WebSearch desacoplado y elegir/implementar proveedor real sólo con credenciales/costos explícitos;
3. mejorar robustez de instalación limpia y provisioning Debian;
4. dejar STT G600 vs Whisper.cpp y benchmarks de hardware para sesiones físicas autorizadas;
5. mantener documentación, tests y boundaries de seguridad sincronizados.
```

En Debian de desarrollo se permite implementar y probar software, pero no declarar hardware físico validado sin evidencia real. Gemini/OpenCode/Codex actúan como agentes subordinados: no hacen commit/push y no cambian arquitectura sin ADR o coordinación explícita.

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
