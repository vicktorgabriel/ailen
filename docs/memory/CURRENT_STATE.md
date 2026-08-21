# Estado actual — AILEN

**Fecha:** 2026-08-21  
**Versión:** `0.1.0-dev.0`  
**Fase:** R2A auditado; POC Face + Vision integrado sobre la base R1.

## Qué existe

- carpeta del proyecto creada en `/mnt/hdd4tb/repo/ailen`;
- definición del producto;
- plan maestro;
- arquitectura inicial;
- roadmap hasta 1.0.0;
- changelog y versionado inicial;
- reglas para agentes y contribución;
- estructura documental inspirada en AndesKey;
- comportamiento del producto documentado (`PRODUCT_BEHAVIOR.md`);
- plan de implementación operativo (`IMPLEMENTATION_PLAN.md`);
- contratos entre módulos (`MODULE_CONTRACTS.md`);
- task board de R1 (`TASKS.md`);
- handoff específico para Gemini/OpenCode/Codex (`AGENT_HANDOFF.md`);
- matriz de aceptación verificable (`ACCEPTANCE_MATRIX.md`);
- carpetas preparadas para código, pruebas, scripts, empaquetado y releases.

- Foundation/Core ejecutable (`pyproject.toml`, CLI `ailen`, versión unificada);
- Sistema de configuración tipado con `schema_version` y plantilla versionada (`config/ailen.example.toml`);
- Logging estructurado con redacción automática de secretos y tokens;
- Diagnóstico de hardware best-effort (`ailen diagnose hardware`) y recomendador de perfiles;
- RuntimeState y HealthService observables;
- EventBus in-memory ligero con suscripciones tipadas, aislamiento de errores y correlation IDs;
- SocialEngine determinista con modos sociales (`HOME`, `WORKSHOP`, `SHOP`, `PUBLIC`, `PRIVATE`, `SLEEP`), cooldown y deduplicación por sesión de presencia;
- `SocialPrivacyPolicy` determinista fuera del LLM con aislamiento inviolable de memorias privadas en `PUBLIC` y `SHOP`;
- `InteractionCoordinator` orquestando ciclo de presencia física, transiciones de estado, decisiones sociales y publicación de eventos;
- `PersonalityBoundary` con límites inviolables sobre seguridad, herramientas y privacidad;
- Panel web utilizable desde celular: `SettingsService` con allowlist de campos administrables, vista `/config` responsive (GET/POST con CSRF, validación server-side, guardado atómico del TOML), identidad del personaje configurable (`[identity].display_name`, voz) separada de la marca AILEN;
- Autenticación administrativa persistente por usuario + contraseña en SQLite (migración `0002_admin_credentials`, ADR-007): PBKDF2-HMAC-SHA256 con 600k iteraciones, salt aleatorio, comparación constant-time, lockout por IP, fail-closed sin credencial; CLI `ailen admin set-password` vía getpass;
- Hardening HTTP baseline del panel: límite de body (413), métodos permitidos (405), Content-Type exigido en POST (415), CSP/Referrer-Policy/no-store, timeout de socket; fallos de diagnóstico no tiran abajo el panel;
- SQLite endurecida con permisos owner-only (`0600`) en POSIX porque contiene memoria privada y credencial administrativa derivada;
- `SettingsService.update()` usa semántica de patch parcial; la Web traduce checkboxes HTML ausentes a `false`;
- Motor lógico de rostro `FaceAnimator` y modelo `FacePose` agnóstico de renderer, con parpadeo no periódico, micro-movimientos y apertura de boca;
- Backend gráfico POC `TkinterFaceController` (sin dependencia pip, requiere `python3-tk`/stack gráfico del sistema) y `NullFaceController` para headless; consumo real pendiente de benchmark físico;
- `VisionDebouncer` temporal para presencia física basado en `presence_debounce_seconds`;
- Backend de cámara POC `OpenCvVisionBackend` con Haar cascade a 5 FPS / 320px y degradación limpia;
- Integración en `InteractionCoordinator` enlazando presencia debounced con transiciones de estado, mirada y expresiones en el rostro;
- Demos CLI `ailen demo face` (con `--gui` y `--headless`) y `ailen demo vision`;
- Suite de benchmark reproducible (`tools/benchmark_presence.py`) y reporte en máquina de desarrollo (`docs/benchmarks/dev_presence_benchmark.md`);
- Suite completa: 187 tests pasando; `ruff` y `mypy` en verde sobre 60 archivos fuente; wheel construido correctamente con módulos Face/Vision y package-data existentes.

## Qué NO existe todavía

- backend gráfico de producción nativo DRM/KMS para appliance sin X11 (actualmente POC Tkinter + Headless);
- audio real / STT / TTS;
- AI Router / integración cloud real;
- LAN Brain;
- updater;
- benchmarks físicos en hardware objetivo (Banghó Zero G05 / SF20BA).

## Hardware objetivo inmediato

### Prototipo

Banghó Zero G05:

- 8 GB RAM;
- M.2 500 GB;
- pantalla/cámara/audio integrados disponibles para el prototipo.

### Laboratorio

Ryzen 5 5500 + 48 GB DDR4 + RTX 3060 12 GB VRAM para pruebas de modelos y benchmarks de referencia.

### Próximos objetivos

1. SF20BA 8 GB;
2. SF20BA 4 GB;
3. equipos 2 GB en modo Satellite/Cloud;
4. placas con pantalla rota usando monitor externo o modo sin pantalla.

## Próxima decisión técnica

Cerrar `ADR-006` o usarlo explícitamente como baseline provisional antes de integrar dependencias que condicionen el producto. Debe resolver mediante POC/benchmark:

- lenguaje/core;
- framework web;
- backend gráfico del rostro;
- STT/TTS baseline;
- persistencia;
- cómo encapsular proveedores LLM.

La base Foundation/Core/Web está cerrada para esta etapa; Face/Vision ya tienen POC integrado. El siguiente trabajo debe centrarse en Audio/STT/TTS sin ampliar todavía a LLM/cloud.

## Próximo milestone

`R2B — Audio local: dispositivos, VAD, STT y TTS baseline`, manteniendo ADR-006 como decisión guiada por POC/benchmarks antes de fijar dependencias pesadas.

Trabajo inmediato definido en `TASKS.md` y `docs/operations/AGENT_HANDOFF.md`.

El repositorio Git local está inicializado en `main`, conectado a `git@github.com:vicktorgabriel/ailen.git` y ya tiene commit fundacional (`84906c5`). El commit de R2A se realizará al cerrar esta auditoría. No se hace push sin autorización explícita.

## Riesgos conocidos

- latencia y consumo real en SF20BA aún desconocidos;
- compatibilidad gráfica sin X/Wayland aún no validada;
- STT/TTS óptimos por perfil aún no medidos;
- costo cloud estimado pero aún no medido con tráfico real;
- nombre `AILEN` fijado para proyecto/plataforma; queda pendiente sólo la verificación marcaria/legal antes de comercialización formal;
- soporte de equipos de 2 GB sujeto a pruebas reales.
