# ADR-003 — Router de IA híbrido

**Estado:** Accepted  
**Fecha:** 2026-08-21

## Contexto

El hardware objetivo varía desde netbooks de 2 GB hasta PCs con GPU. Forzar un único modelo local elevaría requisitos; depender sólo de cloud eliminaría autonomía y privacidad.

## Decisión

AILEN Core dispondrá de un router capaz de resolver una solicitud mediante:

1. regla/intención local;
2. herramienta directa;
3. LLM local;
4. LAN Brain;
5. proveedor cloud.

El router considerará disponibilidad, costo, latencia, privacidad, hardware y configuración.

## Consecuencias

- equipos pobres siguen siendo útiles;
- cloud no es obligatorio para todas las acciones;
- el sistema puede degradar capacidades;
- se requieren métricas de costo/latencia y contratos uniformes para modelos.
