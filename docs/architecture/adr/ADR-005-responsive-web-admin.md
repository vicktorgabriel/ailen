# ADR-005 — Administración web responsive

**Estado:** Accepted  
**Fecha:** 2026-08-21

## Contexto

El producto debe poder configurarse y mantenerse desde un celular o PC sin conectar teclado/mouse al dispositivo ni mantener aplicaciones móviles nativas.

## Decisión

Cada nodo ofrecerá inicialmente una interfaz web responsive autenticada accesible por LAN. Más adelante un Manager podrá agregar varios nodos en una misma interfaz. PWA será opcional.

## Consecuencias

- una sola UI sirve para Android, iOS y escritorio;
- menor costo de mantenimiento;
- el panel debe funcionar bien en pantallas pequeñas;
- autenticación, sesiones y hardening web forman parte del producto;
- exposición remota por Internet no estará habilitada por defecto.
