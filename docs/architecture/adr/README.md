# Architecture Decision Records

Los ADR documentan decisiones estructurales difíciles de revertir.

Estados válidos: `Proposed`, `Accepted`, `Superseded`, `Rejected`.

## Índice inicial

- `ADR-001-modular-core.md` — Core modular antes de distribuir procesos.
- `ADR-002-identity-independent-from-llm.md` — identidad independiente del LLM.
- `ADR-003-hybrid-ai-router.md` — router local/LAN/cloud.
- `ADR-004-sqlite-memory-baseline.md` — SQLite/FTS5 como baseline.
- `ADR-005-responsive-web-admin.md` — administración web responsive, sin app móvil obligatoria.
- `ADR-006-initial-technical-stack.md` — stack técnico provisional guiado por POC/benchmarks.
- `ADR-007-local-admin-auth.md` — autenticación administrativa local persistente.
- `ADR-008-debian-appliance-baseline.md` — Debian 13 minimal como baseline del appliance; sin desktop completo.

Face/Vision/STT/TTS continúan como decisiones POC/provisionales hasta benchmark físico. El sistema base Debian sí queda aceptado como plataforma de despliegue.
