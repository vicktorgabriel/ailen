# Modos de ejecución — Laboratorio y Appliance

**Estado:** baseline operativo
**Fecha:** 2026-08-21

AILEN tendrá dos formas deliberadamente distintas de ejecutarse. El objetivo es evitar que las máquinas de desarrollo/laboratorio sean modificadas como si fueran unidades comerciales dedicadas.

## 1. LAB MODE — Linux Mint / Windows 11

Los equipos con Linux Mint o Windows 11 se consideran **laboratorios**, no appliances. AILEN debe levantarse desde el repositorio/entorno de desarrollo y terminar sin modificar de forma permanente el sistema operativo.

En Lab Mode se probarán, entre otras cosas:

- rostro y animaciones;
- logs y estados;
- cámara real y seguimiento de presencia;
- micrófono, VAD, STT y TTS;
- conversación completa;
- diagnóstico de CPU/RAM/GPU/audio/cámara/display;
- selección automática de perfil;
- recomendación, descarga y arranque de un LLM local compatible;
- comparación de fluidez/latencia entre hardware;
- cloud/LAN fallback sin convertir la máquina en appliance.

Lab Mode **NO** debe:

- cambiar login/autologin del sistema;
- desactivar suspensión/hibernación global;
- alterar políticas de tapa/energía de forma persistente;
- crear una sesión kiosk permanente;
- reemplazar shell/escritorio del usuario;
- reiniciar automáticamente la máquina;
- instalar servicios de arranque sin una acción explícita separada.

La experiencia deseada es algo equivalente a `ailen lab start`: preparar runtime temporal, mostrar diagnóstico, resolver backends configurados y ejecutar AILEN. Al salir, la computadora continúa siendo una PC normal.

## 2. APPLIANCE MODE — Debian dedicado

Las unidades dedicadas usarán Debian 13 minimal según ADR-008. En este modo sí existe un **provisionador** encargado de transformar una instalación Debian limpia en una unidad AILEN repetible.

El provisionador futuro debe ser idempotente, auditable y fallar cerrado. Debe realizar como mínimo:

1. preflight de arquitectura, CPU, RAM, disco, red, audio, cámara y display;
2. seleccionar `DeviceProfile`;
3. instalar dependencias del sistema requeridas por ese perfil;
4. crear usuario/grupo de servicio dedicado y directorios `/opt`, `/etc`, `/var/lib` y `/run`;
5. instalar release AILEN sin depender de Git en producción;
6. copiar/generar configuración inicial;
7. preparar modelos STT/TTS/LLM aprobados según manifiesto y hardware;
8. configurar permisos de cámara/audio/display;
9. instalar unidades systemd y health checks;
10. configurar arranque del rostro sin escritorio completo;
11. evitar suspensión/hibernación y definir política de tapa/blanking apropiada para appliance;
12. evitar depender de un login interactivo para arrancar AILEN;
13. conservar una vía de recuperación administrativa (no eliminar acceso de mantenimiento);
14. preparar panel LAN y primera configuración de administrador;
15. ejecutar self-test final;
16. marcar instalación como completa únicamente si el health check pasa;
17. reiniciar automáticamente al finalizar una instalación dedicada exitosa;
18. en el siguiente boot iniciar AILEN como primera experiencia.

No se debe confundir “quitar login” con eliminar toda posibilidad de administración: la unidad debe arrancar AILEN sin intervención humana, pero mantener un mecanismo de recuperación seguro para soporte.

## 3. Model Manager común

Lab y Appliance deben compartir la misma lógica de decisión de modelos. El hardware se detecta una vez y un `ModelPlanner` produce un plan declarativo. El downloader/installer sólo ejecuta artefactos presentes en un catálogo firmado/hasheado y nunca acepta URLs generadas por un LLM.

El plan debe considerar:

- arquitectura y sistema operativo;
- RAM disponible;
- CPU/flags;
- GPU y VRAM cuando exista;
- espacio libre;
- perfil del nodo;
- capacidad del runtime local;
- tamaño/contexto/quantización del modelo;
- política de descarga y almacenamiento.

La descarga automática debe requerir una decisión explícita del operador en Lab Mode. En Appliance Mode puede formar parte del provisionado si el manifiesto del release/perfil ya lo autoriza.

## 4. Principio de portabilidad

Core, Router, Memory, Personality y contratos deben seguir siendo multiplataforma. Los adapters de hardware/OS son los que varían:

- Linux: ALSA/V4L2/X11/DRM/systemd;
- Windows Lab: APIs/comandos seguros específicos de Windows y backends Python/binarios disponibles;
- cualquier función no disponible debe degradar sin fingir hardware.

Windows 11 y Mint no son objetivos de appliance comercial por ahora: son plataformas de laboratorio para acelerar pruebas en hardware potente.
