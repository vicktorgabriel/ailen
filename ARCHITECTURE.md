# Arquitectura — AILEN

> Nombre de trabajo provisional. Este documento es la fuente canónica de arquitectura del proyecto.

## 1. Objetivo arquitectónico

AILEN debe ejecutar un asistente físico expresivo en hardware heterogéneo, desde netbooks de 2 GB hasta PCs modernas, sin acoplar identidad, memoria ni experiencia del usuario a un modelo de IA concreto.

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
                         │     Cloud Provider    │
                         │  modelo rápido/API   │
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
│  └──────────────────┘              │ rules/local/LAN/cloud      │     │
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

El rostro debe ser vectorial/2D y barato de renderizar.

Responsabilidades:

- ojos y pupilas;
- párpados;
- cejas opcionales;
- boca simple;
- expresiones;
- parpadeo no determinista;
- mirada hacia coordenadas provistas por Vision;
- animación de escucha/procesamiento/habla/reposo;
- sincronización simple de boca con amplitud o marcas del TTS.

No generar imágenes mediante IA en runtime.

El backend gráfico definitivo se decidirá por ADR después de probar DRM/KMS/SDL2 y una alternativa mínima sobre X/Wayland si fuera necesaria por drivers.

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
microphone -> VAD/wake -> buffer -> STT -> text
```

El backend podrá variar por hardware:

- local ultraligero;
- local de mayor calidad;
- remoto opcional.

El Core recibe texto normalizado más metadatos mínimos, no depende del backend.

## 10. Speech / TTS

El TTS debe admitir backend local y, si se decide, remoto.

La salida debe publicar eventos para la cara:

- `speech_started`;
- nivel aproximado;
- `speech_finished`.

La selección de dispositivo de audio debe ser configurable desde el panel.

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
5. cloud.

No es obligatorio seguir ese orden para cada petición. El router considera:

- perfil de hardware;
- tipo de tarea;
- disponibilidad;
- privacidad;
- latencia histórica;
- costo;
- preferencia de instalación;
- longitud del contexto.

### Ejemplos

`subir volumen` -> herramienta local, sin LLM.

`qué anoté de esta placa` -> búsqueda SQLite + LLM local/cloud si hace falta redactar.

`explicame este componente` -> local, LAN o cloud según router.

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

El detector de hardware sugerirá, pero no impondrá, uno de:

- `satellite`;
- `cloud`;
- `hybrid`;
- `local`;
- `lan_brain`.

Los umbrales se definirán con benchmarks del prototipo, no de forma fija en esta etapa.

## 24. Decisiones abiertas

- stack definitivo del Core;
- framework web;
- backend gráfico;
- STT baseline por perfil;
- TTS baseline;
- LLM baseline local;
- proveedores cloud iniciales;
- protocolo multi-node;
- sistema de descubrimiento LAN;
- formato final de releases;
- nombre comercial.

Cada decisión estructural deberá registrarse como ADR.
