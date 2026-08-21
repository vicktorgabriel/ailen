# Investigación y Arquitectura POC — Cloud Providers & Budget (R3A)

## 1. Objetivos y Filosofía Cloud en AILEN

AILEN utiliza proveedores en la nube exclusivamente para **consultas públicas (`PrivacyLevel.PUBLIC`)** cuando la política, disponibilidad y presupuesto lo permiten. Los modelos concretos no se fijan en el Core: deben configurarse con identificadores y precios vigentes al momento del despliegue.

**Regla de Oro:** Cambiar de proveedor o de modelo de nube **NO cambia la identidad del asistente**. La identidad, memoria, personalidad, límites de seguridad y reglas de negocio residen en AILEN Core.

---

## 2. API Schema y Selección de Transporte

Para evitar dependencias pesadas de SDKs externos (e.g. `google-genai` o `openai` pips enormes con decenas de subdependencias) que inflen el Core en Debian 13 minimal:

1. **Transporte Unificado:** Se implementa un backend cliente HTTP basado en la API estándar OpenAI-compatible (`/v1/chat/completions`) utilizando la biblioteca estándar de Python (`urllib.request`).
2. **Compatibilidad Universal:** Este esquema soporta directamente:
   - Proveedores OpenAI-compatible directos (OpenAI, OpenRouter, Groq, Together, DeepSeek, vLLM, LiteLLM, Ollama, llama.cpp).
   - Proxies/gateways o endpoints de Gemini con endpoint compatible.
3. **Manejo de Secretos:** La API key **NUNCA** se almacena en el archivo de configuración `ailen.toml`, ni en SQLite, ni en el historial de eventos, ni en logs. Se inyecta mediante `SecretResolver` (variables de entorno como `AILEN_AI_CLOUD_API_KEY` o archivos protegidos con permisos `0600` en `/var/lib/ailen/secrets/`).

---

## 3. Política de Presupuesto Económico (`BudgetPolicy`)

Para evitar costos inesperados por uso continuo de APIs en la nube:
* **Presupuesto Diario (`daily_budget_usd`):** Límite máximo de gasto por día.
* **Presupuesto Mensual (`monthly_budget_usd`):** Límite máximo de gasto por mes.
* **Cálculo de Costo:** Configuración paramétrica de costo por millón de tokens (`input_cost_per_million`, `output_cost_per_million`) en la configuración del backend. Para Cloud estos precios deben configurarse explícitamente con valores vigentes; `None` significa precio desconocido y no se trata como costo cero. Si el proveedor reporta tokens y existen precios configurados, se calcula el costo estimado y se persiste en `ai_usage`.
* **Corte Automático (`Circuit Breaker`):** Antes de enviar un request a Cloud, la `BudgetPolicy` consulta los totales consumidos en SQLite. Un límite de `0 USD` significa **no gastar**; sólo `None` representa ausencia de límite a nivel interno. Si el presupuesto se agotó, el Router bloquea Cloud (`reason_code="CLOUD_BUDGET_EXCEEDED"`) y redirige a backends locales/LAN o activa modo degradado.
