# Skills externas para desarrollo de AILEN

Las skills se instalaron a nivel proyecto desde https://skills.sh/ para Claude Code, Codex, Antigravity y OpenCode. El indice compartido es `.agents/skills/`, Claude usa tambien `.claude/skills/` y los origenes quedan en `skills-lock.json`.

## Uso recomendado

- Arquitectura y dominio: `codebase-design`, `domain-modeling`, `writing-for-agents`.
- Transferencia y descubrimiento: `handoff`, `find-skills`.
- Python y tests: `modern-python`, `python-testing`, `test-driven-development`, `property-based-testing`, `ai-regression-testing`.
- Diagnostico y verificacion: `systematic-debugging`, `verification-before-completion`, `differential-review`, `agent-architecture-audit`.
- Seguridad: `agent-security-hardening`, `stride-threat-modeling`, `supply-chain-risk-auditor`.
- IA y eficiencia: `cost-aware-llm-pipeline`, `performance-profiler`.
- Web: `frontend-design`, `web-design-guidelines`.

## Precedencia

Todas las skills son auxiliares y quedan subordinadas a `AGENTS.md`, `REGLAMENTO.md`, los ADR y contratos de arquitectura. No instalar dependencias adicionales ni nuevas skills sin revision; `find-skills` sirve para buscar, no habilita incorporacion automatica. Ninguna skill autoriza acciones irreversibles, commits, push, acceso a datos privados o ampliacion de permisos por si misma. No aplicar recomendaciones de migracion de herramientas, framework o estructura documental si contradicen las decisiones vigentes. Toda propuesta necesita diff revisado, pruebas proporcionales y documentacion segun el reglamento.

Las skills operan durante el desarrollo: no son dependencias del runtime Python ni del appliance. Las evaluaciones automatizadas de seguridad son indicativas, no garantias. La CLI reporto riesgo Snyk medio para `find-skills`; revisar futuras actualizaciones antes de ejecutarlas.
