# Roadmap — AILEN

> AILEN es el nombre estable del proyecto/plataforma. La identidad visible del personaje se configura por instalación.

## R0 — Definición de producto — EN CURSO

- [x] Definir objetivo: asistente físico para hogar/taller/comercio.
- [x] Separar identidad del modelo de IA.
- [x] Definir estrategia híbrida local/LAN/cloud.
- [x] Definir administración web responsive sin app móvil obligatoria.
- [x] Definir perfiles `Satellite/Cloud/Hybrid/Local/LAN Brain`.
- [x] Definir hardware de prototipo Banghó Zero G05.
- [x] Definir SF20BA 8/4 GB como objetivo de optimización.
- [x] Definir 2 GB como perfil remoto/satélite viable.
- [x] Crear documentación base, arquitectura y reglas de proyecto.
- [x] Fijar `AILEN` como nombre del proyecto/plataforma.
- [ ] Verificar disponibilidad marcaria/legal antes de comercialización formal.
- [ ] Elegir stack técnico inicial mediante ADR.

## R1 — Bootstrap del repositorio y prototipo base — OBJETIVO 0.1.x

- [x] Inicializar Git local y configurar remoto `origin`.
- [x] Definir `pyproject`/dependencias baseline.
- [x] Crear CLI de diagnóstico de hardware.
- [x] Detectar RAM, CPU, arquitectura, audio, cámara y display best-effort.
- [x] Definir formato de configuración local.
- [x] Implementar logging estructurado y redactado.
- [ ] Crear servicio systemd mínimo del Core.
- [x] Implementar runtime state/health básico.
- [ ] Documentar instalación Debian 13 minimal en Banghó.
- [ ] Registrar benchmark base de la Banghó.

## R2 — Presencia física: rostro, cámara y audio — OBJETIVO 0.2.x

- [ ] Seleccionar backend gráfico mediante benchmark/ADR.
- [ ] Implementar rostro 2D minimalista.
- [ ] Estados `IDLE`, `ATTENTION`, `LISTENING`, `PROCESSING`, `SPEAKING`, `SLEEP`.
- [ ] Parpadeo y microanimaciones no deterministas.
- [ ] Detección simple de persona/rostro.
- [ ] Seguimiento de coordenadas con pupilas.
- [ ] Captura de micrófono y VAD/wake word.
- [ ] STT local baseline.
- [ ] TTS local baseline.
- [ ] Sincronización aproximada de boca.
- [ ] Selección de dispositivos audio/cámara.
- [ ] Primer ciclo completo: ver → escuchar → responder → hablar.

## R3 — Cerebro híbrido, memoria e identidad — OBJETIVO 0.3.x

- [ ] Implementar AI Router.
- [ ] Implementar backend local pequeño.
- [ ] Implementar proveedor cloud rápido y económico mediante interfaz genérica.
- [ ] Implementar LAN Brain opcional.
- [ ] Fallback automático por disponibilidad.
- [ ] Presupuesto diario/mensual configurable.
- [ ] Métricas de tokens/costo/latencia.
- [ ] SQLite inicial.
- [ ] Sesiones y mensajes.
- [ ] Memorias explícitas.
- [ ] FTS5.
- [ ] Construcción de contexto mínimo para cloud.
- [ ] Personality Engine v1.
- [ ] Semilla persistente de personalidad.
- [ ] Modos sociales `WORKSHOP`, `SHOP`, `HOME`, `PUBLIC`, `PRIVATE`.
- [ ] Evitar exposición de memoria privada en modo público.

## R3B — Lab Mode y runtime local adaptativo — OBJETIVO 0.3.x

- [x] `ailen lab start` sin cambios persistentes del SO ni dependencias de root/services.
- [x] soporte de laboratorio explícito para Linux Mint y Windows 11.
- [x] normalizar detección multiplataforma de CPU/RAM/GPU/VRAM/disco/audio/cámara/display sin inventar capabilities desconocidas.
- [x] Model Catalog versionado con artefactos aprobados y hashes; Qwen 3.5 0.8B Q4_0/Q8_0 verificados el 2026-08-21.
- [x] Model Planner explicable por hardware/perfil y clasificado por propósito (`SANITY`, `BALANCED`, `QUALITY`).
- [x] descarga segura con consentimiento explícito en Lab Mode, HTTPS + tamaño exacto + SHA-256 + rename atómico.
- [x] ModelStore local por plataforma, separado de Git y con protección de path traversal.
- [x] `LabComponentFactory` sin sustituciones fake silenciosas en modo real (`--simulate` para offline/UI tests).
- [x] cableado conversacional de software en `LabRunner`: Face/Vision/Audio/STT/Router/LLM/TTS sin fakes silenciosos; falta validación física.
- [x] inventario de modelos en runtime `RuntimeModelInventory` y runtime gestionado `ManagedLlamaRuntime`.
- [x] telemetría y métricas de sesión `LabSessionMetrics` exportadas a `runtime/lab/session_<timestamp>.json` con medición de Time To First Audible Response (TTFAR).
- [x] asistente `ailen lab prepare-ai` y diagnóstico con remediaciones `ailen lab doctor [--json]`.
- [x] R3B.3 catálogo declarativo de modelos de voz (`SpeechAssetCatalog`), store seguro y preflight físico exhaustivo (`LabPreflightChecker`).
- [x] R3B.4 inferencia adaptativa (`InferenceProfile`), política de residencia de modelos (`ModelResidencyPolicy`), prohibición de model hopping y arnés `ailen lab benchmark-ai`.
- [ ] validar primera sesión física interactiva en Linux Mint con cámara/micrófono/parlantes y assets STT/TTS reales.
- [ ] validar después el segundo laboratorio en Windows 11.
- [ ] registrar benchmarks reales de los equipos laboratorio sin confundirlos con hardware objetivo comercial.

## R4 — Herramientas y comportamiento útil — OBJETIVO 0.3/0.4.x

- [ ] Música local/stream mediante herramienta controlada.
- [ ] Volumen/play/pause sin LLM.
- [ ] Notas.
- [ ] Recordatorios simples.
- [ ] Información del negocio/FAQ.
- [ ] Búsqueda web.
- [ ] Fetch/extracción web controlada.
- [ ] Hora/clima mediante backend apropiado.
- [ ] Saludo automático con cooldown/debounce.
- [ ] Comportamiento social configurable.
- [ ] Derivación segura cuando no conoce una respuesta.
- [ ] Tool permission model.

## R5 — Panel web responsive — OBJETIVO 0.4.x

- [ ] Login local con hash robusto.
- [ ] Sesiones y expiración.
- [ ] Rate limit/lockout.
- [ ] Dashboard responsive.
- [ ] Estado de hardware.
- [ ] Configuración de red.
- [ ] Información del comercio.
- [ ] Voz y audio.
- [ ] Cámara y presencia.
- [ ] IA/proveedores/presupuesto.
- [ ] Personalidad y evolución.
- [ ] Memoria administrable.
- [ ] Conversaciones e historial.
- [ ] Diagnóstico.
- [ ] PWA opcional.
- [ ] Primera experiencia de setup desde celular.

## R6 — Instalación appliance y actualizaciones — OBJETIVO 0.5.x

- [ ] Provisionador Debian 13 minimal idempotente y auditable.
- [ ] Preflight y selección automática de `DeviceProfile`.
- [ ] Usuario/grupo dedicado y permisos de hardware.
- [ ] Arranque directo a AILEN sin login interactivo obligatorio.
- [ ] Mantener vía de recuperación administrativa segura.
- [ ] Sin entorno de escritorio pesado.
- [ ] Configurar suspensión/hibernación, política de tapa y blanking para appliance.
- [ ] Instalar modelos aprobados según manifest/perfil.
- [ ] Self-test/health check antes de marcar instalación completa.
- [ ] Reinicio automático al finalizar provisionado exitoso.
- [ ] Primer boot entra directamente a la experiencia AILEN.
- [ ] Servicios systemd y watchdog.
- [ ] Separar releases de datos persistentes.
- [ ] Manifest por arquitectura/perfil.
- [ ] SHA-256 y firma/verificación.
- [ ] Canales `nightly`, `beta`, `stable`.
- [ ] Health check post-update.
- [ ] Rollback automático.
- [ ] Release consumible sin Git instalado.
- [ ] Prueba end-to-end de actualización real.

## R7 — Optimización SF20BA — OBJETIVO 0.6.x

- [ ] Instalar en SF20BA 8 GB.
- [ ] Medir RAM/CPU/temperatura/latencia.
- [ ] Reducir servicios y dependencias.
- [ ] Validar LLM local pequeño donde sea viable.
- [ ] Instalar en SF20BA 4 GB.
- [ ] Definir límites reales del perfil `Hybrid`.
- [ ] Definir límites reales del perfil `Cloud`.
- [ ] Ajustar detector automático de perfil.
- [ ] Validar jornada prolongada.
- [ ] Documentar disipación y montaje seguro en carcasa.

## R8 — Satellite / hardware de 2 GB — OBJETIVO 0.7.x

- [ ] Ejecutar Core mínimo sin LLM local obligatorio.
- [ ] Mantener rostro/audio/presencia.
- [ ] Cloud como inferencia principal.
- [ ] LAN Brain como alternativa.
- [ ] Medir consumo idle y peak.
- [ ] Validar placas sin pantalla con HDMI/monitor externo.
- [ ] Definir modo headless/voz si no hay display.
- [ ] Documentar hardware que no justifica soporte.

## R9 — Manager multi-nodo por LAN — OBJETIVO 0.7.x

- [ ] Device identity por nodo.
- [ ] Descubrimiento LAN.
- [ ] Pairing explícito.
- [ ] Dashboard multi-nodo.
- [ ] Distribución de configuración.
- [ ] Estado/health agregado.
- [ ] Gestión de actualizaciones por grupo.
- [ ] LAN Brain compartido.
- [ ] API Gateway opcional para ocultar claves cloud a satélites.
- [ ] Revocación de dispositivo.

## R10 — Prototipo físico dedicado — OBJETIVO 0.8.x

- [ ] Desarmar unidad elegida sólo después de validar software.
- [ ] Reutilizar pantalla/cámara/micrófono/parlantes.
- [ ] Diseñar primera carcasa.
- [ ] Eliminar batería envejecida cuando corresponda.
- [ ] Validar fuente, temperatura y ventilación.
- [ ] Integrar botón físico de apagado/servicio si se necesita.
- [ ] Evaluar LEDs/servos externos mediante microcontrolador.
- [ ] Crear variante para monitor externo.

## R11 — Piloto taller/comercio — OBJETIVO 0.8/0.9.x

- [ ] Instalar primera unidad en taller propio.
- [ ] Registrar una jornada de uso real.
- [ ] Ajustar falsos saludos/detección.
- [ ] Medir costo cloud real.
- [ ] Evaluar interacción de clientes.
- [ ] Crear procedimiento de soporte.
- [ ] Crear checklist de instalación.
- [ ] Crear backup/exportación.
- [ ] Piloto con al menos un comerciante externo.
- [ ] Registrar feedback y fallos.
- [ ] Corregir antes de ampliar piloto.

## R12 — Precomercial — OBJETIVO 0.9.x

- [ ] Nombre/marca definitiva.
- [ ] Branding configurable.
- [ ] Hardening del panel.
- [ ] Política de privacidad clara.
- [ ] Política de datos/cámara/micrófono.
- [ ] Gestión de API y cuotas comercial.
- [ ] Manual de instalación/usuario.
- [ ] Matriz de hardware soportado.
- [ ] Procedimiento de reemplazo/recuperación.
- [ ] Releases stable probadas en múltiples unidades.
- [ ] Estrategia de precios y soporte definida fuera del código.

## R13 — 1.0.0 comercial

Sólo si:

- [ ] el piloto externo fue estable;
- [ ] actualización y rollback están probados;
- [ ] costo por unidad y por mes es conocido;
- [ ] los modos públicos no filtran memoria privada;
- [ ] existe procedimiento de soporte y restauración;
- [ ] hay al menos un perfil de hardware oficialmente soportado;
- [ ] documentación y changelog están al día;
- [ ] el producto puede instalarse de forma repetible.

## Futuro opcional posterior a 1.0

- QR/códigos de barra;
- ficha de reparación por voz;
- sensores/servos mediante ESP32/Pico;
- cuello móvil;
- integración con sistemas de gestión mediante APIs explícitas;
- reconocimiento de usuario opt-in;
- sincronización segura de identidad entre terminales;
- gateway cloud propio;
- dashboard remoto fuera de LAN;
- marketplace de voces/rostros/personajes si algún día tiene sentido.
