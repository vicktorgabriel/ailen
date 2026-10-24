# AGENTS.md — AILEN

> AILEN es el nombre estable del proyecto/plataforma. El nombre visible del personaje es configurable por instalación.

## Lectura obligatoria

Antes de modificar código o arquitectura:

1. `README.md`
2. `REGLAMENTO.md`
3. `docs/memory/CURRENT_STATE.md`
4. `docs/context/PRODUCT.md`
5. `docs/context/PRODUCT_BEHAVIOR.md`
6. `docs/context/PLAN_MAESTRO.md`
7. `docs/context/IMPLEMENTATION_PLAN.md`
8. `ARCHITECTURE.md`
9. `docs/architecture/MODULE_CONTRACTS.md`
10. `ROADMAP.md`
11. `TASKS.md`
12. ADR relacionado con el subsistema a modificar.

## Estado actual

AILEN está en `0.4.0-dev.0` con Foundation/Core/Web, Face/Vision, Audio/STT/TTS, AI Router adaptativo, R3C Controlled Tools, recordatorios, proveedores externos y el Vertical 1 de updates firmados en Lab integrados. El baseline completo actual es de 1164 tests en verde, Ruff limpio, mypy limpio en 168 módulos fuente y wheel limpio de 211 entradas. R5B FacePack 1.6 es el renderer lógico por defecto; un fallo degrada a headless y nunca elige `portrait`/`pixel` automáticamente. La prioridad actual es consolidar R4/R5 y completar sus validaciones físicas; R6 Appliance Debian sigue siendo el siguiente hito estructural porque el daemon privilegiado de updates aún no existe.

## Continuidad de agentes Codex

- Thread canónico de AILEN: `01a03a1f-e86e-7213-9581-af295af5c7f1`. Reanudarlo; no hacer `fork` ni iniciar otro chat salvo pedido explícito del usuario.
- Codex Sol Max sigue siendo el agente principal para arquitectura, auditorías amplias, migraciones y cierre de gates.
- Codex Luna (`gpt-6-luna`, esfuerzo alto) es el agente de implementación del hilo canónico para módulos acotados y correcciones; debe recibir instrucciones explícitas de ejecutar los tests pertinentes antes de devolver el turno.
- Comandos y perfiles locales: `.agents/SESSION_REGISTRY.md` y `scripts/resume_codex_ailen.sh`. Cambiar de modelo no cambia de thread.

## Agentes auxiliares de desarrollo: AGY (Gemini) y OpenCode (DeepSeek free)

Orden vigente del propietario: además de Codex, el desarrollo usa estos dos CLIs como agentes auxiliares. Son herramientas de desarrollo; **no** son proveedores runtime de AILEN (AGY/OpenCode siguen retirados del producto, ver ADR-011 y `CURRENT_STATE.md`).

- **AGY (Gemini 3.8):** `agy -p "<prompt>" --model gemini-3.8-flash-high` (no interactivo). Para auditorías, revisión de docs y tareas acotadas. Usar `--mode plan` cuando sólo deba analizar y `--mode accept-edits` cuando deba escribir archivos.
- **OpenCode:** `opencode run --model <modelo> "<prompt>"`. Primero un modelo gratuito disponible (`opencode/*-free`); si el cupo gratuito está agotado, OpenCode Go (`opencode-go/deepseek-v4.1-flash` como opción intermedia). Autorizado por el propietario.
- Deben leer este archivo y `docs/operations/AGENT_HANDOFF.md` antes de actuar y reciben tests concretos a ejecutar antes de devolver el turno.
- Nunca reciben secretos, API keys, grabaciones, memoria privada ni datos de clientes. No usar `--dangerously-skip-permissions` ni `--auto` sin autorización explícita.
- Aplican las mismas reglas que el resto: sin commit ni push, sin borrar trabajo ajeno, sin cambios estructurales sin ADR.
- **Uso obligatorio:** el agente principal delega en AGY y OpenCode toda auditoría, revisión de diff, búsqueda amplia, redacción de tests de regresión y tareas acotadas, para ahorrar tokens y acelerar. Arquitectura, seguridad y cierre de gates los decide el principal.
- **Todo se documenta:** cada cambio, decisión y delegación se registra en el mismo lote (`TASKS.md`, `CURRENT_STATE.md`, `RECENT_DECISIONS.md`, `CHANGELOG.md`, ADR). Un cambio sin documentación no está cerrado.
- El agente principal revisa el diff de cualquier cambio que hagan antes de darlo por cerrado.

## Reglas esenciales

- La identidad del asistente no pertenece al LLM.
- Memoria, personalidad, preferencias, reglas y permisos pertenecen a AILEN Core.
- Un proveedor remoto, modelo local o LAN Brain debe ser reemplazable.
- Ningún LLM recibe shell general ni acceso irrestricto al sistema.
- Las herramientas se implementan mediante contratos explícitos y allowlist.
- No versionar API keys, tokens, contraseñas, grabaciones reales, datos de clientes ni memoria privada.
- No enviar historial completo a proveedores remotos; construir contexto mínimo.
- `SHOP/PUBLIC` no puede exponer memoria privada espontáneamente.
- La evolución de personalidad nunca modifica permisos o seguridad.
- El producto debe degradar capacidades, no colapsar, cuando Internet/LAN/modelos no están disponibles.
- Evitar dependencias pesadas si existe una alternativa suficientemente buena para el hardware objetivo.
- No introducir base vectorial, microservicios, Docker u otra complejidad sin evidencia de necesidad.
- Todo cambio estructural requiere ADR o actualización explícita del ADR correspondiente.
- Toda afirmación de soporte de hardware requiere benchmark o prueba real documentada.
- No declarar 2/4/8 GB como suficiente para una función sin medición en el equipo objetivo.
- No hacer push sin autorización explícita.
- No crear commits salvo pedido explícito o flujo acordado.
- No borrar ni sobrescribir trabajo ajeno.

## Prioridad del MVP

1. estabilidad;
2. latencia percibida;
3. privacidad;
4. bajo consumo;
5. mantenibilidad;
6. expresividad del rostro;
7. cantidad de funciones.

No agregar funciones espectaculares si empeoran las seis prioridades anteriores.

## Hardware de referencia

- Desarrollo/modelos: Ryzen 5 5500 + 48 GB + RTX 3060 12 GB.
- Prototipo: Banghó Zero G05, 8 GB RAM, M.2 500 GB.
- Optimización: SF20BA 8 GB → 4 GB.
- Satellite/Cloud: hardware 2 GB si las mediciones lo permiten.

La PC potente es laboratorio; no define los requisitos mínimos del producto.

## Fuentes canónicas

- Producto: `docs/context/PRODUCT.md`
- Alcance: `docs/context/PLAN_MAESTRO.md`
- Arquitectura: `ARCHITECTURE.md`
- Roadmap: `ROADMAP.md`
- Estado: `docs/memory/CURRENT_STATE.md`
- Decisiones recientes: `docs/memory/RECENT_DECISIONS.md`
- ADRs: `docs/architecture/adr/`
- Seguridad: `docs/security/`
- Hardware: `docs/hardware/`
- Deploy: `docs/deployment/`
- Testing: `docs/testing/`
- Plan operativo: `docs/context/IMPLEMENTATION_PLAN.md`
- Contratos: `docs/architecture/MODULE_CONTRACTS.md`
- Trabajo inmediato: `TASKS.md`
- Handoff de agentes: `docs/operations/AGENT_HANDOFF.md`

## Skills de desarrollo externas

- Las skills seleccionadas de skills.sh están descritas en `docs/operations/EXTERNAL_SKILLS.md` y registradas en `skills-lock.json`.
- Antes de invocar una skill, verificar su finalidad y aplicar primero las reglas de `AGENTS.md`, `REGLAMENTO.md` y los ADR vigentes.
- Las skills no autorizan por sí solas dependencias adicionales, cambios estructurales, acceso a secretos, instalación automática de otras skills, commits ni push.
- Usar solo las skills pertinentes a cada tarea; evitar aplicar múltiples guías superpuestas sin necesidad.

## Cierre mínimo de cada cambio

1. Código y documentación coherentes.
2. Tests proporcionales al riesgo.
3. Benchmark si el cambio afecta rendimiento.
4. Sin secretos ni datos reales.
5. ADR/roadmap/changelog/memoria actualizados si corresponde.
6. Diff revisado.
7. No push sin autorización.
