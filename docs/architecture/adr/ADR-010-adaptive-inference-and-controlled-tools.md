# ADR-010 — Inferencia adaptativa y herramientas controladas

**Estado:** Accepted, enmendado el 2026-08-31
**Fecha:** 2026-08-22

## Contexto

AILEN debe funcionar tanto en workstations con GPU como en notebooks/netbooks sin GPU. La RTX 3060 del laboratorio no es un requisito del producto. Además, la experiencia comercial debe requerir la menor configuración posible y las acciones cotidianas no deben depender de un LLM.

## Decisión

### 1. El asistente no es el LLM

Identidad, personalidad, memoria, permisos, tools, privacidad y políticas viven en AILEN Core. El modelo local/LAN/cloud es un recurso reemplazable.

### 2. Selección adaptativa de inferencia

AILEN selecciona un perfil al instalar/iniciar según hardware medido:

- **RULE_ONLY / SATELLITE:** reservado para nodos por debajo del envelope local
  medido (por ejemplo 2 GB); Core + tools, con LAN/cloud opcional. No es el
  baseline autónomo objetivo de 4/8 GB.
- **FAST:** modelo local pequeño orientado a diálogo (aprox. 1B–4B) sobre CPU o GPU modesta.
- **BALANCED:** modelo local medio cuando RAM/CPU/GPU lo permiten.
- **QUALITY:** modelo mayor en hardware capaz, nunca requisito del producto.

No se cambia de modelo por turno: el cambio puede provocar cold-start, swapping o expulsión de VRAM/RAM. Se elige un modelo estable por nodo/sesión y se mantiene residente de forma acotada.

Los umbrales concretos son resultado de benchmark por hardware y pueden cambiar sin alterar esta ADR.

El planner no elige siempre el artefacto menor. Primero descarta lo que no
cumple plataforma, formato, cuantización, CPU/GPU, contexto y reserva de memoria;
dentro de ese envelope ordena por `qualified/candidate/rejected`, evidencia de
benchmark y `quality_rank`, conservando un candidato menor de fallback. El flujo
versionado y fail-closed está en `docs/hardware/LOCAL_MODEL_QUALIFICATION.md`.

Para el producto 4/8 GB, la capacidad de operar completamente local es un
requisito. `ai.local.enabled=false` sigue siendo una elección estricta y válida de
una instalación remota/híbrida; no significa que la distribución carezca de
Ollama/llama.cpp. Los envelopes y evidencia se documentan en
`docs/hardware/LOCAL_MODEL_QUALIFICATION.md`.

La ruta canónica de instalación es:

`HardwareCapabilityReport -> InferenceRecommendation -> ModelPlanner ->`
`HardwareQualificationStore -> ProvisioningPlan -> consentimiento -> descarga`
`HTTPS verificada -> activación`.

`ProvisioningPlan` registra clase/tier de hardware, topología, runtime, modelo
primario y fallback, contexto, offload, reservas RAM/VRAM, descarga/disco,
licencia, calificación, assets y acciones sujetas a consentimiento. Una
calificación es específica de `(hardware_class, model_id, runtime)`; una
medición ASRock no se hereda a 4/8 GB y una medición llama.cpp no habilita
Ollama sólo porque el descriptor soporte ambos. Cuando varios runtimes tienen
evidencia, compiten por calidad, TTFA, throughput y RSS/VRAM medidos dentro del
envelope. El dispositivo y el offload también deben coincidir con la ejecución
calificada: sin evidencia GPU el plan declara CPU y `gpu_layers=0`. Un artefacto
`candidate`, aun con URL y hash válidos, sólo puede aparecer como sugerencia.
Para instalar debe ser `qualified` en la clase/runtime objetivo y mantener
margen para OS, Core, Vosk, Piper, FacePack y buffers. Si no existe uno, el plan
propone LAN/remoto/Core degradado y no finge capacidad local.

Los perfiles Lab describen topología, no fijan modelos. Un override manual sólo
se honra si el artefacto ya está calificado para ese hardware y cabe en el
envelope; nunca convierte un candidato en producción.

Los tiers 16/32/64+ son etiquetas explicativas, no techos de modelo. El envelope
reserva el mayor valor entre un piso por banda y 15% de RAM total, usa la RAM
disponible restante y sólo cuenta VRAM dedicada disponible. Así, hardware
potente puede elegir un modelo de mayor calidad calificado sin heredar el límite
de una netbook. La activación conserva el runtime exacto del plan; compatibilidad
de formato no permite cruzar evidencia llama.cpp/Ollama. El runtime permanece
estable durante la sesión y sólo se reconsidera en provisioning/reconfiguración
o cambio de hardware deliberadamente detectado.

El resultado consentido se persiste como una selección local atómica y acotada,
no como una nueva inferencia del planner en cada turno. El registro incluye
clase de hardware, runtime, modelo, contexto, ejecución/offload y SHA-256; sólo
se crea después de verificar el artefacto exacto. El runtime lo consume cuando
local está explícitamente habilitado y no hay override. Un archivo inseguro,
corrupto, de otra clase de hardware o con artefacto distinto falla cerrado. La
mera existencia de un candidato o de otro runtime sano no lo sustituye.

### 2.1 Semántica de `provider=auto`

`auto` no equivale a reproducir una lista fija de prioridades. Core elige primero
la clase de capacidad según privacidad, disponibilidad, modalidad, complejidad y
latencia observada. En voz casual puede priorizar local o LAN de baja latencia;
una tarea difícil puede escalar a un externo permitido. Las prioridades ordenan
pares equivalentes y fallbacks. Un proveedor explícito sigue siendo preferido si
es elegible. `ai.local.enabled=false` excluye local antes de esta decisión.

Un adapter medido como no apto para realtime no se promueve automáticamente a
primary de voz, aunque puede seguir como elección explícita o fallback de
capacidad. Esa clasificación es evidencia de una versión/ruta concreta, no una
propiedad eterna del proveedor.

### 2.2 Turno de voz y cancelación

La confianza STT real se conserva hasta Core en bandas `noise`, `doubtful`,
`conversation` y `action`; ausencia de confianza queda `unknown` y nunca se
inventa. El piso de una acción con efectos es independiente y más estricto.

Cada respuesta hablada recibe `turn_id` y `generation_id`. Barge-in detiene
playback y cancela lógicamente la generación; los resultados de generaciones
viejas se descartan. Un backend TTS no concurrente se serializa. Si ONNX ya está
dentro de `synthesize()`, puede terminar en background, pero no volver a encolar
PCM. Los joins son acotados y se mide por separado playback detenido y
sintetizador drenando. Una respuesta interrumpida/parcial no se persiste como
mensaje assistant completo.

### 3. Acciones básicas son deterministas

Hora, timer, volumen, reproducción de música, pause/resume/next, notas, estado del sistema y otras acciones simples se ejecutan como tools allowlisted. No requieren inferencia si el intent es inequívoco.

El LLM nunca recibe shell general, root, subprocess arbitrario ni acceso irrestricto a archivos.

### 4. Internet mediante tool controlada

El modelo no obtiene acceso directo e irrestricto a Internet. AILEN Core expone `web_search` / `web_fetch` controlados con:

- proveedor intercambiable;
- timeouts y límites de tamaño/resultados;
- sanitización de contenido;
- bloqueo de esquemas/hosts peligrosos según política;
- privacidad outbound;
- telemetría sin contenido privado;
- presupuesto cuando el proveedor es de pago.

El LLM recibe resultados estructurados/sanitizados y elabora una respuesta.

Los disparadores del parser semántico se declaran en cada tool. Nombres,
descripciones, valores de schema y palabras temporales genéricas no se convierten
automáticamente en triggers: hacerlo causó una segunda inferencia serial en charla
cotidiana. El historial sólo se entrega después de que el texto actual abre ese
gate; nunca lo abre por sí mismo. En ASRock, `muy bien` tras un turno de hora pasó
de una inferencia semántica de 1.3–1.7 s a `attempted=false` en 0.3 ms; el turno
textual real completo midió 1.354 s bajo la carga coexistente observada. Para
información cambiante no cubierta por una regla inequívoca queda
pendiente evaluar un plan estructurado del mismo modelo conversacional (respuesta
o tool request) contra un dataset local antes de reemplazar el routing actual.

La guía especializada del parser también pertenece a cada tool mediante
`intent_guidance`; el resolver sólo incluye la guía de las candidatas del turno.
Así, una consulta web no paga tokens por reglas de Notes. En ASRock el prompt del
parser Web bajó de 416 a 318 tokens y una muestra pasó de 1.549 s a 1.374 s antes
de incorporar el contrato fechado de noticias.

`WebSearchRequest` distingue búsqueda general (`text`) de noticias (`news`) y
puede acotar frescura a día/semana/mes. Los resultados de noticias transportan
`published_at` hasta la síntesis; Core descarta noticias sin timestamp ISO válido,
futuras por más de cinco minutos o fuera de la ventana solicitada antes del LLM.
El default conversacional es tres resultados porque Core sólo proyecta tres al
modelo. DDGS medido con cinco resultados tuvo mediana 2.766 s y con tres 1.515 s
en tres muestras por variante; la red externa sigue siendo variable. «Sin
resultados» es una búsqueda vacía válida, no un error ni permiso para improvisar
actualidad.

### 5. Híbrido como configuración de producto

El onboarding detecta hardware y propone automáticamente el modo recomendado:

- Local-only;
- Local + LAN Brain;
- Local + Cloud fallback;
- Cloud/Satellite;
- Rule-only cuando no hay inferencia disponible.

El usuario/cliente debe aprobar descargas, credenciales y servicios de terceros. Costos externos se muestran de forma explícita y corren por cuenta del cliente salvo que exista un plan comercial propio que los incluya.

### 6. Configuración mínima para el cliente

El instalador/provisionador debe encargarse de detección, elección de perfil, descarga verificada de assets/modelos aprobados, prueba de audio/cámara, configuración inicial y health check. El cliente sólo debería elegir opciones de producto (nombre/voz/privacidad/proveedor) y aportar credenciales cuando corresponda.

## Consecuencias

- AILEN puede funcionar sin GPU.
- Un equipo de 2 GB puede seguir siendo útil como Satellite/Cloud.
- El mismo Core funciona con modelos 1B, 3B, 4B, 9B o proveedores remotos.
- La calidad de conversación puede variar por hardware sin perder identidad ni tools.
- Web y acciones quedan auditables y revocables independientemente del modelo.

## Modelos de laboratorio candidatos (no baseline comercial todavía)

- Qwen3.5 9B: QUALITY en Asrock, validado físicamente con thinking desactivado.
- Llama 3.2 3B: candidato FAST por diálogo multilingüe/español y tool use; requiere benchmark físico.
- Gemma 3 4B: candidato BALANCED/FAST de mayor calidad; requiere benchmark físico.
- Qwen3.5 4B: candidato BALANCED con `think=false`; requiere benchmark físico.

Ningún candidato se convierte en requisito hasta benchmark y revisión de licencia/distribución.
En el catálogo actual sólo Qwen 3.5 0.8B Q4_0/Q8_0 tiene identidad de descarga
HTTPS y SHA-256 verificada, pero permanece `candidate`: no existe todavía ningún
modelo globalmente instalable ni calificado para una clase comercial 4/8 GB.
