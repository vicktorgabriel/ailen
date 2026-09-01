# Arquitectura — AILEN

> Nombre de trabajo provisional. Este documento es la fuente canónica de arquitectura del proyecto.

## 1. Objetivo arquitectónico

AILEN debe ejecutar un asistente físico expresivo en hardware heterogéneo. Un
nodo autónomo de producto apunta a equipos reciclados de 4 a 8 GB y debe poder
conversar completamente local; una máquina de 2 GB sólo puede considerarse
satélite si una medición demuestra ese perfil. Una PC potente puede aprovechar
GPU y prestar LLM/TTS por LAN, pero no define el requisito mínimo.

La arquitectura prioriza:

1. identidad local persistente;
2. degradación progresiva ante falta de Internet/LAN/modelo;
3. bajo consumo en reposo;
4. módulos reemplazables;
5. administración web responsive;
6. seguridad por allowlist de capacidades;
7. actualización recuperable;
8. observabilidad y medición por perfil de hardware.

## 2. Vista general

```text
                         ┌───────────────────────┐
                         │ Remote Provider(s)   │
                         │ Responses/Chat/SSE   │
                         └───────────┬───────────┘
                                     │
                             HTTPS / gateway
                                     │
┌────────────────────────────────────┼───────────────────────────────────┐
│                         AILEN NODE                                     │
│                                                                         │
│  ┌───────────────┐      ┌───────────────────────────────────────────┐  │
│  │ Face / Vision │◄────►│                AILEN Core                │  │
│  └───────────────┘      │ session · policy · personality · router  │  │
│  ┌───────────────┐      └──────┬─────────┬──────────┬──────────────┘  │
│  │ Hearing / STT │◄────────────┘         │          │                 │
│  └───────────────┘                        │          │                 │
│  ┌───────────────┐                        ▼          ▼                 │
│  │ Speech / TTS  │◄────────────────── Memory      Tools              │
│  └───────────────┘                     SQLite    allowlisted           │
│                                           │                            │
│  ┌──────────────────┐              ┌──────┴─────────────────────┐     │
│  │ Responsive Web UI│◄────────────►│         AI Router          │     │
│  └──────────────────┘              │ rules/local/LAN/remote:*   │     │
│                                    └──────┬───────┬─────────────┘     │
└───────────────────────────────────────────┼───────┼────────────────────┘
                                            │       │
                                       Local LLM  LAN Brain
```

## 3. Regla fundamental: identidad != modelo

La identidad de AILEN está compuesta por datos y reglas del Core:

- personalidad;
- memoria;
- preferencias;
- contexto social;
- relaciones configuradas;
- historial;
- voz/rostro seleccionados;
- permisos;
- evolución permitida.

Los modelos son **motores de inferencia reemplazables**.

Un cambio de proveedor, cuantización o modelo no debe resetear ni redefinir el personaje.

## 4. Procesos previstos

La implementación inicial puede comenzar como monolito modular para acelerar el prototipo. La separación en procesos sólo se hará donde aporte aislamiento o ahorro real.

Nombres lógicos previstos:

- `ailen-core`;
- `ailen-face`;
- `ailen-audio`;
- `ailen-vision`;
- `ailen-web`;
- `ailen-updater`;
- `ailen-node-agent`.

En equipos muy limitados algunos módulos pueden vivir dentro del mismo proceso.

## 5. AILEN Core

Responsabilidades:

- máquina de estados global;
- sesión actual;
- eventos de presencia;
- coordinación STT/LLM/TTS;
- selección del motor de IA;
- construcción de contexto;
- aplicación de políticas;
- llamada a herramientas;
- memoria;
- personalidad;
- presupuesto de API;
- eventos para la UI/rostro.

No debe depender de un proveedor cloud específico.

## 6. Máquina de estados de interacción

Baseline:

```text
BOOTING
   └──> IDLE
          ├──> ATTENTION
          │      └──> LISTENING
          │              └──> PROCESSING
          │                      ├──> TOOL
          │                      │     └──> PROCESSING
          │                      └──> SPEAKING
          │                              └──> IDLE / ATTENTION
          └──> SLEEP
                  └──> IDLE / ATTENTION
```

Estados de error y degradación deben ser ortogonales al estado expresivo:

- Internet offline;
- LAN Brain offline;
- micrófono no disponible;
- cámara no disponible;
- cloud budget agotado;
- local model no disponible.

## 7. Face

El rostro debe ser 2D, barato de renderizar y reemplazable detrás de
`FaceController`. A partir de R5B `facepack` es el default lógico; los renderers
anteriores se conservan sólo como elecciones manuales:

- `facepack`: engine nativo C++17 + pack externo de frames curados;
- `portrait`/`vector`: renderers Tkinter legacy seleccionables manualmente;
- `pixel`: renderer mínimo explícito para displays/hardware muy restringidos.

Si engine/pack falla, el contrato se degrada a headless. No existe una ruta
automática `facepack -> portrait`.

Responsabilidades:

- ojos y pupilas;
- párpados;
- cejas opcionales;
- boca/articulación independiente de la emoción;
- expresiones;
- parpadeo no determinista;
- mirada hacia coordenadas provistas por Vision;
- animación de escucha/procesamiento/habla/reposo;
- sincronización de boca con amplitud o, cuando exista, visemas del TTS.

No generar imágenes mediante IA en runtime.

El engine nativo no reproduce MP4. Los videos H3, FFmpeg, OpenCV y YuNet son
insumos exclusivos del compilador offline. Runtime recibe un `.facepack`
versionado con tablas, checksums y payloads JPEG accesibles por frame:

```text
Core: state / expression / gaze / speech
                  │
                  ▼
        ctypes + C ABI estable
                  │
                  ▼
  libailen_face_engine.so / ailen_face_engine.dll
                  │
                  ▼
       ailen_default.facepack externo
```

Estados persistentes son una base neutral más microacciones no periódicas con
esperas/cooldowns. No se hace loop de un clip idle/listening completo. FacePack
1.4 compone base/expresión + delta ROI de ojos/cejas + ROI labial de reemplazo
alineado. El compilador conserva el movimiento real de cabeza/cuerpo en clips
full-frame y registra la pose de la cara por frame para aplicar ojos y boca en la
posición, rotación y escala correctas. Los retornos curados recorren frames reales,
sin crossfade ni mezcla de dos rostros. Las microacciones full-frame de cabeza se
ejecutan cuando no hay una expresión transitoria. Agregar una emoción modifica
assets/manifest/FacePack, no el engine.

El transporte final de display puede evolucionar de Tk/X11 a SDL2/DRM/KMS sin
cambiar Core ni el formato lógico. Ver ADR-012 y `FACEPACK_FORMAT_V1.md`.

## 8. Vision

MVP:

- cámara configurable;
- detección de rostro/persona a baja frecuencia;
- centroides/coordenadas para mirada;
- evento `person_entered` y `person_left` con debounce;
- captura manual explícita.

Fuera del MVP:

- identificación facial automática;
- vigilancia;
- seguimiento biométrico;
- análisis de emociones.

## 9. Hearing / STT

Pipeline conceptual:

```text
captura continua -> VAD/final de turno -> STT -> Transcript -> Core
```

El backend podrá variar por hardware:

- local ultraligero;
- local de mayor calidad;
- remoto opcional.

El Core recibe un turno normalizado con texto, confianza acústica real o
desconocida, motor, duración, identificador, origen barge-in, truncamiento y
alternativas si existen. Barge-in no implica que la frase esté cortada; alcanzar
el límite máximo de captura sí. La confianza no se sintetiza cuando el backend no la entrega ni se
reemplaza con la confianza semántica del resolver.

Las acciones con efectos secundarios requieren turno no cortado, confianza
acústica suficiente e intención inequívoca. Ante duda se repregunta; el texto
no se descarta silenciosamente antes de que Core pueda aplicar esta política.

## 10. Speech / TTS

El TTS debe admitir Piper local siempre disponible y backends expresivos locales
o LAN, como Chatterbox, en equipos capaces. Todos atraviesan el mismo coordinador
de audio.

La salida debe publicar eventos para la cara:

- `speech_started`;
- nivel aproximado;
- `speech_finished`.

La selección de dispositivo de audio debe ser configurable desde el panel.

El modo de llamada solapa etapas sin esperar la respuesta completa:

```text
LLM delta -> segmentador de frase seguro -> cola TTS bounded(1) -> playback
```

La captura permanece activa para barge-in. La interrupción detiene playback,
suprime frases futuras y propaga cancelación hacia TTS/modelo cuando el backend
lo permite. El estado y las colas se limpian por turno. El contrato no promete
cancelar una operación nativa que el backend no pueda abortar, ni llama
"streaming" a dividir una respuesta ya completa.

Cada habla tiene `turn_id/generation_id`. Cancelar invalida resultados tardíos,
detiene playback y libera lógicamente el turno. Un sintetizador no concurrente
queda serializado; si una inferencia ONNX no cancelable sigue activa, termina en
background y su drain se mide sin permitir que reproduzca PCM obsoleto. Una
respuesta interrumpida no se incorpora como mensaje assistant completo.

## 11. Memory

SQLite será baseline.

Esquema conceptual inicial:

```text
users
sessions
messages
memories
business_facts
preferences
personality_state
personality_events
tool_events
api_usage
device_state
settings
```

Principios:

- memoria privada local por defecto;
- FTS5 antes de introducir vectores;
- retención configurable;
- exportación y borrado explícitos;
- no enviar historial completo a cloud;
- contexto cloud construido sólo con información necesaria.

## 12. Personality Engine

La personalidad es una simulación persistente y explicable, no una capacidad autónoma del LLM.

Contendrá:

- semilla única por identidad;
- rasgos base;
- límites mínimos/máximos;
- cambios lentos;
- preferencias aprendidas;
- eventos que justifican cambios;
- modos sociales;
- opción de congelar evolución.

Regla: personalidad nunca modifica permisos, seguridad, presupuesto ni acceso a herramientas.

## 13. AI Router

Orden conceptual de resolución:

1. regla/intención local;
2. herramienta directa;
3. LLM local;
4. LAN Brain;
5. uno o más `remote:<provider_id>`.

No es obligatorio seguir ese orden para cada petición. El router considera:

- perfil de hardware;
- tipo de tarea;
- disponibilidad;
- privacidad;
- latencia histórica;
- costo;
- preferencia de instalación;
- longitud del contexto.

Con `provider=auto`, esas señales eligen primero la clase de backend; las
prioridades numéricas ordenan opciones equivalentes y fallbacks, no sustituyen
la política adaptativa. Una preferencia explícita se honra si sigue siendo
elegible. En voz, un provider medido como no-realtime no se promueve
automáticamente a primary.

Ollama y llama.cpp comparten `AiBackend`/`StreamingAiBackend`; LAN y proveedores
externos implementan el mismo límite. El router no depende de un runtime concreto
y agota los backends elegibles antes de degradar. `ai.local.enabled=false` es una
decisión estricta de esa instalación: no descubre, arranca, calienta ni usa local;
no elimina la capacidad local del producto.

El saludo y la conversación abierta llegan al LLM. El resolver determinista se
reserva para routing, herramientas verificables, errores operativos y repreguntas
de STT; no actúa como chatbot genérico.

### Ejemplos

`subir volumen` -> herramienta local, sin LLM.

`qué anoté de esta placa` -> búsqueda SQLite + LLM local/LAN/remoto si hace falta redactar.

`explicame este componente` -> local, LAN o remoto según router.

`cuánto está X ahora` -> web tool + síntesis.

## 14. Tools

Todas las herramientas deben declarar contrato, permisos y límites.

Baseline:

- `music`;
- `web_search`;
- `web_fetch`;
- `notes`;
- `reminders`;
- `business_info`;
- `system_status`;
- `time_weather` mediante backend apropiado.

Nunca exponer shell arbitrario al modelo.

Las herramientas con efectos deben validar argumentos independientemente de la salida del LLM.

## 15. Modos sociales

Modos iniciales:

- `HOME`;
- `WORKSHOP`;
- `SHOP`;
- `PUBLIC`;
- `PRIVATE`;
- `SLEEP`.

`SHOP/PUBLIC` deben impedir que recuerdos privados se incluyan espontáneamente en respuestas frente a clientes.

## 16. Manager / Web UI

Primera fase: servidor web local en cada nodo.

Debe ofrecer:

- login;
- dashboard;
- hardware/health;
- configuración;
- información del comercio;
- personalidad;
- voz;
- cámara;
- IA y presupuesto;
- sesiones/memoria con controles de privacidad;
- actualización;
- diagnóstico.

Segunda fase: manager multi-nodo por LAN con descubrimiento y pairing.

No se requiere app Android/iOS. La UI debe funcionar como web responsive/PWA si resulta útil.

## 17. Multi-node

Un nodo tiene identidad criptográfica propia.

El pairing debe ser explícito.

El Manager puede administrar varios nodos, pero una caída del Manager no debe apagar funciones locales del nodo.

Un `LAN Brain` es un servicio opcional de inferencia; no almacena la identidad como autoridad.

## 18. Configuración

Separación prevista:

```text
/etc/ailen/ailen.toml          configuración del sistema
/var/lib/ailen/ailen.db        memoria/estado
/var/lib/ailen/secrets/         secretos con permisos restrictivos
```

La configuración versionada será sólo una plantilla sin secretos.

## 19. Instalación Debian

Objetivo final:

- Debian 13 minimal;
- usuario dedicado;
- systemd;
- sin GNOME/KDE/XFCE;
- arranque automático;
- pantalla dedicada al rostro;
- red administrable desde web;
- política de energía apropiada;
- logs rotados;
- watchdog de servicios.

El backend gráfico debe validarse en hardware real antes de declarar que puede prescindir completamente de X/Wayland.

## 20. Releases y updater

Distribución prevista:

```text
/opt/ailen/releases/<version>/
/opt/ailen/current -> releases/<version>
```

Estado persistente fuera de `/opt/ailen/releases`.

Proceso:

1. consultar manifest;
2. descargar asset compatible;
3. verificar hash/firma;
4. instalar en directorio nuevo;
5. validar preflight;
6. cambiar `current`;
7. reiniciar;
8. health check;
9. rollback si falla.

Canales previstos:

- `nightly` sólo desarrollo;
- `beta` prototipos/pilotos;
- `stable` clientes.

## 21. Seguridad

Baseline obligatoria:

- hash robusto de contraseña;
- rate limit/lockout del panel;
- sesiones con expiración;
- CSRF cuando corresponda;
- escucha de administración sólo LAN por defecto;
- secretos fuera del repo;
- allowlist de tools;
- ningún shell libre;
- actualización firmada/verificada;
- logs redactados;
- contexto cloud mínimo;
- separación PUBLIC/PRIVATE;
- pairing autenticado para multi-node.

## 22. Métricas

Cada perfil se validará con:

- RAM idle;
- RAM peak;
- CPU idle/peak;
- temperatura;
- latencia wake-to-STT;
- latencia STT-to-first-token;
- latencia first-token-to-audio;
- tiempo de respuesta total;
- costo por consulta cloud;
- uptime;
- errores por backend.

## 23. Hardware profiles

El detector produce una recomendación explicable. `ProvisioningPlanner` la
combina con catálogo y calificación específica de esa clase de hardware para
emitir un `ProvisioningPlan` con runtime, modelo/fallback, contexto, offload,
reservas, descarga y acciones consentidas. No descarga ni promueve un modelo sin
consentimiento, descriptor verificado y evidencia `qualified` del hardware
objetivo.
Los envelopes actuales son límites de planificación, no soporte certificado:

- `< 3,5 GB`: sin presupuesto local autónomo declarado; candidato satélite;
- `4 GB nominal`: contexto 1024, hasta 1400 MB para modelo y piso libre de
  700 MB;
- `8 GB nominal`: contexto 2048, hasta 3000 MB para modelo y piso libre de
  1200 MB;
- `16 GB nominal`: contexto inicial 4096 y reserva de al menos 1800 MB;
- `32 GB nominal`: contexto inicial 8192 y reserva de al menos 3000 MB;
- `64 GB+`: contexto inicial 16384 y reserva de al menos 6000 MB.

Desde 16 GB no existe un techo fijo universal para el modelo: el presupuesto es
la RAM actualmente disponible menos la mayor entre la reserva mínima y el 15%
de la RAM total. En GPU se usa únicamente la VRAM dedicada disponible de un
adaptador compatible; una iGPU/memoria compartida no se suma otra vez a la RAM.
Contexto, modelo y offload finales quedan además limitados por evidencia
calificada del artefacto y runtime exactos.

Una GPU dedicada se perfila por VRAM medida y puede habilitar un modelo mayor y
Chatterbox local sin convertirlos en requisito. Un nodo `lan_brain` expone el
mismo contrato de inferencia/TTS a clientes confiables; el cliente conserva
Core, privacidad, Vosk y Piper y vuelve a local/externo según su política.

AILEN carga un GGUF verificado bajo demanda y puede descargar de memoria un
modelo local ocioso cuando cruza el piso de su perfil. No detiene runtimes ajenos
ni cambia de modelo por turno. El runtime persistido por provisioning
(`ollama` o `llama_cpp`) es vinculante: otro runtime sano no puede reutilizar su
calificación. Cada tier requiere medir RSS/peak, TTFA, calidad,
tokens/s y convivencia con Vosk, Piper, SQLite y rostro en el hardware objetivo.

La frontera plan/runtime se materializa en
`data/provisioning/local-ai-selection.json`: el instalador sólo puede escribirla
con consentimiento explícito después de verificar el artefacto exacto. El
registro atómico `0600` liga clase de hardware, modelo, runtime, contexto,
CPU/CUDA, offload y SHA-256. Al arrancar, Core la consume únicamente si
`ai.local.enabled=true` y no existe un override Lab; si falta, fue alterada,
cambió el hardware o el hash no coincide, falla cerrado y no promueve el
candidato diagnóstico. La reevaluación ocurre al provisionar/reconfigurar, no
por consulta.

Los modos operativos siguen siendo `satellite`, `cloud`, `hybrid`, `local` y
`lan_brain`; el administrador puede forzar una opción compatible.

## 24. Decisiones abiertas

- stack definitivo del Core;
- framework web;
- backend gráfico;
- STT baseline por perfil;
- TTS baseline;
- modelo/quant local aprobado por tier tras benchmark físico;
- benchmark y calificación realtime de proveedores remotos iniciales;
- protocolo multi-node;
- sistema de descubrimiento LAN;
- formato final de releases;
- nombre comercial.

Cada decisión estructural deberá registrarse como ADR.
