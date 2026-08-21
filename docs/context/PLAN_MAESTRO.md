# Plan Maestro — AILEN

> AILEN es el nombre estable del proyecto/plataforma. Documento canónico de alcance global.

## 1. Objetivo

Construir una plataforma modular para transformar hardware reciclado en asistentes físicos conversacionales administrables por LAN, con identidad local persistente y capacidad de usar IA local, LAN o cloud según el hardware y la tarea.

## 2. Estrategia de desarrollo

El desarrollo seguirá una progresión de hardware descendente:

1. PC potente de laboratorio para experimentar y medir.
2. Banghó Zero G05 de 8 GB como primer prototipo físico real.
3. SF20BA de 8 GB.
4. SF20BA de 4 GB.
5. hardware de 2 GB en modo Satellite/Cloud.

El objetivo no es optimizar desde el primer día, sino obtener primero una arquitectura correcta y luego reducir consumo con benchmarks reales.

## 3. Hardware disponible para desarrollo

### Laboratorio principal

- AMD Ryzen 5 5500.
- 48 GB DDR4.
- RTX 3060 12 GB VRAM.
- SSD/NVMe y almacenamiento HDD.

Uso: probar modelos, cuantizaciones, STT/TTS, visión y cargas de referencia. No establecer dependencias que obliguen a tener GPU dedicada.

### Laboratorio secundario

- AMD FX-8350.
- 20 GB RAM.
- GPU con 8 GB VRAM.

Uso: pruebas de servidor/hub, compatibilidad y rendimiento secundario.

### Equipo adicional

- Dell Optiplex 3050.
- Intel Core i7.
- 12 GB DDR4.

Uso potencial: Hub/LAN Brain o nodo moderno cuando no interfiera con su uso actual.

### Primer prototipo

- Banghó Zero G05.
- 8 GB RAM.
- M.2 500 GB.

Uso: primera instalación end-to-end.

### Objetivo económico

- SF20BA y otras netbooks gubernamentales.
- 2–8 GB DDR3/DDR3L según unidad.
- placas con pantalla dañada reutilizables con monitor externo.

## 4. Arquitectura objetivo

```text
                         Cloud APIs
                             │
                       API Gateway
                             │
                  ┌──────────┴──────────┐
                  │ Assistant Manager  │
                  │ UI web / updates   │
                  └──────────┬──────────┘
                             │ LAN
               ┌─────────────┼─────────────┐
               │             │             │
           LAN Brain      Node A        Node B
           opcional       Taller        Comercio
               │             │             │
             LLM          Core/Face     Core/Face
           potente        Audio/Vision  Audio/Vision
```

Cada nodo debe poder funcionar parcialmente aunque Manager, LAN Brain o Internet estén caídos.

## 5. Componentes lógicos

### AILEN Core

Autoridad del personaje y coordinador principal:

- sesión;
- estados;
- memoria;
- personalidad;
- permisos;
- intents;
- router IA;
- herramientas;
- políticas de privacidad.

### Face

Motor 2D liviano:

- ojos;
- pupilas;
- párpados;
- boca;
- expresiones;
- estados `IDLE`, `ATTENTION`, `LISTENING`, `THINKING`, `TALKING`, `SLEEP`;
- seguimiento visual simple.

### Vision

- detección de persona/rostro;
- posición aproximada;
- presencia;
- captura explícita;
- QR/código de barras en etapas posteriores.

No se requiere reconocimiento de identidad en MVP.

### Hearing / STT

- wake word;
- captura de audio;
- VAD;
- transcripción;
- posibilidad de backend local o remoto.

### Speech / TTS

- voz local por defecto cuando sea viable;
- sincronización aproximada de boca por nivel/temporización;
- dispositivo de audio configurable.

### Memory

SQLite como baseline:

- sesiones;
- mensajes;
- recuerdos;
- configuración;
- hechos del negocio;
- preferencias;
- historial de personalidad;
- historial de herramientas;
- métricas de uso/costo.

FTS5 será la primera estrategia de recuperación. No introducir base vectorial hasta demostrar necesidad.

### AI Router

Decide entre:

1. reglas/intent local;
2. LLM local;
3. LAN Brain;
4. API cloud.

La decisión considera:

- complejidad;
- disponibilidad;
- latencia;
- RAM/CPU;
- privacidad;
- presupuesto;
- modo operativo.

### Tools

Contratos controlados para:

- música;
- búsqueda web;
- información del negocio;
- notas;
- recordatorios;
- hora/clima;
- estado del sistema.

El LLM no recibe shell general.

### Manager Web

Servidor web responsive para:

- autenticación;
- estado;
- configuración;
- información del comercio;
- voz;
- rostro;
- IA;
- presupuesto API;
- logs redactados;
- actualizaciones;
- dispositivos;
- backups;
- personalidad y memoria administrable.

Primera etapa: Manager local en el propio nodo. Etapa posterior: descubrimiento y administración de múltiples nodos.

### Updater

- consulta de releases;
- canales `stable`, `beta` y opcional `nightly`;
- verificación de hash/firma;
- instalación paralela por versión;
- cambio atómico de symlink;
- health check;
- rollback.

## 6. Modelo de inferencia híbrida

### Local primero para acciones triviales

No usar LLM para:

- volumen;
- pausa/play;
- hora;
- abrir/cerrar modo música;
- saludos automáticos por evento;
- estados visuales.

### Cloud rápido para conversación ligera

Adecuado para:

- atención básica;
- preguntas abiertas cortas;
- explicación simple;
- resumen de resultados web;
- conversación social.

### LAN Brain opcional

Adecuado para:

- consultas más complejas;
- pruebas de modelos mayores;
- varios nodos compartiendo inferencia.

### Local LLM

Adecuado para:

- modo offline;
- privacidad;
- equipos con suficiente memoria;
- tareas breves y contextos pequeños.

## 7. Seguridad y privacidad

Reglas base:

- ninguna API key hardcodeada ni versionada;
- la UI web requiere usuario y contraseña;
- contraseñas almacenadas mediante hash robusto;
- administración sólo LAN por defecto;
- API keys preferentemente en Manager/Gateway, no distribuidas a satélites;
- herramientas con allowlist;
- no shell libre desde prompts;
- contexto cloud reducido al mínimo necesario;
- secretos y memoria separados del árbol de releases;
- logs redactados;
- permisos de modo `SHOP/PUBLIC` que impidan filtrar recuerdos privados.

## 8. Distribución prevista

```text
/opt/ailen/releases/<version>/
/opt/ailen/current -> releases/<version>
/var/lib/ailen/
    ailen.db
    memories/
    assets/
    voices/
/etc/ailen/
    ailen.toml
/run/ailen/
    runtime.json
```

El nombre de rutas cambiará si el nombre final del producto cambia antes del primer release público.

## 9. Filosofía de rendimiento

Se debe medir:

- RAM idle;
- RAM durante STT;
- RAM durante inferencia;
- CPU idle;
- latencia speech-to-first-audio;
- temperatura;
- uso de disco;
- costo cloud por interacción;
- estabilidad en jornada prolongada.

La optimización se hará con perfiles de hardware reales, no por intuición.

## 10. MVP comercial

No intentar abarcar automatización empresarial completa.

La primera unidad vendible debe ofrecer una experiencia sólida de:

- presencia;
- saludo;
- conversación;
- FAQ del negocio;
- búsqueda;
- música;
- notas/recordatorios;
- configuración por web;
- actualización;
- costo de IA medible.

## 11. Estrategia de releases

- `0.1.x`: arquitectura y prototipo Banghó.
- `0.2.x`: rostro/audio/visión end-to-end.
- `0.3.x`: IA híbrida y memoria.
- `0.4.x`: Manager web y configuración comercial.
- `0.5.x`: actualización/rollback y hardening.
- `0.6.x`: SF20BA 8/4 GB y perfiles automáticos.
- `0.7.x`: Satellite/Cloud 2 GB y multi-node.
- `0.8.x`: piloto de taller/comercio.
- `0.9.x`: hardening precomercial.
- `1.0.0`: primera versión comercial estable, sólo después de piloto real exitoso.

Las versiones pueden reajustarse si la evidencia del desarrollo lo exige; `ROADMAP.md` es la fuente operativa.
