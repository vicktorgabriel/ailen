# Registro de sesiones de agentes — AILEN

## Codex canónico

- Proyecto: AILEN
- Thread ID: `01a03a1f-e86e-7213-9581-af295af5c7f1`
- Estado: activo/canónico; reanudar siempre, no hacer fork.
- Agente principal: Codex Sol Max (`gpt-5.6-sol`, configuración predeterminada actual).
- Agente auxiliar: Codex Spark (`gpt-5.3-codex-spark`) para tareas acotadas. El subagente de proyecto es `spark_worker` en `.codex/agents/spark_worker.toml`.

```bash
# Arquitectura, migraciones, auditoría extensa
scripts/resume_codex_ailen.sh sol

# Ediciones focales, UI, docs, regresiones pequeñas
scripts/resume_codex_ailen.sh spark
```

Cambiar el modelo al reanudar no crea otro chat. Sol también puede delegar a
`spark_worker` dentro del mismo thread canónico; el child thread devuelve un resumen
al principal. Spark debe recibir los tests concretos; Sol revisa los cambios
transversales y el cierre completo. No usar `codex fork`, `codex exec` ni una sesión nueva para
continuar AILEN salvo autorización explícita del usuario.
