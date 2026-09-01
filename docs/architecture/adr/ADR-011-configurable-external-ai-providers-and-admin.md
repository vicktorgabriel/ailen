# ADR-011 — Provider Manager remoto nombrado y administración segura

**Estado:** Aceptado; revisión mayor 2026-09-01  
**Fecha original:** 2026-08-28  
**Contexto:** AILEN debe conversar con un modelo local, un Brain LAN o varios
proveedores remotos sin mover identidad, memoria, permisos ni herramientas fuera
de Core. ASRock es laboratorio, no requisito comercial.

## Problema

La primera integración externa colapsaba todos los HTTP remotos bajo una ruta
`cloud` y añadía clientes de agentes CLI. Eso impedía una cascada observable
entre proveedores y mezclaba estado de producto con herramientas de desarrollo.
Además, una lista de modelos fija envejece rápido y una respuesta completa
troceada no equivale a streaming.

Los ensayos históricos justifican retirar dos rutas: Antigravity/AGY tardó unos
6,7 s de media hasta primer texto bajo contención y agregó contexto interno de
agente; OpenCode Free devolvió respuestas inválidas y 429. Los reportes se
conservan como evidencia, pero ninguno sigue siendo proveedor runtime.

## Decisión

1. Las categorías estables del router son `local`, `lan_brain` y una o más rutas
   nombradas `remote:<provider_id>`. `provider=auto` aplica modalidad,
   privacidad, complejidad, disponibilidad y elegibilidad realtime; las
   prioridades sólo ordenan opciones equivalentes y fallbacks. Una selección
   explícita se honra primero, con fallback permitido.
2. Cada proveedor remoto tiene configuración y secreto independientes:
   `enabled`, preset, protocolo, endpoint, modelo, auth, prioridad, timeout,
   presupuestos, costos opcionales, catálogo, streaming, calificación y
   elegibilidad para voz. Guardar cambia el archivo; el runtime vivo requiere
   reinicio y la UI debe decirlo.
3. Los presets iniciales son OpenAI, Anthropic, DeepSeek, Kimi, MiniMax y
   compatibles genéricos. Un preset sólo aporta endpoint/protocolo y nombre de
   secreto; no afirma modelo vigente, salud ni calidad. El modelo queda vacío
   hasta selección manual o catálogo live verificado. El preset global de Kimi
   usa `https://api.moonshot.ai/v1` y el internacional de MiniMax usa
   `https://api.minimax.io/v1`. Endpoints regionales chinos requieren un
   provider ID/configuración explícitos y nunca se eligen por defecto.
4. Los transportes livianos implementados, sin SDK pesado, son:
   - OpenAI Responses API con SSE real y `store=false`;
   - OpenAI Chat Completions compatible con SSE real;
   - Anthropic Messages API con SSE real y versión explícita.
   Ninguno anuncia tools ni reasoning si el adapter no los implementa.
5. `catalog_mode=live` se habilita sólo cuando el adapter posee una consulta de
   modelos específica y probada para ese preset. En esta revisión únicamente
   OpenAI queda `live` y consulta `/v1/models`; Anthropic, DeepSeek, Kimi,
   MiniMax y compatibles genéricos quedan `manual`. Un proveedor manual no usa
   un `/models` supuesto como health: permanece configurado/no probado hasta una
   prueba de conexión explícita, que puede tener costo.
6. `SecretResolver` conserva una clave separada por proveedor fuera de TOML y
   SQLite, con directorio `0700`, archivo `0600`, escritura atómica y rechazo de
   permisos abiertos. Las claves nunca se muestran ni se mezclan.
7. La política saliente final reconstruye cada request remoto como
   `SANITIZED_REMOTE_CURRENT_TURN_ONLY`: último turno del usuario, instrucciones
   orales públicas mínimas y metadata escalar allowlisted. Excluye historial,
   memoria recuperada, notas, persona privada, paths, tools, configuración y
   secretos. Sin opt-in de sanitización, PRIVATE no sale.
8. Timeout, rate limit, autenticación, modelo inválido, red, unavailable,
   respuesta inválida y error interno se clasifican. Un 429 abre cooldown
   acotado respetando `Retry-After` dentro del límite. El router pasa al siguiente
   backend sólo si aún no emitió texto; después de un delta potencialmente
   audible devuelve un parcial/error y nunca empalma otra respuesta.
9. `ai.local.enabled=false` sigue siendo frontera estricta de esa instalación:
   no crea, descubre, inicia ni precalienta Ollama/llama.cpp y nunca agrega local
   como fallback. Esto no cambia que el producto soporte local cuando el
   provisioning lo habilita expresamente.
10. AGY/Antigravity y OpenCode quedan retirados end-to-end. Una configuración
    vieja se migra a `provider=auto` con warning y las secciones se descartan; no
    existen adapter, runtime manager, secreto, ruta Web ni alias que los invoque.

## Evidencia implementada

- pruebas de transporte simulan eventos SSE, auth, catálogo OpenAI, timeout, 429,
  errores de modelo y fallbacks sin llamar APIs reales;
- pruebas de presets fijan MiniMax internacional y Kimi global, rechazan una
  selección regional china implícita y mantienen manual todo catálogo no
  verificado;
- pruebas de captura inspeccionan el payload final y demuestran ausencia de
  memoria, historial, persona, paths, herramientas y secretos;
- un corpus prueba prioridad real, proveedor explícito, `auto`, cooldown y la
  prohibición de fallback tras texto emitido;
- `scripts/validate_external_ai.py` es dry-run por defecto y sólo ejecuta una API
  con `--execute`; nunca usa local/LAN ni persiste prompt/respuesta.

Esta evidencia valida contratos, no disponibilidad, latencia ni costo de los
presets. OpenAI, Anthropic, DeepSeek, Kimi y MiniMax permanecen **no probados**
hasta que el administrador configure una clave/modelo, consienta la prueba y se
registre TTFT/reliability. `voice_realtime_eligible` permanece falso hasta ese
benchmark.

## Consecuencias

Positivas:

- Core puede hacer fallback entre remotos observables sin colapsarlos en
  `cloud`;
- streaming y capacidades reflejan el protocolo realmente implementado;
- retirar clientes de agentes evita contexto oculto, herramientas y latencia de
  procesos ajenos al producto;
- agregar un proveedor compatible requiere configuración y transporte, no
  cambios en memoria, tools, voz o identidad.

Límites:

- no se probaron proveedores pagos en esta revisión;
- la stdlib HTTP no mantiene todavía un pool persistente entre turnos;
- las garantías de retención dependen también del contrato/cuenta del proveedor;
  `store=false` se envía donde el protocolo lo permite, pero AILEN no promete
  Zero Data Retention por sí solo;
- hot reload del router no está implementado: se requiere reiniciar AILEN.

## Historia preservada

La versión 2026-08-28 integró AGY y OpenCode como experimentos. La medición de
2026-08-31 los rechazó para conversación de producto. Sus benchmark históricos
y entradas de changelog permanecen; esta revisión reemplaza únicamente su
estatus de producción.
