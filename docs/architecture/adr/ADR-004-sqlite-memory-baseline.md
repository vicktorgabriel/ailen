# ADR-004 — SQLite y FTS5 como baseline de memoria

**Estado:** Accepted  
**Fecha:** 2026-08-21

## Contexto

AILEN necesita persistir sesiones, recuerdos, configuración, personalidad, información del negocio y métricas en equipos con poca RAM. Una base vectorial agrega dependencias y consumo antes de saber si aporta valor real.

## Decisión

Usar SQLite como almacenamiento local baseline y FTS5 para búsqueda textual. Agregar embeddings/base vectorial sólo si benchmarks y casos reales demuestran una mejora necesaria.

## Consecuencias

- dependencia mínima;
- backups sencillos;
- buen comportamiento offline;
- esquema y migraciones deberán versionarse;
- la recuperación semántica avanzada queda diferida.
