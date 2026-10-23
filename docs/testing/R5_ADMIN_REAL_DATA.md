# R5 — Administración de recuerdos y diagnóstico con datos reales

Fecha: 2026-10-02. Versión: `0.4.0-dev.0`.

## Alcance entregado

- `/memoria`: recuerdos explícitos persistidos en SQLite; búsqueda literal
  escapada, 50 registros por página, alta/edición, borrado individual y
  exportación JSON de hasta 1000 registros. El exceso se rechaza sin truncar.
- Públicos por defecto; mostrar/exportar privados y restringidos requiere
  selección explícita. Escrituras y exportación: sesión válida, POST, CSRF y
  confirmación. No se modifica la política conversacional del Core.
- La exportación contiene sólo recuerdos, con `schema_version`, fecha y conteo;
  no contiene tablas de credenciales, historial, notas ni recordatorios. Se
  descarga como attachment con `Cache-Control: no-store`.
- No se ofrece purga masiva ni se afirma cifrado SQLite o búsqueda FTS5. Los
  parámetros de búsqueda no se incluyen en los logs HTTP de acceso.
- `/diagnostico`: salud del proceso que sirve el panel, LabDoctor ejecutado a
  pedido y métricas de la última sesión Lab finalizada. Los periféricos que
  `serve` no inicia permanecen UNKNOWN. No representa health vivo de Lab.
- Doctor no descubre runtimes locales con `ai.local.enabled=false`; una sola
  comprobación simultánea, con estado inicial sin ejecutar y fallos explícitos.
- Lector de reportes bajo `runtime/lab` inyectado por composición, sin paths
  desde requests: archivo regular sin symlink, máximo 1 MiB, exploración de
  hasta 4096 entradas. Proyecta sólo fecha, muestras y latencias finitas no
  negativas de campos allowlisted. Un último reporte inválido no se sustituye
  silenciosamente por una medición anterior.
- Los reportes nuevos incluyen `execution_mode` y conteos de muestras. Legacy,
  simulación y dry-run no se muestran como mediciones reales. `real` identifica
  backends no simulados, no certifica hardware ni calidad acústica.

## Regresiones y validación

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src/ailen
git diff --check
.venv/bin/python -m build --wheel --outdir /tmp/ailen-r5-wheel-review
```

- Suite completa: **1164 tests en verde**.
- Ruff limpio y mypy limpio en **168 módulos fuente**.
- TCP real en loopback: login, CSRF, creación, lectura privada explícita,
  descarga JSON y diagnóstico sin mediciones inventadas.
- Regresiones focales: scope público/privado, XSS, búsqueda literal con `%`,
  paginación sin duplicados, confirmaciones, límites de exportación, conservación
  de notas/recordatorios/importance/expiry, errores redactados, concurrencia de
  Doctor, modo local deshabilitado y rechazo de reportes simulados/corruptos/
  symlinks/tamaño excesivo/valores no finitos.
- Metadato nuevo de métricas es keyword-only: conserva compatibilidad con el
  segundo argumento posicional histórico (`started_at`).
- Navegador Chromium sobre servidor temporal con base y datos sintéticos:
  alta privada oculta en vista pública, visible tras opt-in; memoria sin desborde
  del documento a 390, 768 y 1440 px; diagnóstico a 390 px. Se corrigió el mínimo
  del grid y la barra superior móvil; las tablas conservan scroll interno.
- Wheel revisado: **211 entradas**, nuevas plantillas/servicios incluidos;
  sin DB, WAV, MP4, FacePack, binarios nativos ni datos runtime. El build aislado
  resolvió la ausencia de setuptools en el venv de desarrollo; no se instaló
  una dependencia runtime adicional. Persisten avisos previos de setuptools
  sobre metadata de licencia, fuera de este slice.

## Medición acotada del servidor

Entorno local de desarrollo: Linux x86_64, Python 3.12.3. No extrapolar a
Banghó/SF20BA. Fixture: SQLite temporal con 1000 recuerdos públicos sintéticos,
reporte mínimo sintético para medir render/lectura, sesión administrativa de
prueba, una llamada de calentamiento y 100 llamadas `app.handle(GET)` por vista.
Se midió tiempo wall con `perf_counter`; excluye red, navegador y ejecución del
Doctor. No es un benchmark del pipeline de voz ni de la veracidad del fixture.

| Vista | p50 | p95 |
|---|---:|---:|
| `/memoria` (50 filas) | 2,064 ms | 2,326 ms |
| `/diagnostico` | 0,245 ms | 0,263 ms |

## Pendientes preservados

- Panel de notas, recordatorios e historial; búsqueda FTS5 administrativa.
- Observabilidad entre procesos en vivo y visor de logs redactados.
- Personalidad, visión, herramientas, rostro y sistema/setup con valores reales;
  comercio/FAQ y experiencia inicial móvil completa.
- Pruebas físicas R4/R5B, perfiles de hardware y R6 Appliance. No se probaron
  micrófono, cámara, reproducción audible ni updater físico en este slice.
