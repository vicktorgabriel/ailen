# Estado actual — AILEN

**Fecha:** 2026-09-01
**Versión:** `0.4.0-dev.0`
**Fase:** R4/R5 en consolidación sobre baseline R3C auditado; R5B FacePack realista está implementado como default lógico en ASRock/Linux y `portrait` queda sólo como opción legacy manual. Fallo de engine/pack degrada a headless, nunca selecciona `portrait`. R5 tiene mezcla de vistas funcionales y maquetas: `/ia`, `/audio`, `/actualizaciones`, `/memoria` (recuerdos explícitos) y `/diagnostico` consumen servicios reales; personalidad/vision/tools y otras vistas aún requieren eliminar defaults/datos sintéticos. El Provider Manager usa rutas remotas nombradas, prioridades reales, secretos separados y requests de turno actual saneado. AGY/Antigravity y OpenCode fueron retirados del producto por evidencia de latencia/inestabilidad; los presets OpenAI, Anthropic, DeepSeek, Kimi y MiniMax siguen sin prueba paga. La instalación local se decide mediante un `ProvisioningPlan` basado en hardware y calificación objetivo; `ai.local.enabled=false` sigue siendo estricto. Baseline completo actual: 1164 tests, Ruff limpio, mypy limpio en 168 archivos fuente, diff-check y wheel limpio de 211 entradas inspeccionadas; el engine/FacePack no cambió en esta pasada.

## Definición de producto y agente — 2026-10-23

- Producto: asistente tipo Alexa para equipos modestos; LLM local cuantizado/híbrido
  según hardware o, si no es viable, proveedor externo con voz en vivo (ADR-015).
- Capacidad objetivo: ejecutar tools locales y de red, navegar y modificar archivos
  locales como una persona usando el equipo, bajo niveles N1–N3 de ADR-014 con
  agente en Core, confirmación humana y sin shell general (N4 fuera).
- R5 Web Admin: además de `/ia`, `/audio`, `/actualizaciones`, `/memoria` y `/diagnostico`, ahora `/herramientas`, `/vision`, `/rostro`, `/personalidad`, `/sistema` y `/setup` consumen config efectiva sin datos sintéticos. Baseline: 1190 tests, Ruff y mypy (174 módulos) limpios; wheel no reverificado en este lote.
- Estado: ADR-014/015 aceptados; implementación pendiente (Bloque 22 de TASKS, R5C).
- AGY (Gemini) y OpenCode (DeepSeek free) son agentes auxiliares de desarrollo
  obligatorios para delegar; no son proveedores runtime.

## R5 — Memoria y diagnóstico reales — 2026-10-02

- `/memoria` administra recuerdos explícitos del repositorio: búsqueda literal
  paginada (50), alta/edición/borrado individual confirmado y exportación JSON
  explícita (máximo 1000; rechaza exceso, no trunca). Público por defecto;
  privados/restringidos requieren opt-in de visualización/exportación del admin.
- No modifica política conversacional, notas, recordatorios, sesiones,
  personalidad ni credenciales. Búsqueda administrativa usa LIKE escapado; no se
  anuncia como FTS5. No hay purga masiva ni promesa de cifrado SQLite.
- `/diagnostico` distingue health del proceso del panel, LabDoctor a pedido
  (POST + CSRF, una ejecución simultánea) y última sesión Lab finalizada.
  El panel no inicia los periféricos de Lab ni los marca saludables por default.
- Reportes nuevos declaran `execution_mode` y cantidad de muestras por latencia.
  Simulados/dry-run/legacy sin procedencia no se presentan como medición real.
  Sólo se proyectan escalares allowlisted; no se exponen logs/transcripts/paths.
- LabDoctor respeta `ai.local.enabled=false` sin descubrir runtimes locales.
- Siguiente software: personalidad/visión/herramientas/rostro/sistema/setup con
  valores efectivos, más comercio e historial. Validaciones físicas R4/R5B y
  Appliance R6 siguen abiertas.
- Evidencia y alcance: `docs/testing/R5_ADMIN_REAL_DATA.md`.

## R4 AI local-first y proveedores remotos opcionales — 2026-08-31

- Core conserva memoria, personalidad, herramientas, permisos, Vosk, Piper y
  FacePack independientemente del proveedor conversacional.
- `ai.local.enabled=false` no descubre, construye, inicia, precalienta ni usa
  Ollama/llama.cpp, y tampoco crea el parser semántico local. No hay fallback
  local implícito.
- En despliegues con local habilitado, el modelo debe elegirse por hardware y
  permanecer cuantizado/persistente. Las bandas 1-1,7B Q4 (4 GB) y 3-4B Q4
  (8 GB) son objetivos de prueba, no soporte demostrado. La memoria compartida
  de una iGPU cuenta contra el presupuesto total.
- Remoto privado requiere opt-in explícito. El payload final probado contiene
  sólo el turno actual, estilo oral genérico y metadata allowlisted; excluye
  historial, memories, notas, persona, capabilities, paths, tools y secrets.
- Los presets globales usan Kimi `api.moonshot.ai/v1` y MiniMax internacional
  `api.minimax.io/v1`; no hay selección china implícita. Sólo OpenAI declara
  catálogo live; los demás quedan manuales hasta verificar una consulta oficial
  específica.
- Orden real: proveedor explícito elegible primero; en `auto`, modalidad,
  privacidad, complejidad y elegibilidad realtime eligen clase, y la prioridad
  ordena equivalentes/fallbacks. Cada remoto conserva identidad
  `remote:<provider_id>`; disabled/sin key/sin modelo no entra al fallback.
- 429/timeout/auth/model/network/invalid response se clasifican. 429 abre
  cooldown acotado y usa el siguiente proveedor sin bloquear la conversación.
- Benchmark histórico ASRock contendido: AGY completó 8/8 pero primer texto
  promedió 6,74 s (p95 8,88 s), total 6,87 s; OpenCode completó 1/4, tuvo dos
  respuestas sin texto visible y luego 429. Ambos quedan `RETIRED/REJECTED` y no
  existe ninguna ruta de producción que los invoque.
- `/ia` guarda configuración y secrets, pero el router activo se reconstruye al
  reiniciar AILÉN; el panel ya no afirma hot reload.
- Ollama y llama.cpp implementan el mismo contrato de inferencia. Si existe un
  GGUF verificado, el runner puede registrar llama.cpp administrado sin arrancarlo:
  se carga en el primer turno y sólo se detiene, siendo propiedad de AILÉN y
  estando ocioso, si la RAM disponible cruza el piso del perfil. Ollama conserva
  su proceso y permite descargar el modelo ocioso por la API nativa.
- Los envelopes actuales reservan RAM para el sistema y el stack de voz:
  4 GB nominal = contexto 1024/modelo hasta 1400 MB/piso libre 700 MB; 8 GB =
  2048/3000/1200 MB. Desde 16 GB el presupuesto deja de tener techo fijo:
  reserva al menos 1800/3000/6000 MB para 16/32/64+ GB y además un 15% de la
  RAM total, usando el resto disponible y contexto inicial 4096/8192/16384.
  Una GPU usa sólo VRAM dedicada disponible, sin duplicar memoria compartida.
  Son límites de selección, no validación de rendimiento. Ningún modelo fue
  descargado por este cambio.
- `Transcript` conserva confianza real, motor, duración, utterance, origen
  barge-in, truncamiento y alternativas hasta Core. Las tools con efecto
  repreguntan si el turno fue truncado, la confianza es baja/desconocida o la intención no es inequívoca;
  consultas de lectura no quedan bloqueadas.
- La calidad STT usa bandas configurables: `<0.20` ruido, `0.20–0.45` dudoso,
  `0.45–0.72` conversación y `>=0.72` acción en los defaults actuales. Una
  frase larga ya no atraviesa Core sólo por tener varias palabras si Vosk le dio
  confianza extremadamente baja. `None` permanece desconocido, no sintético.
- La conversación por voz puede solapar streaming real del backend, segmentación
  por frases y TTS/playback con prefetch bounded de uno. El barge-in deja de
  encolar frases y cancela el callback del modelo; un fallo después de emitir
  audio parcial no empalma otro proveedor. VAD/AEC y cancelación Piper continúan
  pendientes de validación física.
- El lifecycle TTS tiene IDs por turno/generación, descarte de resultados viejos,
  lock del sintetizador y joins acotados. Playback detenido y ONNX todavía
  drenando son métricas distintas; assistant parcial/interrumpido se excluye del
  historial completo.
- `provider=auto` vuelve a ser adaptativo: modalidad/privacidad/complejidad y
  clase de latencia eligen el primary; prioridades sólo ordenan equivalentes y
  fallbacks. Ningún preset remoto es primary automático de voz hasta registrar
  TTFT/reliability y marcarlo explícitamente realtime.
- El provisioning detecta hardware, consulta evidencia independiente por
  `(hardware_class, model_id, runtime)` y produce
  runtime/modelo/contexto/offload/reservas/descarga/consentimiento sin descargar.
  Runtime y CPU/CUDA provienen de la misma medición; compatibilidad declarada no
  sustituye calificación y no se infiere offload. Hardware potente escala al
  mejor modelo calificado que entra; si sólo hay candidatos, el plan queda sin
  modelo productivo y ofrece LAN/remoto.
- La configuración local incorpora un runtime canónico `auto|ollama|llama_cpp`.
  Un plan automático sólo expone un modelo `qualified`, y el factory exige el
  mismo runtime medido; un Ollama sano no sustituye evidencia llama.cpp ni al
  revés. `auto` queda para overrides explícitos de laboratorio.
- El puente instalación/runtime ya usa una selección atómica
  `<node.data_dir>/provisioning/local-ai-selection.json`: sólo
  `lab prepare-ai --activate-selection` puede crearla tras verificar artefacto,
  hash y plan target-qualified. Liga hardware/modelo/runtime/contexto/offload,
  se rechaza si está corrupta o cambia el hardware y no se consulta cuando
  `ai.local.enabled=false`. No se creó ninguna selección ni se descargó ningún
  peso durante esta pasada.
- La captura aplica, en orden, NS WebRTC opcional y después ganancia digital dB,
  AGC acotado con gate de ruido/hold/release y limitador. `pipewire:<node>` recibe target
  explícito; `pipewire` usa el default nativo aun sin `pactl`. Las métricas
  distinguen raw, cada etapa DSP y clean final sin conservar PCM.
  En la última inspección de ASRock, `default` resolvió a USB Composite/Jieli y
  Easy Effects Source seguía separado; el G600 observado en campañas anteriores
  no estaba presente en el inventario más reciente. Easy Effects había sido
  observado a 42%/-22,87 dB. Son hechos del host, no una comparación de calidad.
- El panel de ruido dejó de devolver RMS inventados: mide S16LE real en RAM con
  captura inyectada o responde `not_supported`/`unavailable` honestamente; el
  p95 de silencio propone además el gate raw del AGC sin persistirlo
  automáticamente.
- El lifecycle TTS publica `SPEECH_SYNTHESIS_DRAINED` antes de llevar el drain a
  cero y antes de habilitar otra llamada al backend serializado. La regresión de
  cancelación pasó 100 repeticiones software; falta validación física Piper.
- `ailen lab calibrate-voice` deja preparada la matriz física WebRTC 2/3 por
  380/500/600 ms y un modo de barge-in temprano/medio/tardío. No guarda PCM ni
  modifica configuración. Sin `--device` descubre default/fuentes físicas/
  Easy Effects de forma acotada; con override conserva el target exacto. La
  consola y el JSON separan RMS/peak/SNR raw, gained y processed, clipping,
  ganancia aplicada, falsos VAD y fuente efectiva. La campaña por defecto
  recorre 30/75/100 cm y perfiles `raw`, `noise_only` y `full`; Easy Effects se
  mide sólo como referencia externa sin aplicar un segundo AGC.
- `/audio` ya no anuncia cancelación de eco ni latencia Piper inventada y no
  ejecuta escrituras ALSA sobre `Master`. La lectura corta mide sólo piso/nivel
  del input configurado; la calibración de distancia requiere el harness y
  confirmación humana.
- La campaña `voice-20260901T084132Z-1cfb53` **no calificó ningún micrófono**:
  reunió sólo cinco muestras, una frase y 75 cm. El USB Composite/Jieli obtuvo
  WER 1,0 en raw y 0,5 en los perfiles procesados; hubo entre 6 y 30 falsos
  triggers en tres configuraciones. Easy Effects tuvo WER 0,5 en una sola muestra.
  La recomendación automática de `noise_only` se considera observacional e
  insuficiente, no una calibración exitosa ni un perfil para persistir.
- Para unidades recicladas, el objetivo de producto pasa a ser el micrófono
  integrado/nativo de la placa. El backend ya acepta endpoints físicos ALSA o
  PipeWire, pero el provisionador R6 de audio todavía no existe: los perfiles Lab
  continúan usando `input_device="default"`. El onboarding deberá identificar el
  endpoint, medir 30/75/100 cm y persistirlo sólo tras revisión humana. USB, G600
  y Easy Effects quedan como referencias de laboratorio opcionales, no dependencias.
- Saludos y charla general ya no son `RULE_ONLY`: llegan al LLM. La personalidad
  local de ASRock describe a Ailén como asistente general rioplatense; el taller
  sólo se activa como contexto técnico.

## R6 Vertical 1 — updates firmados en Lab — 2026-08-31

- Existe un vertical no privilegiado completo para releases firmadas:
  manifiesto JSON estricto, firma Ed25519 de bytes exactos con OpenSSL, fuente
  HTTPS acotada, descarga cancelable/reanudable, CAS inmutable y journal atómico.
- La preparación revalida el artefacto y rechaza traversal, links, devices,
  FIFOs, sparse, duplicados, colisiones y expansión fuera de límite. El switch
  usa links atómicos y probation; un candidato unhealthy restaura la release
  anterior sin down-migration ni restore automático de SQLite.
- `build_update_service()` es side-effect-free. La fuente/trust incompleta o el
  modo Appliance devuelven un servicio `DISABLED`; no se inventa disponibilidad.
  El controller actual es exclusivamente `LAB_SIMULATION` in-memory y usa raíces
  inyectadas bajo `runtime/lab/update-simulation` al servir el panel.
- `/actualizaciones` y `/api/updates/*` requieren login/CSRF, aceptan campos
  exactos y consumen sólo `UpdateAdminService`. La Web no ve URLs, hashes, paths,
  tar, procesos o systemd; cerrar el navegador no cancela el worker.
- La aceptación sin red externa firma una release sintética, la verifica,
  descarga, prepara y activa; además demuestra rollback por health fallido y
  reanudación ETag/Range después de re-fetch/reverify/reapproval.
- No existen todavía `ailen-updaterd`, activación privilegiada real, pipeline de
  firma productivo, bundle offline, GC de CAS ni prueba física de power loss,
  disco lleno o rollback. Este vertical no declara soporte 4/8 GB.
- Gate del vertical integrado: 1019 tests, Ruff, mypy en 157 archivos fuente y
  diff-check limpios. Wheel de 195 entradas/3.069.600 bytes sin modelos,
  multimedia, FacePack, binarios nativos, claves ni artefactos Lab; incluye los
  módulos updater y el template de administración.


## R5B FacePack nativo — 2026-08-31

- Los 85 videos fueron inspeccionados visualmente y clasificados en un manifiesto
  trazable: 50 keep, 28 trim/compose, 3 review y 4 discard. Fuentes 83–85 se
  descartan por framing/identidad incompatibles; 39 por drift de fondo.
- `libailen_face_engine.so` implementa C ABI 1.4 sobre C++17 y carga FacePack
  hasta formato 1.6. El contenido vive
  en un `.facepack` externo, no dentro de la librería. Un test carga Pack A y Pack
  B con `embarrassed` usando la misma `.so`, sin recompilarla; el controller
  proyecta la lista dinámica al schema controlado de `FaceExpressionTool`.
- El pack desktop-lab mide 90.247.218 bytes, 480×480, 79 secuencias/2.888
  frames/6 estados. Contiene 39 emociones listables, 28 microacciones y 10 fuentes
  speech. Usa 76 fuentes H3; sólo omite redundancias 2/27, review 28/64/82 y
  discard 39/83–85.
- Runtime usa libjpeg y acceso aleatorio; no abre MP4 ni requiere FFmpeg/OpenCV.
  Los MP4 se conservan sin cambios como materia prima fuera del wheel.
- La QA física aisló una limitación del corpus: ojos/boca recortados de un clip
  H3 deforman la geometría de otro aunque el tracking de pose sea correcto.
  El pack 0.7.0/format 1.6 usa los 28 microgestos y 10 `talk_*` como full-frame
  authored. Speech sigue siendo categoría independiente, reemplaza sólo la base
  visual mientras hay voz y retoma la emoción de Core al finalizar. El engine
  conserva ROI como capacidad versionada para futuros assets verdaderamente
  segmentables; el pack actual no declara capas ROI.
- Expresiones cuyo clip acababa todavía en pose agregan regreso por sus mismos
  frames curados en reversa. El pack comparte payloads JPEG repetidos: no hay
  crossfade, doble cara ni generación de frames. El operador confirmó físicamente
  `blink_double` limpio y mejora clara de labios/dientes; el seam de speech casi
  no se percibe a velocidad real. Falta revisar el showcase completo de retornos.
- Faltantes/corrupción/incompatibilidad/path escape degradan a operación facial
  headless; un error nativo fatal durante render conmuta el mismo `FaceController`
  a `NullFaceController`. `pixel` permanece como elección manual. `facepack` es
  default y no existe fallback automático a `portrait`.
- Preflight separa Tkinter de la capacidad nativa: sólo informa FacePack `PASS`
  después de cargar ABI y pack; un fallo informa `WARN` y el display facial queda deshabilitado.
- ASRock bajo load 13.13/14.28/13.57: library load 1.267 ms, pack load/checksum
  181.368 ms, RSS incremental 3.79 MiB, update+copy con speech full-frame
  0.920 ms avg / 1.485 ms p95. Engine consumió 0.841% de un core idle y 2.560%
  durante speech; Tk animado midió 16.482%/27.217%/42.506% de un core a
  480/720/1080 px presentados. No extrapolar.
- Linux/X11 fue compilado y probado. La CMake/DLL Windows y perfiles LOW en
  Raspberry/Banghó/SF20BA siguen pendientes de prueba física.
- Auditoría post-Codex: las expresiones FacePack usan timing natural por defecto (`duration_seconds=0`) en vez de heredar holds de 5/7.5 s del renderer legacy. Portrait interpreta 0 como su default histórico.
- Cierre histórico específico de R5B: 767 tests, Ruff, mypy 146+6, C++17 con
  `-Wall -Wextra -Wpedantic -Werror`, diff-check y wheel sin assets runtime
  prohibidos en verde. Wheel: 183 entradas/3.018.784 bytes.


## Auditoría física de regresiones ASRock — 2026-08-26

- Latencia: se confirmó doble inferencia en comentarios con palabras temporales
  genéricas. El routing semántico ahora usa sólo hints declarados; `hoy está
  fresco` vuelve a una inferencia. El historial ya no abre por sí solo el parser:
  `muy bien` tras Clock midió semantic 0.3 ms (`attempted=false`), 458 tokens de
  entrada, main LLM 1.340 s y turno texto total 1.354 s. La telemetría separa
  resolvers, tool, prompt-eval, generación, TTS/chunks, primer PCM y playback.
- Audio G600/PipeWire: período/buffer explícitos estabilizaron frames de 20 ms
  (p95 observado 128.6 -> 22.66 ms). Hangover ya no satisface por sí mismo
  `min_speech_ms`. El G600 produjo pulsos idle ~0.012–0.023 RMS que alargaban
  utterances hasta 15 s; threshold Lab 0.022 las cerró en 0.26–1.98 s. No es un
  default global y debe revalidarse con micrófono sano/voz baja.
- Barge-in: el token de cancelación llega hasta `aplay`, `stop()` funciona desde
  otro thread y los frames sobreviven processing/cooldown. Se observaron cortes
  de 0.2 ms durante conversación y el audio preservado produjo transcript correcto.
- NC250: gestión verificada en NIGHT=3 sin persistir credenciales. RTSP HD entregó
  frames recientes con thread vivo; YuNet, presencia raw/estable y Core llegaron a
  `present=true` con operador en cuadro. Un episodio de tres read timeouts degradó
  salud y reconectó la misma ruta correctamente. VGA no abrió en este firmware.
- Piper usa prefetch acotado de una oración. Los chunks integrados observados
  tuvieron `gap_ms=0`; en muestras aisladas el residual fue ~13–219 ms frente a
  ~1.36–1.43 s sin prefetch.
- WebSearch implícito funcionó por DDGS real y no cayó a generación libre, pero el
  turno textual midió 8.644 s: semantic 1.564 s, provider 4.669 s y resumen Qwen
  2.386 s. Tras limitar el default a los tres resultados que Core realmente usa y
  mover la guía específica a cada tool, una repetición midió 4.988 s: semantic
  1.374 s, provider 2.030 s y resumen 1.581 s. La red y la longitud generada varían;
  sigue siendo demasiado lento para voz y aún conserva dos inferencias seriales.
- Actualidad Web: `DDGS.text()` entregó snippets sin año y Qwen presentó por error
  Python 3.14 como futura. `WebSearchRequest` ahora separa `text|news`, acota
  frescura y propaga `published_at` desde `DDGS.news()`. Core descarta noticias sin
  timestamp válido o fuera de ventana, y «No results found» se normaliza como
  búsqueda vacía honesta. Una consulta ambigua por «Python» devolvió noticias
  fechadas de serpientes y el resumen las rechazó como irrelevantes; al especificar
  «lenguaje de programación Python», routing midió 1.807 s, DDGS 1.654 s y no hubo
  resultados válidos del día, sin síntesis posterior que inventara actualidad.
- Conversación textual: la frase casual con «día» registró deterministic 0.6 ms,
  semantic 0.5 ms con `attempted=false`, 398 tokens de entrada y turno total
  1.777 s. El bloque de capacidades vacío ya no entra al prompt. En seis muestras
  casuales la mediana fue 1.559 s y 42.5 tokens de salida; Qwen todavía agrega
  preguntas/ofertas de soporte de forma variable, por lo que naturalidad no se
  considera cerrada ni se aplicó un filtro que pueda borrar preguntas legítimas.
- Expresiones: estado y gesto transitorio están separados; TTS ya no borra el
  gesto explícito. El renderer pixel usa una malla de 4 px, contornos de dos
  escalones y tres tonos a 800x480; once gestos acotados tienen geometría propia
  y la boca articula aun bajo un gesto. Demo ASRock: 2.1% CPU de proceso y 25.9 MB
  RSS a 30 FPS. La revisión fue aceptada visualmente por el operador; no existe
  todavía metadata emocional espontánea desde el turno conversacional.
- Decisión histórica del 2026-08-29, hoy supersedida: `portrait` fue entonces el
  renderer por defecto y `pixel` su alternativa. Ambos se conservan sólo como
  selecciones manuales; FacePack es ahora el default y cualquier fallo queda
  headless, sin fallback gráfico automático.
- Pendiente: repetir TTFAR/escucha con micrófono sano; optimizar navegación sin
  dos inferencias seriales; acotar respuestas todavía largas de Qwen y diseñar metadata
  expresiva conversacional sin dar control directo de UI al modelo.

## Actualización Debian / R4 software — 2026-08-24

- Vision deja de depender de un periférico concreto: `[vision].camera_source` admite `auto`, `usb` o `rtsp`. `usb` nunca cae silenciosamente a red, `rtsp` falla cerrado si falta configuración/secret y `auto` prioriza V4L2 antes de RTSP. Configs antiguas con `network_camera_preferred=true` se migran al cargar; la opción nueva explícita siempre prevalece. El Lab Debian queda en `camera_source="usb"`; la NC250 continúa como fuente RTSP opcional de red y no bloquea este host. La webcam reciclada USB aún no fue conectada/validada físicamente en Debian.
- Recordatorios persistentes R4: migración `0004_reminders`, `RemindersTool`, `ReminderService` y evento `REMINDER_DUE`. Frases con tiempo explícito (`en 20 minutos`, `mañana a las 10`, fecha/hora) se separan de notas atemporales y timers volátiles. El scheduler sólo publica eventos; el runner encola TTS hasta quedar en IDLE/ATTENTION para respetar half-duplex. La base Lab Debian ya está en schema 4; anuncio acústico real queda pendiente de prueba física.
- Debian Lab tiene Ollama 0.32.15 en el HDD de 4 TB y `qwen3.5:2b-q4_K_M` medido sobre RX 580 vía Vulkan (100% GPU, ~15.45 tok/s en benchmark corto). Vosk sigue STT activo; Whisper.cpp tiny/base están instalados y verificados para comparación física posterior.
- `MprisMusicService` implementa transporte local real sobre MPRIS mediante `playerctl`, con argv explícito, `shell=False`, timeout acotado y fail-closed cuando no existe backend/player. Lab lo registra detrás de `MusicTool`; las queries de texto libre no se reinterpretan como archivos o URLs.
- La reproducción musical audible todavía NO está validada físicamente en este host; el ítem R4 permanece abierto hasta probar un reproductor MPRIS real.
- Una instalación limpia en Debian reveló que `ailen diagnose ai` y `ailen demo ai` podían consultar `ai_usage` antes de ejecutar migraciones. Ambos caminos ahora migran SQLite antes de construir `BudgetPolicy`.
- Entorno Debian de desarrollo preparado con `.venv`, OpenCV/Piper y tooling. Suite: 503 tests pasan y 1 se omite por asset/hardware no presente; Ruff limpio ignorando únicamente `EXE002` causado por semántica de permisos del montaje NTFS, mypy limpio en 129 archivos y `git diff --check` limpio.
- `AGENTS.md` y `docs/operations/AGENT_HANDOFF.md` fueron actualizados para evitar que Gemini/OpenCode trabajen con el estado obsoleto de Foundation.

## Qué existe

- carpeta del proyecto creada en `/mnt/hdd4tb/repo/ailen`;
- definición del producto;
- plan maestro;
- arquitectura inicial;
- roadmap hasta 1.0.0;
- changelog y versionado inicial;
- reglas para agentes y contribución;
- estructura documental inspirada en AndesKey;
- comportamiento del producto documentado (`PRODUCT_BEHAVIOR.md`);
- plan de implementación operativo (`IMPLEMENTATION_PLAN.md`);
- contratos entre módulos (`MODULE_CONTRACTS.md`);
- task board de R1, R2A, R2B, R3A y R3B (`TASKS.md`);
- handoff específico para Gemini/OpenCode/Codex (`AGENT_HANDOFF.md`);
- matriz de aceptación verificable (`ACCEPTANCE_MATRIX.md`);
- carpetas preparadas para código, pruebas, scripts, empaquetado y releases.

- Foundation/Core ejecutable (`pyproject.toml`, CLI `ailen`, versión unificada);
- Sistema de configuración tipado con `schema_version` y plantilla versionada (`config/ailen.example.toml`);
- Logging estructurado con redacción automática de secretos y tokens;
- Diagnóstico de hardware best-effort (`ailen diagnose hardware`) y recomendador de perfiles;
- RuntimeState y HealthService observables;
- EventBus in-memory ligero con suscripciones tipadas, aislamiento de errores y correlation IDs;
- SocialEngine determinista con modos sociales (`HOME`, `WORKSHOP`, `SHOP`, `PUBLIC`, `PRIVATE`, `SLEEP`), cooldown y deduplicación por sesión de presencia;
- `SocialPrivacyPolicy` determinista fuera del LLM con aislamiento inviolable de memorias privadas en `PUBLIC` y `SHOP`;
- `InteractionCoordinator` orquestando ciclo de presencia física, transiciones de estado, decisiones sociales y publicación de eventos;
- `PersonalityBoundary` con límites inviolables sobre seguridad, herramientas y privacidad;
- Panel web utilizable desde celular: `SettingsService` con allowlist de campos administrables, vista `/config` responsive (GET/POST con CSRF, validación server-side, guardado atómico del TOML), identidad del personaje configurable (`[identity].display_name`, voz) separada de la marca AILEN;
- Autenticación administrativa persistente por usuario + contraseña en SQLite (migración `0002_admin_credentials`, ADR-007): PBKDF2-HMAC-SHA256 con 600k iteraciones, salt aleatorio, comparación constant-time, lockout por IP, fail-closed sin credencial; CLI `ailen admin set-password` vía getpass;
- Hardening HTTP baseline del panel: límite de body (413), métodos permitidos (405), Content-Type exigido en POST (415), CSP/Referrer-Policy/no-store, timeout de socket; fallos de diagnóstico no tiran abajo el panel;
- SQLite endurecida con permisos owner-only (`0600`) en POSIX porque contiene memoria privada y credencial administrativa derivada;
- `SettingsService.update()` usa semántica de patch parcial; la Web traduce checkboxes HTML ausentes a `false`;
- Motor lógico de rostro `FaceAnimator` y modelo `FacePose` agnóstico de renderer, con parpadeo no periódico, micro-movimientos y apertura de boca;
- Baseline de despliegue aceptado en ADR-008: Debian 13 stable amd64 netinst/minimal, sin entorno de escritorio; con Tkinter se usa sólo Xorg/xinit/python3-tk y los nodos headless no instalan X;
- Backend gráfico POC `TkinterFaceController` (sin dependencia pip, requiere `python3-tk`/stack gráfico del sistema) y `NullFaceController` para headless; consumo real pendiente de benchmark físico;
- `VisionDebouncer` con confirmación asimétrica de presencia/ausencia y gracia de dropout;
- Backend de cámara `OpenCvVisionBackend` con YuNet preferido en Lab para rostro/posición y Haar como alternativa experimental explícita;
- Formato canónico de audio: PCM 16-bit signed LE, mono, 16000 Hz (`src/ailen/audio/pcm.py`) con RMS matemático puro;
- VAD en Python puro (`EnergyVad`) con umbral configurable y hangover; benchmark lógico DEV documentado sin extrapolar porcentaje de CPU a hardware objetivo;
- `UtteranceCollector` con defaults actuales de pre-roll 200 ms, mínimo de habla 250 ms, silencio final 700 ms y corte máximo 15 s;
- `AudioTurnGate` bloquea STT normal durante processing/TTS; barge-in inspecciona RMS por separado, cancela playback y conserva audio de usuario;
- Backends I/O reales ALSA (`AlsaAudioInputBackend`, `AlsaAudioOutputBackend`, `AlsaDeviceEnumerator`) y fakes para CI/tests;
- Backend STT local offline `VoskSttBackend` (extra `[stt-vosk]`) y alternativa `WhisperCppSttBackend` (`whisper-cli` actual, nombres legacy best-effort); no inventan confidence cuando el motor no lo provee;
- Backend TTS local offline `PiperTtsBackend` por la API Python canónica, con voz cacheada y PCM incremental; no existe fallback CLI/WAV;
- `AudioInteractionCoordinator` integrando micrófono, turn gate, VAD, STT, TTS y un nivel de boca RMS básico durante playback;
- AI Router determinista `RuleBasedRouter` con perfiles de hardware (`SATELLITE`, `CLOUD`, `HYBRID`, `LOCAL`, `LAN_BRAIN`) y destinos reales `local`, `lan_brain` y `remote:<provider_id>`; los reason codes actuales incluyen privacidad, complejidad, realtime, presupuesto y disponibilidad;
- `OutboundPrivacyPolicy` fail-closed para LAN no confiable y remotos nombrados; nunca rebaja silenciosamente información `RESTRICTED`/`PRIVATE`;
- `SecretResolver` seguro para API keys desde variables de entorno o archivos `0600`, con enmascaramiento total en logs y reportes;
- `BudgetPolicy` por proveedor, consultando `ai_usage` en SQLite para frenar cargos remotos ante límites diarios o mensuales;
- `AiContextBuilder` produce prompts mínimos acotados y reconstruye el boundary remoto sin historial, memoria privada, tools ni paths;
- Transportes HTTP activos: OpenAI Responses, Anthropic Messages y OpenAI Chat-compatible, con streaming, timeouts y taxonomía de fallos;
- Backends locales Ollama/llama.cpp, cliente `LanBrainAiBackend` y remotos nombrados. `CloudAiBackend` fue retirado y sólo queda migración compatible desde configuraciones históricas;
- `AiOrchestrator` ejecutando la secuencia de fallback con degradación limpia y registro de telemetría en SQLite;
- `ConversationCoordinator` unificando Transcript STT -> Context -> Router -> Orchestrator -> TTS speak();
- Subsistema de Hardware Multiplataforma (`src/ailen/hardware/`): `LinuxHardwareAdapter`, `WindowsHardwareAdapter`, `FakeHardwareAdapter` y `HardwareDetector` produciendo `HardwareCapabilityReport` sin inventar capacidades sintéticas;
- `ModelCatalog` declarativo e inmutable (`src/ailen/models/catalog.py`) con soporte para `ModelPurpose` (`SANITY`, `BALANCED`, `QUALITY`), alias de runtime y modelos GGUF 2026 verificados con Git LFS (`qwen3.5-0.8b-q4_0`, `qwen3.5-0.8b-q8_0`);
- `ModelPlanner` adaptativo con márgenes de seguridad (60% RAM, 80% VRAM), comprobación de disco libre y CPU flags en GPU offload;
- `ModelStore` y `ModelDownloader` endurecidos contra path traversal, fail-closed con HTTPS forzado y renombre atómico;
- `RuntimeModelInventory` consultando modelos cargados en Ollama (`/api/tags`, `/v1/models`) y mapeando nombres/alias explícitos;
- `ManagedLlamaRuntime` gestionando el ciclo de vida de procesos `llama-server` / `llama serve` propios de AILEN con loopback estricto `127.0.0.1` y ownership de procesos respetado;
- `LabComponentFactory` (`src/ailen/runtime/factory.py`) con regla estricta "No Silent Fakes" (los fakes sólo se activan con `--simulate`);
- `LabRunner` (`src/ailen/runtime/runner.py`) con cableado end-to-end de hardware real (Face GUI Tkinter, Visión OpenCV, Audio ALSA, Vosk/Whisper STT, Piper TTS, AI Router), single-flight interaction lock y telemetría de sesión `LabSessionMetrics`;
- `LabDoctor` (`src/ailen/runtime/doctor.py`) con diagnósticos de solo lectura, remediaciones explícitas y salida `--json`;
- Comandos CLI operativos: `ailen lab inspect`, `ailen lab start [--simulate] [--fullscreen]`, `ailen lab doctor [--json]`, `ailen lab prepare-ai [--yes] [--start-runtime]`, `ailen lab benchmark`, `ailen models list`, `ailen models plan [--purpose]`, `ailen models fetch`, `ailen models verify`;
- Baseline integrado vigente: 1164 tests; Ruff limpio, mypy limpio en 168 archivos fuente, `git diff --check` y wheel de 211 entradas validados. Los conteos menores de R3B.2 se conservan sólo en documentos históricos.

## Qué NO existe todavía

- backend gráfico de producción nativo DRM/KMS para appliance sin X11 (actualmente POC Tkinter + Headless);
- servidor LAN Brain dedicado/discovery automático (existe el backend cliente LAN, no el servicio de fleet/brain final);
- updater Appliance productivo (`ailen-updaterd`, systemd y pruebas físicas);
  sólo existe el Vertical 1 firmado en `LAB_SIMULATION`;
- release productivo del FacePack: el default lógico Linux/X11 existe, pero faltan DLL Windows, packaging de release y validación en hardware objetivo;
- retornos H3 naturales de varias emociones intensas y lip-sync fonémico/visemas; el slice actual usa mouth level y transición curada;
- benchmarks físicos en hardware objetivo (Banghó Zero G05 / SF20BA).

## Hardware objetivo inmediato

### Prototipo

Banghó Zero G05:

- 8 GB RAM;
- M.2 500 GB;
- pantalla/cámara/audio integrados disponibles para el prototipo.

### Laboratorio

Linux Mint y Windows 11 se tratarán como **Lab Mode**: AILEN se levanta sin convertir el equipo en appliance ni cambiar login/suspensión/arranque. Allí se probarán rostro, logs, cámara, micrófono, STT/TTS, diagnóstico, selección/descarga de LLM y fluidez. La estrategia está documentada en `docs/deployment/LAB_AND_APPLIANCE_MODES.md`.

### Próximos objetivos

1. SF20BA 8 GB;
2. SF20BA 4 GB;
3. equipos 2 GB en modo Satellite/Cloud;
4. placas con pantalla rota usando monitor externo o modo sin pantalla.

## Próxima decisión técnica

`ADR-006` pasa a baseline provisional aceptado para el ciclo 0.4.x: Python modular, SQLite, Web stdlib/HTML liviano, Face desacoplado, audio local, STT/TTS opcionales y proveedores de IA detrás de contratos. Los benchmarks en Banghó/SF20BA siguen siendo autoridad para cualquier cambio del stack de appliance.

La decisión visual R5B está registrada en ADR-012: engine C ABI y FacePack externo
detrás del contrato existente. La siguiente decisión no es reescribir Core, sino
validar DLL/release packaging y medir un perfil LOW real; `portrait` no participa
en failover automático.

## Próximo milestone

Consolidar `0.4.0-dev.0`: ordenar el working tree, cerrar documentación R4/R5,
completar validaciones físicas (sesión conversacional con FacePack, recordatorio
audible, MPRIS y STT comparativo), y validar R5B fuera de ASRock. El siguiente hito
de plataforma es R6 Appliance Debian 13 minimal; no se etiqueta release mientras
el árbol esté sin auditar o la suite completa/wheel no hayan vuelto a verde.

Trabajo inmediato definido en `TASKS.md` y `docs/operations/AGENT_HANDOFF.md`.

El repositorio Git local está inicializado en `main` y conectado a `git@github.com:vicktorgabriel/ailen.git`. El baseline auditado previo a R3B.4 es `2c2f6c3`. No se hace push sin autorización explícita.

## Higiene de release 0.4.x

- `VERSION` y `pyproject.toml` están alineados en `0.4.0-dev.0` / `0.4.0.dev0`; el runtime usa una autoridad de versión centralizada y los launchers ya no hardcodean el número.
- `run.sh` es el launcher canónico; `scripts/run_ailen.sh` sólo delega a él para evitar dos copias divergentes.
- artefactos generados obsoletos (`build/`, `*.egg-info`, wheel 0.1.0) fueron eliminados y se regenerarán sólo en el gate de release.
- MP4 H3 crudos están ignorados por Git y no forman parte del `package-data`; deben seguir disponibles localmente para la futura clasificación con Codex.
- no se crea commit/tag/release sin autorización explícita y sin volver a ejecutar suite completa, Ruff, mypy, diff-check y build/inspección del wheel cuando H3 haya liberado recursos.

## Riesgos conocidos

- latencia y consumo real en SF20BA aún desconocidos;
- compatibilidad gráfica sin X/Wayland aún no validada;
- STT/TTS óptimos por perfil aún no medidos;
- costo cloud estimado pero aún no medido con tráfico real;
- nombre `AILEN` fijado para proyecto/plataforma; queda pendiente sólo la verificación marcaria/legal antes de comercialización formal;
- soporte de equipos de 2 GB sujeto a pruebas reales.

## Actualización física R3B.3 — 2026-08-22

- `AUDIO CONVERSATION PASS` confirmado en Asrock/Linux Mint con G600 USB, sin simulación.
- Pipeline validado: micrófono -> VAD -> Vosk -> Router -> Ollama `qwen3.5:9b` -> Piper -> auricular.
- Mint Lab usa routing `pipewire` para evitar exclusión `arecord`/`aplay` sobre el mismo hardware USB.
- Ollama local usa backend nativo `/api/chat`, `think=false` y keep-alive de laboratorio para reducir cold-start; la identidad sigue viviendo en Core.
- Modo voz normaliza Markdown/URLs/símbolos antes de Piper y acota respuestas; defaults LAB: 500 ms de silencio final y 96 tokens máximos.
- Suite posterior a la validación: 349 tests; Ruff, mypy sobre 109 source files y diff-check verdes.
- Cámara YuNet y Face GUI Tkinter ya están disponibles en Lab; queda mejorar robustez STT y repetir Vision con una cámara mejor cuando esté disponible.

## Decisión adaptativa posterior al AUDIO CONVERSATION PASS — 2026-08-22

- La RTX 3060 de Asrock es sólo laboratorio; AILEN no requiere GPU.
- Se adopta ADR-010: inferencia adaptativa por hardware y tools controladas por Core.
- Perfiles objetivo: RULE_ONLY/SATELLITE, FAST, BALANCED y QUALITY; un modelo estable por nodo/sesión, sin cambiarlo por consulta.
- Acciones básicas (hora, timer, volumen, música, notas, status) deben ser deterministas; el LLM sólo interpreta cuando es necesario.
- Internet se implementará como `web_search`/`web_fetch` controlados, nunca como acceso irrestricto del LLM.
- Candidato FAST prioritario para benchmark: Llama 3.2 3B; alternativas Gemma 3 4B y Qwen3.5 4B con thinking desactivado.
- Próximo bloque: R3B.4 Adaptive Runtime + Voice Latency; luego R3C Product Behaviors + Controlled Tools + Web.
## Auditoría R3B.4 — 2026-08-22

- Se corrigió el benchmark para usar `/api/chat` nativo de Ollama; el shim OpenAI no se usa para `think=false`.
- `FIRST(ms)` es primer turno observado, no cold start; `TOK/S` sólo se informa con `eval_count/eval_duration` reales del runtime.
- Se eliminaron aliases peligrosos entre modelos distintos y se bloquea cualquier upshift de perfil por encima del hardware medido.
- El planner prefiere el menor footprint entre candidatos que ya satisfacen propósito/perfil.
- El backend OpenAI-compatible genérico no expone `reasoning_content` ni recibe controles específicos de Ollama.
- `RecommendedDeployment` reutiliza `HardwareDetector`; modelo y costo externo permanecen desconocidos hasta resolución/configuración real.

## Validación física Vision — 2026-08-23

- Webcam reciclada de notebook convertida a USB detectada como `HD Webcam`; stream usable `/dev/video1`.
- OpenCV 4.14.0 + Haar frontal/profile fallback; `/dev/video1` auto-seleccionado si `/dev/video0` no existe.
- `ailen demo vision` confirmó presencia y gaze variable; `lab start --headless` registró 211 observaciones y 2 transiciones reales en 12.34 s.
- Estado: `YUNET FACE DETECTION PASS` con la webcam reciclada actual. Tkinter/Face GUI disponibles. Haar queda experimental; YuNet es el detector preferido del Lab para rostro/posición, con limitación de estabilidad en baja luz/movimiento.

- YuNet 30 s controlado: tramo inicial sin persona limpio, rostro presente con confidence ~0.92-0.95 y gaze variable. PASS para face detection; objetos/escena siguen fuera de capacidad.

## Validación física Benchmarks — 2026-08-23

- `ailen lab benchmark-vision` (CPU, Ryzen 5 5500, 640x480, 5 FPS):
  - YuNet: 60/60 detecciones con rostro presente; latencia avg ~49 ms, p50 ~51 ms, p95 ~91 ms, max ~159 ms; confianza avg/min ~0.91/0.89; gaze x [+0.74,+0.85], y [-0.24,-0.22]. Aceptable a 5 FPS en CPU puro.
  - Haar (experimental): 40/40 con rostro presente pero avg ~67 ms con picos >500 ms y sin confianza calibrada.
  - Reportes JSON en `runtime/lab/vision_benchmarks/`; fases etiquetadas por el operador (`--phase`), sin inferencia de falsos positivos automática.
- `ailen lab benchmark-stt`: utterance generada con Piper ("Detecto un rostro frente a la cámara."), mismo WAV por motor:
  - Vosk small-es 0.42: OK, latencia ~407 ms, WER 0.143 (transcribió "detectó" en vez de "detecto"). Ejemplo del problema de calidad de Vosk.
  - whisper.cpp: `NOT_INSTALLED` (binario y modelo ggml ausentes); sin descarga automática.
- Limitación conocida web_fetch: validación DNS anti-SSRF es pre-conexión; DNS rebinding sofisticado requiere transporte con IP fijada (pendiente, documentado en WEB_SEARCH_BOUNDARY.md).

## Mejora de comprensión de voz — 2026-08-23

- Sesión física auditada: 24 utterances; Vosk aceptó 22, pero el problema principal fue el resolver demasiado literal.
- Fast path ampliado para ASR imperfecto (`hora es`, `notas tengo`, `nota ...`, variaciones de `más/menos volumen`).
- Nuevo fallback semántico local restringido: Qwen puede interpretar intención y proponer una tool local permitida, pero Core valida esquema/permisos y ejecuta. Network/destructive quedan fuera de este parser.
- Consultas contextuales de notas ya pueden recuperar contenido por tokens (`qué tengo que comprar mañana` -> `comprar estaño mañana`).
- Fragmentos vagos de una sola palabra se repreguntan para evitar que el LLM complete desde contexto viejo.
- Contexto Vision deja de ser saliente en cada respuesta; no debe repetirse la presencia salvo relevancia.
- ClockTool usa hora local del sistema, no UTC.
- Baseline de cierre: 487 tests; Ruff/mypy/diff-check verdes.
- Siguiente validación física: repetir la conversación de voz y medir cuántos turnos terminan en reprompt, tool determinista, semantic-tool y chat real. STT Vosk sigue siendo una limitación independiente y debe compararse con Whisper.cpp usando WER real G600.

## Comprensión natural + cámara NC250 — 2026-08-23

- Auditoría del historial físico confirmó que Notes sí persistía `comprar estaño mañana`; los fallos estaban en resolución de intención/contexto y en respuestas inventadas por el LLM general.
- IntentResolver acepta variantes naturales/ASR de hora y notas; follow-ups recientes de notas se resuelven localmente antes del LLM.
- Fragmentos ambiguos de dominio piden aclaración específica en vez de ejecutar o inventar continuidad.
- SemanticToolIntentResolver reduce la allowlist según dominio y usa timeout configurable.
- Lab separa `qwen2.5-coder:3b` como `intent_model` opcional del conversacional `qwen3.5:9b`; nunca descarga el modelo y vuelve al backend principal si no está instalado.
- Validación actual: 491 tests; Ruff limpio; mypy limpio en 129 archivos; diff-check limpio.
- TP-Link NC250 descubierta por Bonjour como `NC250-162889.local` / `192.168.1.157`. Panel HTTP local en 80; RTSP autenticado en 554 `/h264_hd.sdp` verificado con H.264 1280×720 + audio mono 8 kHz. Credenciales no se persisten en configuración/docs.

### Ajustes posteriores de inteligencia y NC250 — 2026-08-24

- Se corrigió un falso positivo del parser semántico: los hints ahora se comparan como términos léxicos completos, evitando que `dia` coincida dentro de palabras como `inmediato` y dispare herramientas sin intención real.
- Preguntas de capacidades (`qué podés hacer`, equivalentes) se responden desde el `ToolRegistry` y estado real de Core, sin permitir que el LLM invente funciones no instaladas.
- El contexto de memoria aclara que historial/memorias entregados por Core sí son memoria disponible, pero instrucciones del sistema, metadatos y sensores no deben narrarse como conversación previa.
- Se amplió el filtrado de cierres de voz genéricos para reducir repetición mecánica.
- Reproducción end-to-end de los fallos físicos previos ahora resuelve `hora es`, `ahora es`, creación/listado/búsqueda de notas y follow-ups de compra por tool local en ~9-22 ms.
- NC250 validada también como fuente de micrófono: RTSP expone audio PCMU mono 8 kHz y ffmpeg lo remuestreó a 16 kHz con señal física no nula. La integración como `AudioInputBackend` de AILEN sigue pendiente; por ahora el audio principal continúa por PipeWire/G600.
- `runtime/lab/ailen-lab.toml` quedó preparado para preferir la NC250 por RTSP con contraseña obtenida sólo desde `AILEN_CAMERA_PASSWORD`; el preflight y `lab start --headless` quedan READY con `rtsp://192.168.1.157:554/h264_hd.sdp` sin exponer credenciales.
- La NC250 continúa en `daynightmode=2` (Día). El firmware expone Auto=1, Día=2, Noche=3; la activación física de IR nocturno queda pendiente de pasar manualmente a Auto/Noche y repetir detección YuNet.
- Validación posterior: 501 tests; Ruff limpio; mypy limpio en 129 archivos; `git diff --check` limpio.
