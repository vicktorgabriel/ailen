# ADR-009 — Proveedores Cloud, Circuit Breaker de Presupuesto y SecretResolver

**Estado:** Accepted  
**Fecha:** 2026-08-21  
**Autor:** Antigravity / AILEN Team  

## Contexto

AILEN requiere una estrategia para utilizar proveedores cloud (OpenAI, Gemini, Groq, OpenRouter, etc.) de manera opcional, desacoplada y económicamente segura. Los riesgos asociados son:
1. Filtración accidental de secretos (API keys en repositorios, bases de datos o logs).
2. Costos descontrolados por invocaciones repetidas o bucles de inferencia.
3. Envío de datos personales o privados a servidores de terceros en Internet.

## Decisión

1. **Protocolo Genérico OpenAI-Compatible:** La comunicación con proveedores remotos o locales desacoplados se realiza mediante HTTP estándar (`GenericOpenAiBackend`) con timeouts estrictos y parsing resiliente.
2. **SecretResolver:** Las credenciales nunca se almacenan en `ailen.toml`, SQLite o logs. Se resuelven desde variables de entorno o archivos owner-only; en POSIX se rechazan archivos accesibles por grupo/mundo. Cloud falla cerrado si no hay credencial/configuración suficiente.
3. **BudgetPolicy (Circuit Breaker):** Se audita el consumo registrado en `ai_usage`. `0 USD` significa no gastar y sólo `None` significa sin límite interno. Los precios por token no tienen defaults históricos: deben configurarse con valores vigentes. Si tokens/precio no están disponibles, no se fabrica costo cero.
4. **OutboundPrivacyPolicy:** Datos `RESTRICTED` o `PRIVATE` jamás son enviados a Cloud. Un request bloqueado no se rebaja a `PUBLIC`: falla cerrado.

## Consecuencias

- **Positivas:** Circuit breaker de costo auditable, secretos separados de configuración/datos y privacidad outbound determinista fuera del LLM.
- **Limitaciones:** En caso de agotar presupuesto o perder conectividad, el sistema degrada a respuestas locales sin asistencia en la nube.
