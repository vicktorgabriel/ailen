# ADR-010 — Inferencia adaptativa y herramientas controladas

**Estado:** Accepted  
**Fecha:** 2026-08-22

## Contexto

AILEN debe funcionar tanto en workstations con GPU como en notebooks/netbooks sin GPU. La RTX 3060 del laboratorio no es un requisito del producto. Además, la experiencia comercial debe requerir la menor configuración posible y las acciones cotidianas no deben depender de un LLM.

## Decisión

### 1. El asistente no es el LLM

Identidad, personalidad, memoria, permisos, tools, privacidad y políticas viven en AILEN Core. El modelo local/LAN/cloud es un recurso reemplazable.

### 2. Selección adaptativa de inferencia

AILEN selecciona un perfil al instalar/iniciar según hardware medido:

- **RULE_ONLY / SATELLITE:** sin LLM local obligatorio; Core + tools, con LAN/cloud opcional.
- **FAST:** modelo local pequeño orientado a diálogo (aprox. 1B–4B) sobre CPU o GPU modesta.
- **BALANCED:** modelo local medio cuando RAM/CPU/GPU lo permiten.
- **QUALITY:** modelo mayor en hardware capaz, nunca requisito del producto.

No se cambia de modelo por turno: el cambio puede provocar cold-start, swapping o expulsión de VRAM/RAM. Se elige un modelo estable por nodo/sesión y se mantiene residente de forma acotada.

Los umbrales concretos son resultado de benchmark por hardware y pueden cambiar sin alterar esta ADR.

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
