# Frontera de Búsqueda y Extracción Web — AILEN

**Fecha:** 2026-08-23  
**Hito:** R3C Product Behaviors + Controlled Tools + Web  
**Estado:** Integrado / Baseline  
**Referencia:** ADR-009, ADR-010

---

## 1. Objetivo

AILEN permite obtener información pública de Internet para responder preguntas actualizadas sin otorgar acceso de red irrestricto al modelo de lenguaje ni exponer la red interna del usuario a ataques de SSRF (Server-Side Request Forgery).

---

## 2. Búsqueda Web (`web_search`)

### 2.1 Contrato del Proveedor (`WebSearchProvider`)
El acceso a motores de búsqueda se abstrae mediante la interfaz `WebSearchProvider`:
- Entrada: `WebSearchRequest` (`query`, `max_results`, `language`, `safe_search`, `timeout`).
- Salida: `WebSearchResponse` (`success`, `results: list[WebSearchResult]`, `status`, `cost_tier`, `error_message`).

### 2.2 Política de Proveedores y Estados
- **Default Seguro:** Si no hay un proveedor comercial o local configurado, el sistema utiliza `UnconfiguredWebSearchProvider`, respondiendo con estado `UNCONFIGURED` y mensaje directo al usuario.
- **Sin Scraping Frágil:** Queda prohibido hardcodear parsers de motores públicos sin API aprobada que puedan romperse ante cambios de HTML.
- **Costos Transparentes:** Los proveedores se etiquetan con `cost_tier` (`FREE`, `PAID`, `UNKNOWN`). Si el proveedor es de pago, el costo corre por cuenta del cliente con cuotas explícitas.

---

## 3. Extracción Segura (`web_fetch`) y Política Anti-SSRF

La herramienta `web_fetch` descarga y sanitiza texto de una URL pública bajo la política estricta `WebFetchPolicy`:

### 3.1 Defensas Anti-SSRF
1. **Esquema Obligatorio:** Sólo se admite `https://` (o `http://` si es explícito). Se rechazan terminantemente esquemas peligrosos como `file://`, `ftp://`, `data:`, `javascript:`, `gopher://`.
2. **Validación de Hostnames:** Se bloquean `localhost`, `localhost.localdomain` y endpoints de metadata cloud (`metadata.google.internal`).
3. **Resolución DNS y Validación de IP:** Antes de abrir cualquier conexión socket, se resuelve el host mediante `socket.getaddrinfo` y se valida que **todas** las direcciones IP asociadas sean públicamente enrutables:
   - Bloqueo de Loopback (`127.0.0.0/8`, `::1`).
   - Bloqueo de Redes Privadas RFC1918 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).
   - Bloqueo de Link-Local (`169.254.0.0/16`, `fe80::/10`).
   - Bloqueo de Endpoint de Metadata Cloud (`169.254.169.254`).
   - Bloqueo de Multicast, Reservadas y No Especificadas (`0.0.0.0`).
4. **Inspección en Redirecciones HTTP:** Las redirecciones (301, 302, 303, 307, 308) no se siguen automáticamente por el cliente HTTP; se inspecciona individualmente cada URL de destino contra la política DNS e IP antes de cada salto (límite máximo de 3 redirecciones).

### 3.2 Restricciones de Carga y Contenido
- **Límite de Tamaño:** Máximo 256 KiB (`262,144` bytes). Se verifica cabecera `Content-Length` y lectura acotada con fail-closed.
- **Allowlist de Content-Type:** Sólo se aceptan tipos textuales (`text/html`, `text/plain`, `text/markdown`, `application/json`, `application/xml`).
- **Rechazo de Binarios:** Imágenes, ejecutables, archivos comprimidos (ZIP), audio y video son rechazados de inmediato.
- **Sin Ejecución de JavaScript:** Se procesa como texto/HTML estático; no se ejecutan scripts del navegador.

---

## 4. Estados y modos de `web_search`

- `web_search` está permitido en modos `HOME`, `WORKSHOP`, `PUBLIC` y `PRIVATE`; queda **excluido de `SHOP`** por conservadurismo mientras no exista política de contenido externo en contexto comercial. Revisable con evidencia.
- Sin proveedor configurado responde `UNCONFIGURED` y la conversación contesta directamente sin invocar al LLM (sin costo, sin latencia de inferencia).
- Conectividad: el executor deniega tools con `requires_network=true` (`NETWORK_UNAVAILABLE`) cuando `ToolContext.internet_available=false`.

---

## 5. Limitaciones conocidas

- **DNS rebinding (TOCTOU):** la validación DNS/IP ocurre antes de abrir la conexión; la librería HTTP vuelve a resolver el host al conectar. Un atacante que controle DNS podría devolver una IP pública en la validación y una IP privada en la conexión. Mitigación futura: transporte con IP fijada (pinning) o verificación post-conexión del par remoto. No bloquea los vectores comunes (loopback/RFC1918 directos, redirects a privados, metadata), que sí están cubiertos.


### Hardening posterior

`WebFetch` opera HTTPS-only, rechaza credenciales embebidas en URL, exige un `Content-Type` permitido y mantiene límites de bytes/redirecciones. Los resultados de `WebSearchProvider` se acotan y sanea la URL antes de entrar al contexto; todo contenido web se marca como no confiable y no puede redefinir rol, reglas ni pedir secretos/tools. La autorización outbound se configura en `[network].outbound_web_enabled`, separada de cloud AI.
