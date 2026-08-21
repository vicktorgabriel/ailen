# Investigación y Arquitectura POC — AI Router Híbrido (R3A)

## 1. Contexto y Objetivos

AILEN (**Asistente Inteligente Local, Evolutivo y Natural**) está diseñado bajo un modelo híbrido donde la toma de decisiones de enrutamiento es **completamente determinista, auditable y ajena a cualquier LLM**. El Router no es una red neuronal; es una máquina de decisión basada en políticas de privacidad, perfiles de hardware, latencia, conectividad, complejidad y presupuesto económico.

---

## 2. Taxonomía de Rutas y Backends

Se establecen cinco rutas canónicas:

| Ruta / Backend | Identificador | Propósito Principal | Restricción de Privacidad |
| :--- | :--- | :--- | :--- |
| **Rule-Only** | `rule` | Comandos de control (volumen, timer, hora, saludos, cambio de modo, estado). Cero uso de LLM. | Toda privacidad. |
| **Local LLM** | `local` | Inferencia en la máquina anfitriona (servidor llama.cpp / Ollama local en `127.0.0.1`). | Soporta `PRIVATE`, `RESTRICTED` y `PUBLIC`. |
| **LAN Brain** | `lan_brain` | Inferencia en nodo servidor dentro de la misma red local (`trusted=True/False`). | Si `trusted=True`: `PRIVATE`/`RESTRICTED`/`PUBLIC`. Si no confiable: sólo `PUBLIC`. |
| **Cloud Provider**| `cloud` | Inferencia remota en nube (APIs REST rápidas/económicas) para chat abierto o consultas complejas. | **Estrictamente `PUBLIC`**. NUNCA recibe datos `RESTRICTED` o `PRIVATE`. |
| **Degraded** | `degraded` | Respuesta de contingencia estructurada y segura cuando ningún backend está disponible o configurado. | No envía datos. |

---

## 3. Matriz de Decisión por DeviceProfile

El perfil de dispositivo (`DeviceProfile`) declara la capacidad computacional y el rol del nodo en el ecosistema AILEN:

1. **`SATELLITE` (Nodos livianos / 2-4 GB / Terminales de voz y presencia):**
   - Inferencia local pesada deshabilitada o fuertemente restringida.
   - Preferencia primaria: **`LAN_BRAIN`**.
   - Fallback secundario: **`CLOUD`** (si privacy es `PUBLIC`, internet disponible y hay presupuesto).
   - Fallback final: **`DEGRADED`**.

2. **`CLOUD` (Nodos orientados a conectividad continua y modelos de nube):**
   - Preferencia primaria para chat: **`CLOUD`** (si la política de privacidad outbound lo permite).
   - Comandos y control continúan siendo **`RULE_ONLY`**.
   - Fallback: **`LAN_BRAIN`** / **`LOCAL`** -> **`DEGRADED`**.

3. **`HYBRID` (Perfil por defecto / Balance entre autonomía local y asistencia remota):**
   - Comandos de control -> **`RULE_ONLY`**.
   - Privacidad `PRIVATE`/`RESTRICTED` -> **`LOCAL`** -> **`LAN_BRAIN`** -> **`DEGRADED`** (Cloud bloqueado).
   - Privacidad `PUBLIC` con baja latencia -> **`LOCAL`** -> **`LAN_BRAIN`** -> **`CLOUD`**.
   - Privacidad `PUBLIC` con alta complejidad o sin local disponible -> **`CLOUD`** -> **`LAN_BRAIN`** -> **`LOCAL`**.

4. **`LOCAL` (Nodos autónomos offline-first / Máxima soberanía de datos):**
   - Preferencia primaria: **`LOCAL`**.
   - Fallback secundario: **`LAN_BRAIN`** (si está en red).
   - Cloud: Bloqueado por defecto salvo autorización explícita de política.

5. **`LAN_BRAIN` (Servidor de inferencia local de alta capacidad / PC con GPU):**
   - Actúa como ejecutor local de inferencia.
   - Preferencia primaria: **`LOCAL`**.
   - No actúa como cliente cloud-first.

---

## 4. Política de Privacidad Outbound (Hacia la Red)

La privacidad se divide en dos capas inviolables:

1. **Inbound / Retrieval Privacy (`SocialPrivacyPolicy`):** Controla qué memorias y hechos de negocio de SQLite pueden cargarse al contexto según el `SocialMode` (`SHOP`, `PUBLIC`, `HOME`, `WORKSHOP`, `PRIVATE`, `SLEEP`).
2. **Outbound Privacy (`OutboundPrivacyPolicy`):** Controla qué destinos de red tienen autorización para recibir el request:
   - `PrivacyLevel.PUBLIC`: Puede enviarse a Cloud si Cloud está habilitado y hay presupuesto.
   - `PrivacyLevel.RESTRICTED`: Puede enviarse a `Local` o `LAN_BRAIN` confiable (`trusted=True`). **NUNCA sale a Internet/Cloud**.
   - `PrivacyLevel.PRIVATE`: Puede enviarse a `Local` o `LAN_BRAIN` confiable según política. **NUNCA sale a Internet/Cloud**.
   - En modos públicos (`SHOP`/`PUBLIC`): Solo información pública puede ingresar al contexto y solo backend local o cloud para consultas públicas es admisible.

---

## 5. Fallback Ordenado y Circuit Breaking

El `AiOrchestrator` recibe el `RoutePlan` generado por el `RuleBasedRouter` y ejecuta los intentos de manera secuencial y acotada:
- Máximo de intentos = `1 + len(fallback_backends)`. Cero bucles infinitos.
- Registro auditable de cada intento en telemetría de eventos.
- Si un backend falla por timeout, conexión rechazada o error HTTP, se conmuta al siguiente fallback disponible.
- Si todos los backends fallan, se genera una respuesta `AiResponse` segura de modo degradado (`finish_reason="degraded"`), sin que el sistema colapse ni emita errores técnicos al usuario.
