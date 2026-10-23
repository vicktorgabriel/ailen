# Roadmap — AILEN

> AILEN es el nombre estable del proyecto/plataforma. La identidad visible del personaje se configura por instalación.

## R0 — Definición de producto — CERRADO (verificación legal queda para precomercial)

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
- [x] Elegir stack técnico inicial mediante ADR (`ADR-006`, baseline provisional aceptado; benchmarks de hardware final siguen abiertos).

## R1 — Bootstrap del repositorio y prototipo base — OBJETIVO 0.1.x

- [x] Inicializar Git local y configurar remoto `origin`.
- [x] Definir `pyproject`/dependencias baseline.
- [x] Crear CLI de diagnóstico de hardware.
- [x] Detectar RAM, CPU, arquitectura, audio, cámara y display best-effort.
- [x] Definir formato de configuración local.
- [x] Implementar logging estructurado y redactado.
- [→ R6] Servicio systemd/watchdog del appliance: se implementa junto con provisioning y rollback, no como deuda separada de R1.
- [x] Implementar runtime state/health básico.
- [→ R6/R10] Instalación Debian 13 minimal y procedimiento físico Banghó se documentan con el appliance/prototipo real.
- [→ R10] Benchmark base de Banghó se registra únicamente cuando el prototipo físico esté disponible y medido.

## R2 — Presencia física: rostro, cámara y audio — CERRADO EN LAB / BASELINE 0.4.x

- [x] Seleccionar backend gráfico baseline de laboratorio mediante POC/ADR (portrait/Tkinter + headless; backend appliance definitivo queda para R6/R7).
- [x] Implementar rostro 2D minimalista y renderer portrait raster.
- [x] Estados `IDLE`, `ATTENTION`, `LISTENING`, `PROCESSING`, `SPEAKING`, `SLEEP`.
- [x] Parpadeo y microanimaciones no deterministas.
- [x] Detección simple de persona/rostro (YuNet baseline, Haar experimental).
- [x] Seguimiento de coordenadas con pupilas/mirada normalizada.
- [x] Captura de micrófono y VAD/turn gate; wake word dedicado sigue siendo opcional.
- [x] STT local baseline (Vosk + alternativa Whisper.cpp).
- [x] TTS local baseline (Piper Python incremental).
- [x] Sincronización aproximada de boca por energía RMS; lip-sync fonémico queda para FacePack.
- [x] Selección de dispositivos audio/cámara, USB/RTSP y hot-plug best-effort.
- [x] Primer ciclo completo: ver → escuchar → responder → hablar, validado en laboratorio físico ASRock.

## R3 — Cerebro híbrido, memoria e identidad — CERRADO / BASELINE 0.4.x

- [x] Implementar AI Router.
- [x] Implementar backend local pequeño.
- [x] Implementar proveedor cloud rápido y económico mediante interfaz genérica.
- [x] Implementar LAN Brain opcional.
- [x] Fallback automático por disponibilidad.
- [x] Presupuesto diario/mensual configurable.
- [x] Métricas de tokens/costo/latencia.
- [x] SQLite inicial.
- [x] Sesiones y mensajes.
- [x] Memorias explícitas.
- [x] FTS5.
- [x] Construcción de contexto mínimo para cloud.
- [x] Personality Engine v1.
- [x] Semilla persistente de personalidad.
- [x] Modos sociales `WORKSHOP`, `SHOP`, `HOME`, `PUBLIC`, `PRIVATE`.
- [x] Evitar exposición de memoria privada en modo público.
- [x] Hacer estricta la desactivación local: `ai.local.enabled=false` no toca
  runtimes ni inferencia local y nunca agrega fallback oculto.
- [x] Proveedores externos intercambiables con prioridades reales, streaming
  declarado por capacidad, privacidad de turno actual y degradación honesta.
- [x] Unificar Ollama y llama.cpp bajo `AiBackend`/`StreamingAiBackend`, con
  llama.cpp administrado de carga bajo demanda y liberación ociosa por presión.
- [x] Conservar evidencia STT hasta Core y bloquear sólo tools con efecto cuando
  el turno llega cortado o con confianza acústica insuficiente/desconocida.
- [x] Solapar streaming real LLM -> segmentación segura -> TTS incremental con
  cola bounded y cancelación de barge-in, sin empalmar fallback tras audio parcial.
- [x] Devolver charla abierta y saludos al LLM; el resolver determinista queda
  acotado a routing, tools verificables, errores y repreguntas STT.
- [ ] Validar el baseline local-first en equipos reciclados objetivo: GGUF Q4
  pequeño, modelo persistente, streaming a primera frase y margen simultáneo
  para Vosk/Piper/SQLite/rostro. ASRock no es criterio de suficiencia.
- [ ] Comparar físicamente WebRTC VAD modo 2/3 y cierres 380/500/600 ms sin
  guardar audio real; no cambiar defaults por simulación.
- [ ] Medir barge-in humano, cola limpia, transcript preservado, eco real y
  cancelación/latencia Piper en hardware objetivo.
- [x] Implementar harness RAM-only para esa matriz y barge-in guiado, con
  WER/CER, confianza, onset/offset, truncamiento, stop y drain separados; la
  ejecución física sigue pendiente.
- [x] Definir calificación versionada de modelos `candidate/qualified/rejected`
  y ranking por evidencia/calidad dentro del envelope, sin descargar pesos.
- [x] Generar `ProvisioningPlan` por hardware y calificación objetivo: runtime,
  modelo, contexto, offload, reservas, descarga verificada y consentimiento;
  los perfiles Lab describen topología y no fijan el modelo. Runtime y offload
  requieren evidencia propia por hardware/modelo/runtime; soporte declarado no
  se usa como sustituto.
- [x] Quitar el techo fijo de workstation: 16/32/64+ GB y GPU dedicada usan
  reserva dinámica, contexto escalonado y el mejor modelo target-qualified que
  entra. El factory exige el mismo runtime calificado y rechaza candidatos
  automáticos.
- [x] Reemplazar `cloud` único por remotos nombrados y streaming real Responses,
  Chat-compatible y Anthropic. AGY/OpenCode quedan retirados del producto; los
  presets de API no se consideran probados sin clave/benchmark consentido.
- [x] Implementar captura PipeWire default/target explícito y DSP liviano de
  NS + ganancia dB/AGC con gate/hold/limitador más calibrador RAM-only y métricas
  raw/por etapa/final; AEC continúa pendiente.
- [ ] Comparar APIs opcionales de baja latencia por TTFT, calidad oral, cuota y
  costo; no elegir por nombre de modelo o tokens/s publicados.

## R3B — Lab Mode y runtime local adaptativo — OBJETIVO 0.3.x

- [x] `ailen lab start` sin cambios persistentes del SO ni dependencias de root/services.
- [x] soporte de laboratorio explícito para Linux Mint y Windows 11.
- [x] normalizar detección multiplataforma de CPU/RAM/GPU/VRAM/disco/audio/cámara/display sin inventar capabilities desconocidas.
- [x] Model Catalog versionado con artefactos aprobados y hashes; Qwen 3.5 0.8B Q4_0/Q8_0 verificados el 2026-08-21.
- [x] Model Planner explicable por hardware/perfil y clasificado por propósito (`SANITY`, `BALANCED`, `QUALITY`).
- [x] descarga segura con consentimiento explícito en Lab Mode, HTTPS + tamaño exacto + SHA-256 + rename atómico.
- [x] ModelStore local por plataforma, separado de Git y con protección de path traversal.
- [x] `LabComponentFactory` sin sustituciones fake silenciosas en modo real (`--simulate` para offline/UI tests).
- [x] cableado conversacional de software en `LabRunner`: Vision/Audio/STT/Router/LLM/TTS validados físicamente sin fakes; Face GUI Tkinter ya abre en Lab; queda repetir interacción completa tras mejorar STT/cámara.
- [x] inventario de modelos en runtime `RuntimeModelInventory` y runtime gestionado `ManagedLlamaRuntime`.
- [x] telemetría y métricas de sesión `LabSessionMetrics` exportadas a `runtime/lab/session_<timestamp>.json` con medición de Time To First Audible Response (TTFAR).
- [x] asistente `ailen lab prepare-ai` y diagnóstico con remediaciones `ailen lab doctor [--json]`.
- [x] R3B.3 catálogo declarativo de modelos de voz (`SpeechAssetCatalog`), store seguro y preflight físico exhaustivo (`LabPreflightChecker`).
- [x] R3B.4 inferencia adaptativa (`InferenceProfile`), política de residencia de modelos (`ModelResidencyPolicy`), prohibición de model hopping y arnés `ailen lab benchmark-ai`.
- [x] R3C boundary de herramientas controladas integrado; música queda sólo como contrato/routing hasta configurar backend físico real.
- [x] arnés `ailen lab benchmark-vision` (latencia CPU por frame del detector real, detecciones, confianza y gaze por fase, reporte JSON) — YuNet ~49 ms avg / p95 ~91 ms a 5 FPS en Ryzen 5500.
- [x] arnés `ailen lab benchmark-stt` (Vosk vs whisper.cpp sobre mismos WAVs, WER con normalización española, `NOT_INSTALLED` sin descargas).
- [ ] decidir reemplazo/migración de STT según WER medido en utterances reales de G600 (whisper.cpp requiere instalación manual de binario + ggml).
- [x] abrir Face GUI + cámara/audio/LLM/TTS en Linux Mint; queda mejorar STT y repetir prueba de experiencia completa con hardware de cámara mejor.
- [ ] validar después el segundo laboratorio en Windows 11.
- [ ] registrar benchmarks reales de los equipos laboratorio sin confundirlos con hardware objetivo comercial.

## R4 — Herramientas y comportamiento útil — OBJETIVO 0.3/0.4.x

- [ ] Reproducción musical física real mediante `MusicService`; `MusicTool`/routing ya existen pero default es `UNAVAILABLE`.
- [x] Volumen/play/pause/timer/hora/status sin LLM (`RULE_ONLY_TOOL` fast-path).
- [x] Notas con persistencia SQLite parametrizada (`NotesTool`).
- [x] Recordatorios persistentes SQLite + scheduler interno/eventos; anuncio audible físico aún se valida como deuda de R4.
- [ ] Información del negocio/FAQ estructurada.
- [x] Búsqueda web desacoplada de proveedor (`WebSearchProvider`, `WebSearchTool`).
- [x] Fetch/extracción web controlada con defensas anti-SSRF y allowlist (`WebFetchPolicy`, `WebFetchTool`).
- [x] Hora mediante backend local determinista (`ClockTool`).
- [x] Saludo automático con cooldown/debounce mediante SocialEngine/InteractionCoordinator.
- [x] Comportamiento social configurable por modos y privacidad.
- [x] Derivación/fallback segura por router, degradación y respuestas de capacidad basadas en estado real.
- [x] Tool permission model y barrera de SocialMode/PrivacyLevel (`ToolExecutor`).

## R5 — Panel web responsive — PARCIAL FUNCIONAL / INTEGRACIÓN DE DATOS REALES 0.4.x

- [x] Login local con hash robusto.
- [x] Sesiones y expiración.
- [x] Rate limit/lockout.
- [x] Dashboard responsive.
- [x] Estado de hardware.
- [ ] Configuración de red dedicada: `/config` ya persiste campos reales, pero vistas especializadas todavía deben leer siempre el valor efectivo.
- [ ] Información del comercio.
- [x] Voz y audio.
- [ ] Cámara y presencia: backend/API existen; la vista `/vision` todavía precarga varios defaults hardcodeados.
- [x] IA/proveedores/presupuesto.
- [ ] Personalidad y evolución: Core existe; la vista `/personalidad` todavía presenta valores de maqueta.
- [x] Recuerdos explícitos administrables en `/memoria`: búsqueda literal paginada, CRUD y exportación JSON real con privacidad y confirmaciones.
- [ ] Administración integrada de notas y recordatorios desde el panel.
- [ ] Conversaciones e historial.
- [x] Diagnóstico: health del proceso, LabDoctor a pedido y telemetría del último reporte Lab finalizado con procedencia/muestras/fecha; faltantes explícitos.
- [ ] Estado entre procesos en vivo y visor de logs redactados.
- [ ] PWA opcional.
- [ ] Primera experiencia de setup desde celular.
- [x] `/actualizaciones` autenticado consume el servicio firmado y muestra
  lifecycle/progreso redacted en `LAB_SIMULATION`; activación Appliance real
  permanece en R6.


## R5B — FacePack realista extensible — OBJETIVO 0.4/0.5.x

- [x] Capturar/generar un corpus inicial amplio de expresiones H3 sin integrarlo todavía al Core.
- [x] Clasificar visualmente los 85 videos; manifiesto trazable con frames/defectos/decisión. Recorte temporal se aplica al compilar, sin borrar fuentes.
- [x] Separar estados persistentes (`idle/waiting/attentive/listening/processing/sleeping`), microacciones, emociones, emociones intensas y speech.
- [x] Definir FacePack v1 binario, versionado, checksummed y externo al engine/wheel.
- [x] Sustituir loops idle/listening por base + espera variable + microacción + retorno, con RNG determinista para tests.
- [x] Implementar anchors y entradas/salidas curadas; `transition_*`, prioridad y retorno visual compatible tienen ejecución real sin cambiar el estado semántico de Core.
- [x] Mantener speech semánticamente separado de emoción. La prueba física rechazó capas ROI derivadas de clips H3 completos por deformar identidad; FacePack 1.6 selecciona speech full-frame limpio y retoma el affect al finalizar. ROI queda disponible para futuras fuentes realmente segmentables; visemas fonémicos siguen pendientes por falta de ground truth.
- [x] Implementar engine C++17/C ABI + wrapper `ctypes` desacoplado de Core y degradación limpia a headless.
- [x] Demostrar Pack A -> Pack B con emoción nueva sin recompilar la misma `.so`.
- [x] Establecer `facepack` como default; `portrait` queda legacy manual, `pixel` manual para hardware/display muy limitado y ningún fallo selecciona otro renderer.
- [x] Benchmark ASRock/Linux del engine, pack y transporte Tk; no extrapolado.
- [ ] Compilar/probar físicamente `ailen_face_engine.dll` en Windows y validar packaging de releases.
- [ ] Medir perfil LOW real en Raspberry/Banghó/SF20BA antes de fijar resolución/calidad o soporte.
- [x] Probar físicamente ROI normalizado de ojos/cejas/boca y retirar esas capas del pack H3 al confirmar deformación entre identidades; blink/gaze/speech actuales reproducen frames completos limpios. El engine conserva composición ROI para futuros assets preparados como capas.
- [x] Preservar movimiento full-frame authored y eliminar regresos abruptos mediante frames reales reversibles, sin crossfade ni doble rostro.

## R5C — Agente de Core y voz en vivo — OBJETIVO 0.5.x (ADR-014, ADR-015)

- [ ] Contrato de niveles de autonomía en `ToolRegistry`/`ToolExecutor` (N1–N3) con tope por instalación y por `SocialMode`.
- [ ] Bucle de agente en Core con presupuesto de pasos/tiempo/tokens, cancelación por voz y panel, y confirmación humana para acciones destructivas o externas.
- [ ] N2 archivos: raíces autorizadas, anti traversal/symlink, respaldo o papelera, tests de seguridad.
- [ ] N3 navegador aislado: perfil efímero, contenido web como dato no confiable, confirmación para formularios/compras/login.
- [ ] Proveedor `remote_realtime:<id>`: adaptador WebSocket, opt-in con aviso de privacidad, barge-in, `BudgetPolicy`, fallback a cascada de texto; medir TTFT/TTFAR antes de declarar calidad.
- [ ] Web Admin: raíces autorizadas, nivel máximo, historial de acciones y cancelación.
- [ ] Provisioning: ofrecer realtime remoto cuando el hardware no sostiene LLM local, con aviso de costo/privacidad.
- N4 (shell/computer-use general) queda fuera de alcance y exige ADR nuevo.

## R6 — Instalación appliance y actualizaciones — OBJETIVO 0.5.x

- [x] Vertical 1 Lab: manifiesto exacto firmado con Ed25519, fuente HTTPS
  acotada, downloader reanudable, CAS inmutable, journal y un worker.
- [x] Vertical 1 Lab: extracción tar segura, switch atómico, probation y
  rollback verificados end-to-end sólo bajo raíces temporales inyectadas.
- [x] Configuración/factory side-effect-free y servicio `DISABLED` honesto ante
  fuente/trust incompletos o modo Appliance todavía no implementado.
- [ ] Implementar `ailen-updaterd` y el contrato mínimo de activación
  privilegiada; Core/Web nunca reciben shell ni paths elegidos por request.
- [ ] Crear pipeline productivo de firma/custodia de claves y bundle offline.
- [ ] Probar corte de energía, disco lleno y rollback en un appliance físico.

- [ ] Provisionador Debian 13 minimal idempotente y auditable.
- [x] Detección y plan automático de `DeviceProfile`/modelo sin descargas; falta
  ejecutar la activación consentida dentro del provisionador Debian real.
- [x] Vertical Lab del puente plan -> activación: manifiesto local atómico,
  target-qualified y verificado por hash, estable entre sesiones; falta que el
  provisionador Debian ejecute esa acción tras instalar runtime/artefacto.
- [ ] Usuario/grupo dedicado y permisos de hardware.
- [ ] Arranque directo a AILEN sin login interactivo obligatorio.
- [ ] Mantener vía de recuperación administrativa segura.
- [ ] Sin entorno de escritorio pesado.
- [ ] Configurar suspensión/hibernación, política de tapa y blanking para appliance.
- [ ] Ejecutar en appliance el `ProvisioningPlan` consentido e instalar sólo
  modelos calificados por clase de hardware y artefactos HTTPS/hash/licencia.
- [ ] Self-test/health check antes de marcar instalación completa.
- [ ] Reinicio automático al finalizar provisionado exitoso.
- [ ] Primer boot entra directamente a la experiencia AILEN.
- [ ] Servicios systemd y watchdog.
- [ ] Separar releases de datos persistentes.
- [ ] Manifest por arquitectura/perfil.
- [x] SHA-256 y firma/verificación Ed25519 demostrados en Vertical 1 Lab; falta
  pipeline de firma productivo.
- [ ] Canales `nightly`, `beta`, `stable`.
- [x] Health probation post-update simulada; health real del appliance pendiente.
- [x] Rollback automático simulado; rollback físico/power-loss pendiente.
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
