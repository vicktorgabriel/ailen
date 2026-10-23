# ADR-016 — Navegador aislado N3 controlado por Core

**Estado:** Proposed (pendiente de medición en hardware objetivo)  
**Fecha:** 2026-10-23  
**Contexto:** ADR-014 formalizó el nivel N3 como navegador controlado con perfil
efímero, sin sesiones del usuario, con lectura libre bajo política anti-SSRF y
confirmación humana para efectos laterales. La investigación en
`docs/research/BROWSER_N3_OPTIONS.md` evaluó alternativas para Debian 13 amd64
sin dependencias nuevas en `pyproject.toml`, sin microservicios y sin Node.js.

## Decisión propuesta

1. **Motor y transporte CDP:** Utilizar `chromium-headless-shell` empaquetado en
   Debian 13 (`trixie`) amd64 (~229 MB instalados, sin entorno X11). Controlado
   directamente por Chrome DevTools Protocol (CDP) mediante JSON sobre el cliente
   WebSocket stdlib (`StdlibWebSocketClient` de `src/ailen/ai/realtime/client.py`).
   Superficie en `pyproject.toml`: 0 dependencias nuevas.
2. **Ciclo de vida y perfil efímero:** Subproceso bajo demanda lanzado por
   `ToolExecutor` exclusivamente durante la sesión N3 y finalizado (`SIGTERM`/
   `SIGKILL`) tras inactividad o timeout, liberando el 100 % de su RAM al terminar.
   Perfil volátil en `tmpfs` (`--user-data-dir`), bajo usuario de sistema sin
   privilegios y con el sandbox nativo de Chromium habilitado (`--no-sandbox`
   prohibido).
3. **Aislamiento de red anti-SSRF:** Todo tráfico saliente se sujeta a
   `WebFetchPolicy`. Las redirecciones y sub-peticiones de red (XHR, scripts,
   recursos) se interceptan mediante CDP (`Fetch.enable`) o proxy HTTP local
   efímero en Core, validando la IP de destino antes de conectar para evitar
   accesos a LAN, localhost o DNS rebinding.
4. **Allowlist estricta de acciones en `BrowserTool`:** La herramienta expone
   únicamente cuatro operaciones: `navigate`, `read_text`, `click` y `type`. Se
   desactivan descargas (`Browser.setDownloadBehavior: deny`), diálogos, nuevas
   ventanas y extensiones.
5. **Mitigación de prompt injection:** Todo contenido DOM extraído se clasifica
   como dato no confiable (`untrusted: True`, `DATOS WEB NO CONFIABLES`). Se
   sanea y trunca antes de ingresar al contexto del LLM; nunca se interpreta como
   instrucción para Core ni para el agente.
6. **Confirmación humana para efectos laterales:** `navigate` y `read_text` son
   lecturas libres sobre HTTPS público validado. Cualquier acción interactiva con
   potencial efecto lateral (`type` en inputs, `click` en `<form>` o botones de
   envío, compra, publicación o login) requiere confirmación humana previa vía
   `ConfirmationService` con resumen determinista auditado en `tool_events`.
7. **Degradación elegante:** Si el binario no está instalado o el hardware no lo
   soporta, se degrada al extractor estático sin JS (`html.parser` sobre
   `web_fetch`) para lectura básica, o se reporta `TOOL_UNAVAILABLE`.

## Alternativas descartadas

- **Playwright (`playwright`):** No empaquetado en Debian 13 `trixie`. Requiere
  runtime binario Node.js (~50–70 MB) y múltiples dependencias Python/C
  adicionales ajenas al stack de AILEN.
- **Selenium (`python3-selenium` + `chromium-driver`):** Agrega el proceso
  `chromedriver` y librerías intermedias sin aportar ventajas frente a CDP
  directo por WebSocket nativo.
- **Extractor HTML sin JS exclusivo:** Incapaz de interactuar con SPAs o sitios con
  renderizado dinámico; queda relegado como fallback de sólo lectura liviana.
- **Firefox ESR headless:** Mayor tamaño instalado (~301 MB frente a ~229 MB),
  `geckodriver` no empaquetado en `trixie`, y WebDriver BiDi menos auditado en la
  base actual de Core.

## Consecuencias

- **Positivas:** Cero dependencias añadidas a Python; navegación N3 aislada en
  disco y red; liberación de memoria garantizada fuera de uso; control total en Core.
- **Costos y límites:** Requiere instalar el paquete Debian a nivel OS; el adaptador
  CDP debe gestionarse y auditarse dentro de Core; CPU/RAM transitoria durante cargas.

## Riesgos abiertos

- **Presión de RAM en 4 GB:** Sitios pesados pueden comprometer la estabilidad;
  requiere límites estrictos de proceso renderer y memoria V8.
- **Bypass SSRF en sub-recursos:** Si no se intercepta cada conexión a nivel de red,
  JavaScript malicioso podría sondear la LAN o infraestructura local.
- **Procesos huérfanos:** Caídas o timeouts abruptos de la tarea en Core deben
  garantizar la limpieza del subproceso Chromium y su directorio en `tmpfs`.
- **UI Redressing / engaño visual:** Elementos web con etiquetas que oculten su
  efecto real frente al resumen presentado para confirmación humana.

## Mediciones requeridas para pase a Accepted

Conforme a `AGENTS.md`, ninguna viabilidad de hardware se asume sin evidencia. El
pase a `Accepted` queda condicionado a mediciones en **Banghó Zero G05 (8 GB)** y
**SF20BA (8 GB → 4 GB)** bajo Debian 13 minimal con stack completo activo
(Core, VAD, STT, TTS, FacePack 1.6):

1. **RSS pico:** a medir
2. **RSS percentil 95 (p95):** a medir
3. **Latencia de arranque en frío (cold start):** a medir
4. **Impacto en latencia de audio/voz:** a medir (ausencia de xruns o caídas de turnos)
5. **Impacto en FPS del rostro:** a medir (estabilidad de cuadros en FacePack)
