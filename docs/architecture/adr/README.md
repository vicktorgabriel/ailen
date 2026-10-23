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
- `ADR-009-cloud-providers-and-budget-circuit-breaker.md` — privacidad outbound, secretos y límites de costo cloud.
- `ADR-010-adaptive-inference-and-controlled-tools.md` — selección de inferencia por hardware y tools/Web controlados por Core.
- `ADR-011-configurable-external-ai-providers-and-admin.md` — proveedores externos configurables y administración segura.
- `ADR-012-native-facepack-engine.md` — engine C ABI desacoplado y FacePack externo versionado.
- `ADR-013-signed-provisioning-and-recoverable-updates.md` — manifiestos Ed25519,
  CAS, journal y activación/rollback simulados; daemon Appliance pendiente.
- `ADR-014-core-agent-and-autonomy-levels.md` — agente en Core con niveles de
  autonomía N1–N3 (tools, archivos acotados, navegador aislado); N4 fuera. Accepted.
- `ADR-015-realtime-voice-provider.md` — proveedor remoto de voz en vivo opcional
  por WebSocket con tools vía function-calling en Core. Accepted.
- `ADR-016-isolated-browser-n3.md` — navegador N3 aislado con chromium-headless-shell y CDP sobre stdlib WebSocket. Proposed.


Vision/STT/TTS continúan sujetos a POC/benchmark físico. FacePack queda aceptado
como default lógico de laboratorio; falla a headless y no selecciona `portrait`.
La DLL Windows, packaging de release y hardware LOW siguen sin validación. El
sistema base Debian sí queda aceptado como plataforma de despliegue.
