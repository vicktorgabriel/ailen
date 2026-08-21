# ADR-002 — Identidad independiente del LLM

**Estado:** Accepted  
**Fecha:** 2026-08-21

## Contexto

El proyecto debe poder cambiar entre modelos locales, un cerebro LAN y proveedores cloud sin que el personaje pierda continuidad.

## Decisión

La identidad, personalidad, memoria, preferencias, modos sociales, permisos y evolución pertenecen a AILEN Core y a su almacenamiento persistente. Los LLM se tratan como motores de inferencia intercambiables.

## Consecuencias

- cambiar de modelo no crea un personaje nuevo;
- la memoria puede permanecer local aunque la inferencia sea remota;
- el Core debe construir contexto explícitamente;
- prompts de proveedor no son fuente canónica de personalidad;
- backups de identidad no dependen de un proveedor externo.
