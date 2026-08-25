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

AILEN está en `0.1.0-dev.0` con Foundation/Core/Web, Face/Vision, Audio/STT/TTS, AI Router adaptativo y R3C Controlled Tools integrados. El baseline actual supera 500 tests. La prioridad de software pasa a R4 sin fingir validaciones físicas: backend musical local/MPRIS, proveedor WebSearch real y robustez de instalación limpia; STT G600/Whisper y hardware objetivo se validan sólo en los equipos físicos correspondientes.

## Reglas esenciales

- La identidad del asistente no pertenece al LLM.
- Memoria, personalidad, preferencias, reglas y permisos pertenecen a AILEN Core.
- Un proveedor cloud, modelo local o LAN Brain debe ser reemplazable.
- Ningún LLM recibe shell general ni acceso irrestricto al sistema.
- Las herramientas se implementan mediante contratos explícitos y allowlist.
- No versionar API keys, tokens, contraseñas, grabaciones reales, datos de clientes ni memoria privada.
- No enviar historial completo a proveedores cloud; construir contexto mínimo.
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

## Cierre mínimo de cada cambio

1. Código y documentación coherentes.
2. Tests proporcionales al riesgo.
3. Benchmark si el cambio afecta rendimiento.
4. Sin secretos ni datos reales.
5. ADR/roadmap/changelog/memoria actualizados si corresponde.
6. Diff revisado.
7. No push sin autorización.
