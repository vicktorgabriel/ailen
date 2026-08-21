# Contribuir a AILEN

> Proyecto en etapa inicial. Las reglas podrán evolucionar antes de 1.0.

## Antes de trabajar

Leer `AGENTS.md`, `ARCHITECTURE.md`, `ROADMAP.md` y el ADR del subsistema afectado.

## Flujo recomendado

1. Definir un alcance pequeño y verificable.
2. Revisar si modifica una decisión arquitectónica.
3. Implementar sin mezclar refactors no relacionados.
4. Agregar o actualizar pruebas.
5. Medir rendimiento si afecta hardware objetivo.
6. Actualizar documentación/changelog cuando corresponda.
7. Revisar el diff completo.
8. Commit/push sólo cuando el propietario lo autorice.

## Criterios de calidad

- código modular;
- dependencias justificadas;
- errores observables;
- logs sin datos privados innecesarios;
- comportamiento degradable cuando un backend no está disponible;
- interfaces reemplazables para modelos/proveedores;
- pruebas que no dependan de hardware físico salvo suites manuales explícitas.

## Hardware

Los cambios que prometan menor consumo o nuevo soporte deben adjuntar mediciones de RAM, CPU y latencia en un equipo identificado.

## Documentación

Usar ADR para decisiones difíciles de revertir. `docs/memory/CURRENT_STATE.md` debe describir lo que realmente funciona hoy, no lo que está planeado.
