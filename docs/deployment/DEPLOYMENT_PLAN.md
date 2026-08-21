# Plan de despliegue — AILEN

## Objetivo

Convertir Debian 13 minimal en un appliance que arranque directamente al asistente, sea administrable por LAN y pueda actualizarse sin intervención técnica frecuente.

## Instalación objetivo

1. Debian 13 minimal.
2. Usuario dedicado de servicio.
3. Dependencias mínimas según perfil.
4. Configuración de audio/cámara/display.
5. AILEN instalado bajo `/opt/ailen/releases/<version>`.
6. Datos persistentes fuera de `/opt`.
7. Servicios systemd.
8. Autoinicio del rostro/Core.
9. Panel web sólo LAN por defecto.
10. Health check.

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
