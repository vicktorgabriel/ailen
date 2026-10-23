# Registro de sesiones de agentes — AILEN

## Codex canónico

- Proyecto: AILEN
- Thread ID: `01a03a1f-e86e-7213-9581-af295af5c7f1`
- Estado: activo/canónico; reanudar siempre, no hacer fork.
- Agente principal: Codex Sol Max (`gpt-5.6-sol`, configuración predeterminada actual).
- Agente de implementación: Codex Luna (`gpt-6-luna`, esfuerzo alto) para módulos acotados y correcciones.

```bash
# Arquitectura, migraciones, auditoría extensa
scripts/resume_codex_ailen.sh sol

# Implementación acotada, UI, docs, regresiones
scripts/resume_codex_ailen.sh luna
```

Cambiar el modelo al reanudar no crea otro chat. Luna debe recibir los tests concretos; Sol revisa los cambios
transversales y el cierre completo. No usar `codex fork`, `codex exec` ni una sesión nueva para
continuar AILEN salvo autorización explícita del usuario.
