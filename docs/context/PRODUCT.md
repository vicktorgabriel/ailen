# Producto — AILEN

> AILEN — Asistente Inteligente Local, Evolutivo y Natural. Nombre estable del proyecto/plataforma; el nombre, voz y apariencia del personaje son configurables por instalación.

## 1. Visión

Convertir hardware informático antiguo o parcialmente averiado en asistentes físicos útiles, expresivos y fáciles de mantener para hogar, taller y comercio.

AILEN debe sentirse como un dispositivo dedicado con presencia propia, no como una notebook reutilizada ejecutando un chatbot.

## 2. Problema que resuelve

Existe una gran cantidad de notebooks y PCs antiguas cuyo hardware todavía es suficiente para audio, cámara, red, pantalla y tareas ligeras, pero resulta incómodo para uso de escritorio moderno. Al mismo tiempo, pequeños comercios y talleres pueden beneficiarse de un asistente conversacional sencillo sin comprar hardware específico costoso ni mantener aplicaciones complejas.

AILEN une ambos problemas:

- reutiliza hardware existente;
- agrega una capa conversacional útil;
- evita requerir una aplicación móvil nativa;
- permite administración centralizada por navegador;
- aprovecha APIs económicas cuando el hardware local no alcanza.

## 3. Casos de uso prioritarios

### Taller

- búsquedas técnicas rápidas;
- lectura de notas y procedimientos;
- guardar mediciones y observaciones;
- reproducir música;
- temporizadores y recordatorios;
- conversación breve mientras el usuario trabaja con las manos ocupadas;
- detectar presencia de una persona y llamar la atención del usuario.

### Comercio

- saludo al detectar ingreso;
- responder preguntas frecuentes del negocio;
- explicar servicios, horarios y formas de pago;
- reproducir música;
- derivar al responsable cuando no tiene una respuesta confiable;
- conversación breve y socialmente moderada con clientes.

### Hogar

- compañía conversacional ligera;
- música;
- consultas web;
- notas y recordatorios;
- presencia y contexto básico.

## 4. Experiencia deseada

El usuario enciende el equipo y no ve un escritorio Linux. Aparece directamente el rostro del asistente.

El dispositivo:

- mira a las personas detectadas;
- escucha una palabra de activación o interacción configurada;
- responde con una voz definida;
- conserva memoria local;
- puede desarrollar rasgos persistentes de personalidad dentro de límites establecidos;
- entra en reposo visual cuando no se usa;
- se administra desde el celular o PC por una web responsive.

## 5. Personalidad

La personalidad pertenece a AILEN Core y no al proveedor de IA.

Se modelará mediante:

- semilla inicial persistente;
- rasgos configurables;
- límites de comportamiento;
- preferencias adquiribles de forma lenta;
- contexto social (`HOME`, `WORKSHOP`, `SHOP`, `PUBLIC`, `PRIVATE`, etc.);
- historial de cambios explicable;
- capacidad de congelar o reiniciar evolución.

La evolución nunca habilita capacidades ni permisos nuevos. Sólo modifica expresión, preferencias y estilo dentro de límites seguros.

## 6. Identidad separada del cerebro

AILEN es la plataforma; el personaje visible es una identidad configurable por instalación. El asistente conserva esa identidad aunque cambie de modelo, voz o proveedor.

```text
Identidad AILEN
├── personalidad
├── memoria
├── historial
├── preferencias
├── estado
└── reglas

Cerebros intercambiables
├── LLM local
├── LLM LAN
└── API cloud
```

Cambiar Qwen, Mistral, Gemini, OpenAI u otro proveedor no debe crear un personaje nuevo.

## 7. Perfiles de hardware

### Satellite/Cloud

Orientado a 2 GB o CPUs muy limitadas.

- rostro;
- audio;
- cámara ligera;
- wake word;
- memoria básica;
- Core;
- inferencia remota por LAN o cloud.

### Cloud

Orientado a 2–4 GB.

- mismo comportamiento visible;
- API externa como cerebro conversacional principal;
- comandos y funciones sencillas locales.

### Hybrid

Orientado a 4–8 GB.

- LLM pequeño local;
- API externa como refuerzo;
- LAN Brain opcional.

### Local

Orientado a equipos más modernos.

- LLM local principal;
- nube opcional;
- mayor autonomía.

## 8. Arquitectura comercial inicial

El producto se venderá inicialmente como unidad física configurada para un comercio/taller local.

El cliente recibe:

- dispositivo;
- instalación preparada;
- asistente configurado;
- panel web privado;
- actualizaciones;
- documentación mínima de uso.

No se requiere una app móvil nativa.

## 9. Límites explícitos del MVP

No forman parte del primer MVP:

- robot caminante;
- navegación autónoma general por escritorio (el navegador aislado y los archivos
  acotados con confirmación son objetivo posterior, ver ADR-014);
- shell libre controlado por el LLM (fuera de alcance, ADR-014 nivel N4);
- domótica compleja;
- reconocimiento facial obligatorio;
- videovigilancia avanzada;
- visión multimodal pesada permanente;
- agentes autónomos de larga duración;
- procesamiento financiero o administrativo crítico.

## 10. Criterio de éxito del primer prototipo

El prototipo será considerado exitoso cuando una Banghó Zero G05 pueda ejecutar de forma estable durante una jornada:

1. rostro animado;
2. cámara y detección simple de presencia;
3. STT y TTS;
4. conversación híbrida;
5. memoria persistente;
6. música;
7. consultas web controladas;
8. panel responsive autenticado;
9. arranque automático;
10. actualización recuperable.

## 11. Criterio de éxito comercial inicial

El primer piloto comercial debe demostrar:

- instalación sencilla;
- uso intuitivo por el comerciante;
- interacción agradable con clientes;
- latencia aceptable;
- costo de API bajo y medible;
- ausencia de mantenimiento manual diario;
- funcionamiento continuo estable;
- actualización remota/local confiable.
