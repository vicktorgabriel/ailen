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

## Aplicación R5 — 2026-10-02

Memoria y diagnóstico conservan HTML server-rendered sin nuevas dependencias y
consumen contratos de aplicación inyectados desde `serve`. Se administran sólo
recuerdos explícitos con exposición pública por defecto y acceso privado
explícito; las escrituras/exportaciones son POST autenticado + CSRF + confirmación.
No se agrega purga masiva ni acceso SQLite desde handlers.

El diagnóstico distingue proceso Web de Lab: health local no representa el
estado vivo de otro proceso. LabDoctor se ejecuta a pedido; la telemetría leída
es la última sesión finalizada, con procedencia/muestras/fecha. Sin evidencia se
muestra ausencia o error, nunca valores de muestra. El lector tiene root fijo y
límites, rechaza symlinks y no entrega contenido conversacional. Observabilidad
entre procesos en vivo y visor de logs quedan fuera de este slice.
