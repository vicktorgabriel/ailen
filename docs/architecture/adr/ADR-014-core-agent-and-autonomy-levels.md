# ADR-014 — Agente de Core y niveles de autonomía

**Estado:** Accepted (2026-10-23)
**Fecha:** 2026-10-23
**Contexto:** El objetivo de AILEN es un asistente tipo Alexa que, además de
conversar, pueda operar el equipo siguiendo instrucciones: ejecutar herramientas
locales y de red, navegar y modificar archivos locales, como lo haría una persona
frente al equipo. Hasta ahora `AGENTS.md`, `PRODUCT.md` (§9) y `ARCHITECTURE.md`
prohíben shell libre y acceso irrestricto del LLM. Esta decisión no levanta esas
prohibiciones: define un modelo de autonomía por niveles que las respeta.

## Decisión

1. **El agente vive en Core.** AILEN Core ejecuta el bucle
   plan → acción → observación con el LLM disponible (local, LAN o
   `remote:<id>`). El LLM sólo propone acciones; cada acción se valida y ejecuta
   mediante `ToolExecutor` con schema, permisos por `SocialMode`, timeout y
   auditoría en `tool_events`. Identidad, memoria y permisos permanecen en Core
   (ADR-002). No se delega el control a un CLI de agentes externo.
2. **Niveles de autonomía.** Cada herramienta declara su nivel; el admin fija el
   nivel máximo por instalación y por `SocialMode`:
   - **N1 — Tools con schema** (hoy: hora, timer, volumen, música, notas,
     recordatorios, web_search/web_fetch, estado).
   - **N2 — Archivos acotados:** leer, listar, crear y modificar sólo dentro de
     raíces autorizadas por el admin. Resolución de rutas con `is_relative_to`,
     sin seguir symlinks fuera de la raíz. Escrituras sobrescriben vía copia de
     respaldo o papelera recuperable; borrado y sobrescritura masiva requieren
     confirmación humana.
   - **N3 — Navegador controlado:** perfil aislado y efímero, sin cookies ni
     sesiones del usuario. Leer páginas es libre dentro de la política SSRF de
     `web_fetch`; enviar formularios, comprar, publicar o autenticarse requiere
     confirmación humana. Todo contenido web es dato no confiable, nunca
     instrucción (mitigación de prompt injection).
   - **N4 — Shell o computer-use general: fuera de alcance.** Reabrirlo requiere
     un ADR nuevo con sandbox y evidencia.
3. **Confirmación humana.** Acciones destructivas o con efecto externo piden
   confirmación por voz o panel, con resumen de lo que se va a hacer. Una
   transcripción de baja confianza o truncada nunca confirma (reglas STT de R4).
   `SHOP`/`PUBLIC` limita el nivel máximo a N1 (las tools N1 conservan sus propios
   `allowed_modes` y nivel de privacidad; no se añade un bloqueo extra de efectos
   laterales N1, p. ej. volumen, que ya son decisiones de producto por modo).
4. **Presupuesto del bucle.** Máximo de pasos, tiempo y tokens por tarea; la
   tarea se puede cancelar por voz y desde el panel; sin agentes de larga
   duración sin supervisión en el MVP.
5. **Privacidad con proveedores remotos.** El LLM remoto recibe sólo la tarea
   actual y los resultados de herramientas necesarios, ya filtrados por
   `OutboundPrivacyPolicy`. Contenido de archivos clasificado como privado no
   sale a remotos sin opt-in explícito por raíz.
6. **Degradación.** Sin LLM capaz de tool-calling confiable, el agente se
   desactiva y quedan N1 deterministas. No se promete agente en un tier de
   hardware sin medición (ver AGENTS.md).

## Consecuencias

- `PRODUCT.md` §9 se actualiza: "shell libre" y "navegación autónoma general por
  escritorio" siguen fuera; archivos acotados y navegador aislado pasan a ser
  objetivo con gates.
- Nuevas herramientas N2/N3 se implementan una por una con contrato en
  `MODULE_CONTRACTS.md`, tests de path traversal, symlinks y prompt injection.
- La Web Admin necesita vistas reales de raíces autorizadas, nivel máximo,
  historial de acciones y cancelación (R5).

## Alternativas descartadas

- Delegar a un CLI externo (Claude Code, OpenCode, AGY): saca permisos y
  privacidad de Core.
- Shell general en sandbox como nivel inicial: riesgo desproporcionado para el
  MVP y sin evidencia de necesidad.
