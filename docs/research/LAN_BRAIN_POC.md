# Investigación y Arquitectura POC — LAN Brain (R3A)

## 1. Concepto y Rol de LAN Brain

Un nodo **LAN Brain** es una máquina de mayor capacidad de cómputo (e.g. PC con GPU dedicada o servidor doméstico/taller en la misma red local) que actúa como acelerador de inferencia para terminales satélite o nodos modestos (`SATELLITE` / `HYBRID`).

---

## 2. Límite de Confianza (`Trust Boundary`)

El nodo satélite debe saber si el servidor LAN es de confianza total o un endpoint compartido:

* **`ai.lan.trusted = false` (default seguro):** la confianza debe habilitarse explícitamente sólo para un LAN Brain controlado por el propietario.
  * El satélite puede delegar consultas con nivel de privacidad `RESTRICTED` y `PRIVATE` a la LAN Brain, ya que los datos nunca salen a la Internet pública.
* **`ai.lan.trusted = false`:**
  * La LAN Brain es tratada como un nodo no seguro. Solo consultas con `PrivacyLevel.PUBLIC` son remitidas; datos `RESTRICTED` o `PRIVATE` son bloqueados por `OutboundPrivacyPolicy`.

---

## 3. Protocolo de Comunicación

* Protocolo: HTTP REST OpenAI-compatible (`POST /v1/chat/completions`, `GET /v1/models` para health check).
* Timeouts y Fallbacks: Si la LAN Brain no responde dentro del timeout configurado (`ai.lan.timeout_seconds`), el `AiOrchestrator` conmuta limpiamente a los fallbacks del `RoutePlan` (Local o Cloud si la privacidad lo permite, o Degraded).
* Para R3A se utiliza configuración de endpoint estática (`ai.lan.endpoint = "http://192.168.1.50:8080/v1"`). Discovery automático mDNS se posterga para versiones futuras.
