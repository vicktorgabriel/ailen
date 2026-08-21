# Comportamiento del producto — AILEN

> AILEN es el nombre estable del proyecto/plataforma. Este documento define cómo debe sentirse y comportarse el asistente. El nombre, voz y apariencia del personaje son configurables por instalación.

## 1. Principio de producto

AILEN no debe sentirse como una notebook con un chatbot abierto. Debe sentirse como un dispositivo físico dedicado, presente en el ambiente, capaz de ver, escuchar, hablar, recordar y usar herramientas limitadas.

La personalidad, memoria, historial y reglas pertenecen al Core. El LLM es un recurso reemplazable para lenguaje y razonamiento ligero.

## 2. Casos de uso prioritarios

### Taller

El asistente debe poder:

- saludar al propietario cuando detecta presencia tras un período razonable;
- escuchar consultas con las manos ocupadas;
- buscar información técnica rápida;
- leer una respuesta en voz alta;
- guardar y recuperar notas de una reparación;
- reproducir música;
- controlar volumen/play/pause;
- crear recordatorios o temporizadores simples;
- recordar contexto reciente del trabajo cuando sea apropiado;
- permanecer callado cuando no es necesario intervenir.

Ejemplos de intención:

- "Buscame el datasheet del BQ24780."
- "¿Qué voltaje debería tener REGN?"
- "Guardá que REGN mide 6,05 V."
- "¿Qué había medido en REGN?"
- "Poné música."
- "Recordame revisar la temperatura en media hora."

### Comercio

El asistente debe poder:

- detectar que una persona entró o se acercó;
- mirar hacia la persona antes de hablar cuando la cámara lo permita;
- saludar una sola vez dentro de una ventana configurable;
- responder información cargada del comercio;
- responder preguntas abiertas simples;
- derivar al comerciante cuando no sabe;
- reproducir música si está permitido;
- evitar conversaciones intrusivas o excesivas;
- no exponer información privada del propietario.

Información comercial administrable:

- nombre y descripción del negocio;
- horarios;
- servicios;
- medios de pago;
- preguntas frecuentes;
- políticas básicas;
- mensaje/estilo de bienvenida;
- datos que el asistente puede comunicar públicamente.

## 3. Modos sociales

El Core debe soportar, como mínimo:

- `WORKSHOP`: informal, técnico, acceso a memoria privada autorizada.
- `SHOP`: orientado a atención, cordial y poco intrusivo.
- `HOME`: más informal y personal.
- `PUBLIC`: máxima restricción de memoria privada.
- `PRIVATE`: permite utilizar recuerdos privados autorizados.

Un modo social no cambia permisos del sistema operativo. Sólo limita contexto, lenguaje, iniciativa y exposición de memoria.

`SHOP` y `PUBLIC` nunca deben incluir espontáneamente recuerdos privados en prompts cloud ni en respuestas a terceros.

## 4. Presencia y atención

Estados visuales mínimos:

- `IDLE`
- `ATTENTION`
- `LISTENING`
- `THINKING`
- `TALKING`
- `SLEEP`
- `ERROR/DEGRADED` sólo si hace falta comunicar una falla

Comportamiento esperado:

### IDLE

- microanimaciones leves;
- parpadeo no perfectamente periódico;
- mirada suave sin consumo de CPU elevado;
- no hablar espontáneamente sin una razón definida.

### ATTENTION

- ocurre ante presencia o interacción;
- orientar pupilas hacia la cara detectada;
- puede elevar párpados/expresión brevemente;
- no implica que deba saludar siempre.

### LISTENING

- mirada más estable;
- feedback visual claro de que el micrófono está capturando;
- evitar sonidos innecesarios que interfieran con STT.

### THINKING

- animación discreta;
- puede mirar ligeramente a otro punto;
- nunca debe congelar la UI mientras espera red o inferencia.

### TALKING

- boca aproximada al nivel/tiempo del audio;
- movimiento sutil, no lip-sync pesado obligatorio;
- se puede mantener seguimiento visual de la persona.

### SLEEP

- aparece tras inactividad configurable;
- reduce animación y, si el hardware lo permite, brillo/uso de cámara;
- wake word o evento permitido lo despierta;
- debe ser un estado funcional de ahorro, no sólo estético.

## 5. Saludo automático

El saludo es un comportamiento del Social Engine, no del LLM.

Requisitos:

- cooldown configurable;
- debounce de presencia para evitar saludos por falsos positivos;
- no repetir saludo por cada frame/cara detectada;
- considerar conversación activa y cantidad aproximada de personas;
- permitir desactivarlo;
- permitir variantes naturales de una lista o mediante IA, pero sin depender de IA para funcionar.

Flujo de referencia:

```text
persona detectada
    -> presencia estable
    -> cooldown vencido
    -> modo permite saludo
    -> orientar mirada
    -> TTS saludo
    -> registrar evento
```

## 6. Personalidad

### 6.1 Semilla

Cada identidad puede nacer con una semilla persistente que inicializa rasgos dentro de rangos seguros, por ejemplo:

- curiosidad;
- sociabilidad;
- humor;
- formalidad;
- iniciativa;
- paciencia;
- expresividad.

La semilla se genera una sola vez salvo reset explícito.

### 6.2 Evolución

La evolución debe ser lenta, explicable y acotada.

Puede influirse por:

- frecuencia de interacción;
- tipos de tareas;
- estilos de respuesta valorados;
- música y actividades frecuentes;
- correcciones explícitas del usuario;
- tiempo de convivencia.

No puede modificar:

- permisos de tools;
- reglas de seguridad;
- presupuesto cloud;
- configuración de privacidad;
- capacidad de acceder a shell;
- política `PUBLIC/PRIVATE`.

### 6.3 Preferencias

Puede desarrollar preferencias simuladas y persistentes, pero nunca debe presentarlas como consciencia real. Ejemplo: tender a elegir un género musical recurrente o adquirir un estilo de saludo.

Las preferencias deben poder:

- inspeccionarse desde administración;
- resetearse;
- congelarse;
- evolucionar a velocidad configurable.

## 7. Memoria

Distinguir al menos:

- contexto corto de conversación;
- sesiones históricas;
- recuerdos explícitos;
- hechos del negocio;
- preferencias;
- historial de personalidad;
- eventos y tools.

No todo mensaje se convierte automáticamente en recuerdo permanente.

La recuperación inicial debe priorizar SQLite/FTS5 y filtros semánticos simples. No agregar vector DB hasta medir una necesidad real.

## 8. Conversación y nube

El Core construye contexto mínimo para cualquier proveedor externo.

Nunca enviar por defecto:

- historial completo;
- base de memoria completa;
- secretos;
- API keys;
- logs internos;
- información privada no relevante;
- imágenes/cámara salvo acción explícita y backend autorizado.

Un modelo cloud puede recibir:

- instrucciones mínimas de identidad/estilo;
- modo social actual;
- fragmentos de memoria estrictamente relevantes;
- conversación reciente necesaria;
- resultados de tools que deba resumir.

## 9. IA híbrida

Orden conceptual de recursos:

1. regla/intent/tool determinista;
2. LLM local si corresponde;
3. LAN Brain si está disponible y es adecuado;
4. cloud rápido/económico si está permitido.

El orden real puede cambiar por política, latencia, privacidad o capacidad de hardware.

Casos que NO deberían usar LLM:

- subir/bajar volumen;
- play/pause;
- timers simples;
- hora si ya existe tool;
- saludo por presencia;
- cambio de modo;
- estado del sistema;
- animaciones.

## 10. Degradación

AILEN debe degradar capacidades, no colapsar.

### Sin Internet

Debe conservar, según perfil:

- rostro;
- presencia;
- configuración local;
- música local;
- notas/memoria;
- acciones deterministas;
- LLM local si existe;
- TTS/STT local si existen.

### Sin LAN Brain

Usar local o cloud según política.

### Sin cloud

Usar local/LAN/tools y comunicar limitación sólo cuando afecte la petición.

### Sin cámara

Debe seguir siendo asistente de voz/pantalla.

### Sin pantalla

Debe existir modo `HEADLESS/VOICE` en hardware compatible.

## 11. Rostro

El rostro debe ser ligero y abstracto, no un avatar 3D pesado.

Elementos mínimos:

- fondo;
- ojos/pupilas;
- párpados;
- boca;
- opcionalmente cejas o elementos simples.

Objetivo: generar presencia mediante movimiento, timing y atención, no mediante detalle gráfico.

El diseño visual final puede ser tematizable, pero el motor no debe depender de assets de alta resolución.

## 12. Cámara

MVP:

- detectar persona/rostro;
- estimar coordenadas para mirada;
- presencia estable;
- captura explícita si una tool lo solicita.

No MVP:

- reconocimiento facial obligatorio;
- vigilancia permanente;
- identificación biométrica de clientes.

Futuro opt-in:

- QR;
- códigos de barra;
- reconocimiento de usuario autorizado;
- tracking más avanzado.

## 13. Audio

MVP:

- enumerar y seleccionar micrófono/parlante;
- VAD/wake word o mecanismo equivalente;
- STT español suficientemente rápido;
- TTS español local preferible;
- evitar feedback/acople en lo posible;
- volumen controlado por tool;
- reproducción de música separada del pipeline de voz.

## 14. Música

La música es una tool del Core, no una tarea del LLM.

Debe soportar inicialmente:

- archivos locales;
- playlists;
- play/pause/stop;
- volumen;
- consulta de pista actual.

Streams/radio online pueden agregarse si no complican el MVP.

## 15. Administración

Todo nodo debe exponer una administración web responsive autenticada.

No se requiere app Android/iOS.

Áreas previstas:

- Dashboard;
- Comercio;
- Comportamiento;
- Personalidad;
- Memoria;
- Audio/Voz;
- Cámara/Presencia;
- IA y presupuesto;
- Tools;
- Sistema/Hardware;
- Actualizaciones;
- Diagnóstico.

En modo multi-nodo, un Manager puede administrar varios nodos por LAN.

## 16. Hardware físico

El primer prototipo no debe desarmarse hasta validar software, audio, cámara y display.

En una unidad física dedicada:

- reutilizar placa, pantalla, cámara, micrófono y parlantes cuando sea viable;
- retirar baterías envejecidas si el uso será permanente y no aportan valor;
- conservar disipación y ventilación segura;
- aceptar monitor externo en placas con display roto;
- permitir modo sin pantalla si el hardware es demasiado limitado;
- futuro: microcontrolador para LEDs/servos, sin cargar al Core con control de tiempo real.

## 17. Experiencia comercial deseada

El dueño del comercio no debe configurar prompts ni conceptos de IA.

Debe poder completar formularios humanos como:

- "Información de mi negocio";
- "Cómo quiero que salude";
- "Qué puede responder";
- "Nivel de conversación";
- "Presupuesto mensual de IA";
- "Qué funciones están habilitadas".

La tecnología subyacente debe permanecer oculta salvo en el área avanzada/diagnóstico.

## 18. Fuera de alcance inicial

- robot móvil;
- humanoide;
- visión multimodal pesada continua;
- navegación autónoma general por escritorio;
- shell libre;
- domótica irrestricta;
- agentes autónomos de larga duración;
- ERP/POS completo;
- reconocimiento biométrico obligatorio;
- cloud obligatorio para arrancar.
