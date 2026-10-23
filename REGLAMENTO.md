# Reglamento del proyecto — AILEN

Documento de normas internas del proyecto.

## Principios

- Mantener código y documentación coherentes: todo cambio, decisión y delegación a agentes se documenta en el mismo lote de trabajo.
- El uso de AGY y OpenCode para delegar auditorías, revisiones y tareas acotadas es obligatorio (ahorro de tokens y agilidad).
- Usar versionado semántico.
- Registrar cambios relevantes en `CHANGELOG.md`.
- Documentar decisiones estructurales mediante ADR.
- Probar el hardware antes de declararlo soportado.
- Mantener datos persistentes separados de las releases.
- No crear commits ni publicar cambios sin autorización del propietario.
- Revisar dependencias nuevas por consumo y compatibilidad con Debian 13.
- Agentes auxiliares de desarrollo: además de Codex se usan AGY (Gemini, `agy -p`) y OpenCode con modelos DeepSeek gratuitos (`opencode run --model opencode/deepseek-v4.1-flash-free`). Son sólo herramientas de desarrollo, no proveedores runtime del producto; siguen las mismas reglas (sin commit/push, sin secretos ni datos privados, sin flags de auto-aprobación sin autorización, diff revisado por el agente principal). Detalle en `AGENTS.md`.
- `AILEN` es el nombre estable del proyecto/plataforma; la disponibilidad marcaria/legal se verifica antes de comercialización formal y no cambia la separación entre plataforma e identidad visible del personaje.
