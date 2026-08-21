# Plan de despliegue — AILEN

## Objetivo

Convertir Debian 13 minimal en un appliance que arranque directamente al asistente, sea administrable por LAN y pueda actualizarse sin intervención técnica frecuente. La separación entre equipos laboratorio y unidades dedicadas está definida en `LAB_AND_APPLIANCE_MODES.md`.

## Instalación objetivo

Baseline aceptado: **Debian 13 stable amd64 netinst/minimal**, según ADR-008. No se instala un entorno de escritorio completo.

1. Debian 13 minimal.
2. Usuario dedicado de servicio.
3. Dependencias mínimas según perfil.
4. Configuración de audio/cámara/display.
5. Si el nodo tiene pantalla y usa el POC Tkinter: Xorg mínimo + `xinit` + `python3-tk`, sin GNOME/KDE/XFCE ni navegador kiosk.
6. Si el nodo es headless/Satellite: sin servidor gráfico.
7. AILEN instalado bajo `/opt/ailen/releases/<version>`.
8. Datos persistentes fuera de `/opt`.
9. Servicios systemd.
10. Autoinicio de Core y, cuando corresponda, sesión gráfica directa del rostro.
11. Panel web sólo LAN por defecto.
12. Health check.

Si un futuro renderer SDL2/DRM-KMS resulta superior en hardware objetivo, se podrá quitar Xorg sin cambiar Debian como OS base.

## Layout previsto

```text
/opt/ailen/releases/<version>/
/opt/ailen/current
/etc/ailen/ailen.toml
/var/lib/ailen/ailen.db
/var/lib/ailen/assets/
/var/lib/ailen/secrets/
/run/ailen/runtime.json
```

## Actualización

```text
check manifest
  -> download
  -> verify
  -> unpack new release
  -> preflight
  -> switch current
  -> restart
  -> health check
  -> keep OR rollback
```

## Canales

- `nightly`: desarrollo interno;
- `beta`: prototipos/pilotos;
- `stable`: clientes.

## Git y releases

El repo fuente podrá alojarse en GitHub. Los dispositivos no deben necesitar Git para actualizarse: consumirán artefactos de release y manifest verificables.

La separación repo fuente / repo público de distribución se decidirá más adelante según seguridad y mantenimiento, tomando como referencia la experiencia de AndesKey.

## Primera validación

La primera instalación end-to-end se hará en Banghó Zero G05 completa, antes de modificar su carcasa.
