# ADR-015 — Proveedor remoto de voz en vivo (realtime)

**Estado:** Accepted (2026-10-23)
**Fecha:** 2026-10-23
**Contexto:** En equipos modestos que no sostienen un LLM local cuantizado más el
stack de voz, AILEN debe poder ofrecer conversación de voz fluida tipo llamada,
usando un modelo externo con audio nativo (por ejemplo OpenAI Realtime o Gemini
Live). El pipeline actual es VAD → STT local → LLM → TTS local, con proveedores
remotos sólo de texto (ADR-011).

## Decisión

1. **Nuevo tipo de ruta:** `remote_realtime:<provider_id>`, separado de los
   remotos de texto. Transporte WebSocket (o equivalente del proveedor) con audio
   PCM bidireccional; el adaptador de cada proveedor vive detrás de un contrato
   propio y es reemplazable.
2. **Opt-in explícito y visible.** Desactivado por defecto. Al activarlo, el panel
   y el rostro indican que el audio sale del equipo. En `SHOP`/`PUBLIC` y con
   contenido `PRIVATE`/`RESTRICTED` no se usa.
3. **Core conserva identidad, memoria y herramientas.** El modelo realtime recibe
   instrucciones mínimas generadas por Core y ejecuta acciones únicamente por
   function-calling hacia `ToolExecutor` (ADR-014); nunca accede directo al
   sistema. Memoria y personalidad no se transfieren al proveedor salvo el
   contexto mínimo filtrado por `OutboundPrivacyPolicy`.
4. **Barge-in y estado.** Core mantiene el `AudioTurnGate`, el estado del rostro
   y la cancelación; la interrupción del usuario corta la reproducción y envía la
   cancelación al proveedor.
5. **Presupuesto y fallo.** Se aplica `BudgetPolicy` por minuto/tokens de audio.
   Si la conexión cae o se agota el presupuesto, se degrada a la cascada de
   texto (STT → remoto texto → TTS) o a `RULE_ONLY`, sin colgar la conversación.
6. **Sin afirmaciones sin medir.** Latencia, costo y calidad rioplatense se
   declaran sólo con TTFT/TTFAR medidos con clave propia y consentimiento.

## Consecuencias

- Se añade `realtime_eligible` a la calificación de proveedores y un adaptador
  WebSocket liviano (sin SDK pesado si es evitable).
- El provisioning para hardware sin LLM local ofrece esta ruta como opción, con
  aviso de privacidad y costo.
- Requiere nuevas pruebas simuladas offline y un harness dry-run como el de
  proveedores de texto.
