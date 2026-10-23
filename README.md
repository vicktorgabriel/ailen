# AILEN

> **AILEN — Asistente Inteligente Local, Evolutivo y Natural.** Nombre oficial del proyecto/plataforma. El nombre, voz y apariencia de cada personaje/asistente son configurables por instalación.

AILEN es una plataforma de asistente físico y conversacional diseñada para reutilizar notebooks y PCs antiguas como compañeros de hogar, taller y comercio.

La idea central no es crear un chatbot dentro de una computadora, sino un **dispositivo dedicado**: rostro animado, cámara como ojos, micrófono como oído, parlantes como voz, memoria persistente y acceso limitado a herramientas útiles.

## Estado

- Versión de trabajo: `0.4.0-dev.0`
- Fase: consolidación R4/R5 sobre runtime físico de laboratorio ya funcional; FacePack nativo es el renderer lógico por defecto (fallo => headless, nunca portrait automático) y el siguiente hito es Appliance Debian.
- R5: memoria explícita y diagnóstico ya usan servicios reales; [alcance y validación](docs/testing/R5_ADMIN_REAL_DATA.md). Las demás vistas pendientes figuran en `TASKS.md`.
- Hardware objetivo del primer prototipo: Banghó Zero G05, 8 GB RAM, M.2 500 GB.
- Sistema base previsto: Debian 13 minimal.
- Primer objetivo de optimización posterior: SF20BA de 8 GB y 4 GB.
- Hardware de 2 GB: previsto como nodo `Satellite/Cloud`, sin obligación de LLM local.

## Principios del producto

1. **La identidad no vive dentro del LLM.** Personalidad, memoria, preferencias, configuración y estado pertenecen a AILEN Core.
2. **IA híbrida.** El mismo asistente puede usar LLM local, un cerebro LAN y/o APIs externas rápidas y económicas.
3. **Degradación progresiva.** Si falla Internet, el nodo conserva las capacidades locales que pueda ejecutar. Si el cerebro LAN está apagado, puede usar local o nube.
4. **Hardware reciclado primero.** El software debe ser medible y adaptable a 2, 4, 8 GB y equipos modernos. En los equipos reciclados se prioriza el micrófono integrado/nativo de la placa, pero cada endpoint se califica físicamente antes de persistirlo; un USB o Easy Effects no es requisito del producto.
5. **Sin escritorio pesado.** El producto final debe arrancar directamente como appliance dedicado.
6. **Administración web responsive.** Configuración y mantenimiento desde celular/PC por LAN, sin app móvil obligatoria.
7. **Funciones limitadas y controladas.** Música, búsquedas, información del comercio, notas, recordatorios, presencia y conversación; el LLM no obtiene shell libre.
8. **Privacidad por diseño.** Historial, personalidad y memoria permanecen locales salvo el contexto mínimo necesario enviado a un proveedor externo.
9. **Actualización segura.** Releases versionadas, canales de actualización, verificación, health check y rollback.
10. **Documentación como fuente de verdad.** Arquitectura, decisiones, roadmap y estado deben acompañar al código.

## Modos previstos

| Perfil | Hardware orientativo | IA principal | Uso |
|---|---:|---|---|
| `Satellite/Cloud` | 2 GB | API / LAN | Terminal de rostro/voz muy liviana |
| `Cloud` | 2–4 GB | API rápida | Comercio y consultas rápidas |
| `Hybrid` | 4–8 GB | local pequeño + API | Perfil general recomendado |
| `Local` | 8 GB+ / hardware moderno | local + API opcional | Mayor autonomía |
| `LAN Brain` | PC potente | modelo mayor | Cerebro compartido opcional |

## Primer MVP

El primer prototipo útil debe poder:

- arrancar automáticamente en Debian 13;
- mostrar un rostro 2D liviano;
- parpadear, mirar y reaccionar por estados;
- detectar presencia/rostro sin identificación obligatoria;
- escuchar y transcribir voz;
- hablar mediante TTS;
- conversar usando un router local/LAN/remotos nombrados;
- recordar conversaciones y datos explícitamente guardados;
- saludar en modo comercio sin resultar invasivo;
- responder información configurada del negocio;
- realizar búsquedas web controladas;
- reproducir música;
- administrarse desde una UI web responsive protegida;
- actualizarse con rollback.

## Documentación principal

- `docs/context/PRODUCT.md`: definición del producto.
- `docs/context/PLAN_MAESTRO.md`: alcance y estrategia global.
- `docs/context/PRODUCT_BEHAVIOR.md`: comportamiento, personalidad, presencia y modos sociales.
- `docs/context/IMPLEMENTATION_PLAN.md`: orden concreto de implementación.
- `ARCHITECTURE.md`: arquitectura técnica canónica.
- `docs/architecture/MODULE_CONTRACTS.md`: contratos entre módulos.
- `ROADMAP.md`: etapas y entregables.
- `TASKS.md`: trabajo inmediato y primer slice integrable.
- `docs/operations/AGENT_HANDOFF.md`: continuidad y roles para Codex Sol Max, Codex Luna y otros agentes de desarrollo.
- `docs/operations/R1_PARALLEL_WORK.md`: división concreta del primer trabajo paralelo.
- `docs/context/COMMERCIAL_MVP.md`: alcance del primer piloto vendible.
- `docs/testing/ACCEPTANCE_MATRIX.md`: criterios verificables por subsistema.
- `CHANGELOG.md`: cambios por versión.
- `docs/memory/CURRENT_STATE.md`: estado actual.
- `docs/memory/RECENT_DECISIONS.md`: decisiones recientes.
- `docs/architecture/adr/`: decisiones arquitectónicas.
- `AGENTS.md`: reglas para agentes de código/IA.
- `REGLAMENTO.md`: reglas de proyecto, versionado y releases.

## Estructura inicial

```text
ailen/
├── README.md
├── ARCHITECTURE.md
├── ROADMAP.md
├── CHANGELOG.md
├── VERSION
├── AGENTS.md
├── REGLAMENTO.md
├── CONTRIBUTING.md
├── config/
├── docs/
│   ├── architecture/adr/
│   ├── context/
│   ├── deployment/
│   ├── hardware/
│   ├── memory/
│   ├── operations/
│   ├── security/
│   ├── testing/
│   └── ui/
├── packaging/
├── release/
├── scripts/
├── src/ailen/
└── tests/
```

## Alcance comercial inicial

El objetivo de campo es validar una unidad en taller/local y luego un pequeño piloto con comerciantes locales. El producto no intentará competir inicialmente como plataforma empresarial general ni como robot autónomo.

## Identidad del producto y del personaje

`AILEN` es el nombre oficial del proyecto y de la plataforma: **Asistente Inteligente Local, Evolutivo y Natural**. La marca comercial deberá verificarse legalmente antes de una venta formal, pero el código y el repositorio usan AILEN como identidad estable.

El personaje que habla no queda acoplado a la marca. Cada instalación podrá configurar `display_name`, voz, apariencia y personalidad; AILEN es la plataforma que sostiene esa identidad.
