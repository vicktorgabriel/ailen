# ADR-001 — Core modular antes de distribuir procesos

**Estado:** Accepted  
**Fecha:** 2026-08-21

## Contexto

AILEN tendrá rostro, audio, visión, memoria, herramientas, web y varios backends de IA. Separar todo en microservicios desde el inicio aumentaría consumo, complejidad de IPC y dificultad de depuración, especialmente en equipos de 2–4 GB.

## Decisión

Comenzar con un monolito modular y contratos internos claros. Separar procesos únicamente cuando exista una razón medible: aislamiento de fallos, permisos distintos, watchdog independiente o ahorro de recursos.

## Consecuencias

- prototipo más rápido;
- menor overhead;
- módulos siguen siendo reemplazables;
- la frontera lógica debe respetarse aunque compartan proceso.
