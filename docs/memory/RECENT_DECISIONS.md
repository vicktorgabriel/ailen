# Decisiones recientes — AILEN

## 2026-08-21

### Proyecto

- Se fija `AILEN` como nombre estable del proyecto/plataforma en `/mnt/hdd4tb/repo/ailen`.
- AILEN significa **Asistente Inteligente Local, Evolutivo y Natural**.
- El nombre visible del personaje, su voz y su apariencia serán configurables por instalación.
- Antes de comercialización formal queda pendiente únicamente la verificación marcaria/legal del nombre.
- La disciplina documental seguirá un esquema similar al usado en AndesKey: arquitectura, roadmap, changelog, memoria de estado, ADRs y reglas para agentes.

### Producto

- El producto será un asistente físico para hogar, taller y comercio, no un chatbot de escritorio.
- El rostro será 2D, liviano y expresivo.
- Cámara = ojos, micrófono = oído, parlantes = voz.
- No se necesita una app móvil nativa: la administración será por web responsive en LAN.

### IA

- La identidad del asistente vive en AILEN Core, no en el LLM.
- Se adopta arquitectura híbrida: reglas/tools locales + LLM local opcional + LAN Brain opcional + API cloud rápida.
- Los modelos cloud están orientados a consultas breves, atención y síntesis; no se requiere razonamiento pesado por defecto.
- El router debe considerar costo, latencia, disponibilidad, privacidad y hardware.

### Hardware

- Banghó Zero G05 de 8 GB + M.2 500 GB será el primer prototipo real.
- Ryzen 5 5500 + 48 GB + RTX 3060 12 GB será laboratorio, no requisito del producto.
- SF20BA será plataforma objetivo para optimización, primero 8 GB y luego 4 GB.
- Equipos de 2 GB podrán ser Satellite/Cloud si las mediciones lo permiten.
- Equipos con pantalla rota pueden reutilizarse mediante monitor externo.

### Presencia física y Face (R2A)

- Se separa la capa lógica de animación (`FaceAnimator`) y los modelos de pose geométrica (`FacePose`) de cualquier biblioteca gráfica. El motor es determinista, corre sin pantalla y genera poses normalizadas (-1..1 / 0..1).
- Backend gráfico POC: se adopta `TkinterFaceController` como renderer interactivo de prueba, sin dependencia pip pero con requisito de `python3-tk` y un stack gráfico del sistema. No se fijan todavía cifras de RAM/CPU ni compatibilidad final de appliance hasta medir en hardware objetivo. `NullFaceController` mantiene soporte headless de primera clase.
- Detección de presencia POC: se utiliza clasificador Haar cascade de OpenCV a 5 FPS y 320px como dependencia opcional `[vision]`. Se prohíbe el reconocimiento de identidad, biometría y almacenamiento de imágenes.
- Debounce temporal (`VisionDebouncer`): se separa la observación instantánea de cámara del estado estable de presencia usando `vision.presence_debounce_seconds` (2.0s), previniendo falsos positivos de un solo frame y dropouts momentáneos.
- `InteractionCoordinator` integra la presencia debounced con `StateManager`, `SocialEngine` y actualiza la mirada (`gaze`) y expresiones en `FaceController`.

### Web / Admin / Seguridad

- El panel web deja de depender de `AILEN_ADMIN_PASSWORD`: la credencial administrativa de **usuario + contraseña** es persistente en SQLite (tabla `admin_credentials`, migración 0002, fila única) y se gestiona con `ailen admin set-password` vía getpass (nunca password en argv). Detalle completo en `ADR-007-local-admin-auth.md`.
- KDF baseline del panel: PBKDF2-HMAC-SHA256 con 600k iteraciones (stdlib, OWASP-aligned), salt aleatorio de 16 bytes por credencial, comparación constant-time. Fail-closed: sin credencial configurada nadie autentica.
- Lockout por IP: 5 fallos en 5 minutos => bloqueo 5 minutos. Sesiones siguen efímeras en memoria (deuda aceptada).
- `web.host`/`web.port` NO son editables desde el panel: cambiar el bind en caliente puede exponer el panel o dejar afuera al operador; se administran por archivo/CLI y aplican al reiniciar.
- `SettingsService` con allowlist explícita como único camino Web -> configuración (MODULE_CONTRACTS §16): validación server-side completa antes de guardar, claves desconocidas rechazadas, escritura atómica del TOML; la vista `/config` no renderiza secretos.
- Hardening HTTP baseline del servidor stdlib: body máx. 1 MiB (413), métodos permitidos explícitos (405), POST sólo `application/x-www-form-urlencoded` (415), CSP `default-src 'self'`, Referrer-Policy, Cache-Control no-store, timeout de socket.
- Se agrega sección `[identity]` a la configuración (`display_name` default neutro "Asistente"): AILEN es marca/plataforma, nunca nombre hardcodeado del personaje.
- Auditoría de integración: se corrige wake desde `SLEEP`, se hace efectivo el username del login, SQLite pasa a `0600` en POSIX, SettingsService adopta patch parcial, y rutas de configuración explícitas inexistentes dejan de caer silenciosamente a defaults.

### Distribución

- Las actualizaciones se diseñarán desde temprano con releases versionadas, verificación, health check y rollback.
- Los clientes usarán canal `stable`; prototipos, `beta`; desarrollo podrá usar `nightly`.
- No se inicializa Git ni se hacen commits hasta que el propietario cree/defina el repositorio y lo autorice.

### Desarrollo paralelo

- Se documenta un primer slice `Foundation/Core + Web/Mocks` antes de integrar Face/Audio/AI reales.
- Gemini y OpenCode pueden trabajar en paralelo con áreas de propiedad temporal separadas para reducir conflictos.
- Ningún agente debe hacer commit/push; la integración se revisará completa antes del primer commit.
- `TASKS.md` es la cola inmediata y `docs/operations/R1_PARALLEL_WORK.md` contiene los prompts/alcances listos para usar.
- Face/STT/TTS/LLM reales se validarán por POC/benchmark antes de fijarlos como dependencia definitiva.
