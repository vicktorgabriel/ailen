# ADR-006 — Stack técnico inicial del prototipo

**Estado:** Proposed  
**Fecha:** 2026-08-21

## Contexto

El primer prototipo debe correr en Banghó Zero G05 con 8 GB y después degradarse a SF20BA. La elección del stack no debe basarse sólo en comodidad del equipo de desarrollo.

## Candidatos iniciales

### Core

Python es candidato fuerte por ecosistema de audio, visión, IA, SQLite y velocidad de prototipado, pero se debe medir memoria/base runtime.

### Web

Se busca un servidor ligero con HTML/CSS/JS responsive. Evitar SPA pesada si no aporta valor al panel local.

### Rostro

Comparar al menos:

- SDL2 sobre backend disponible;
- DRM/KMS directo si el soporte real es viable;
- X/Wayland mínimo como fallback de compatibilidad.

### STT/TTS

Seleccionar por benchmark en la Banghó, incluyendo RAM, latencia y calidad en español.

### LLM local

Mantener interfaz genérica y benchmarkear modelos pequeños cuantizados. El MVP no depende de un modelo concreto.

## Criterios para aceptar

- instalación reproducible en Debian 13 minimal;
- RAM idle razonable;
- compatibilidad con Banghó y SF20BA;
- mantenimiento activo;
- capacidad de empaquetado/release;
- ausencia de dependencia innecesaria de GPU;
- tests automatizables.

## Decisión

Pendiente de benchmark/POC. No implementar un stack como definitivo sin actualizar este ADR.

## Nota de implementación provisional (carril Web, 2026-08-21)

Para el skeleton del panel web se adoptó **stdlib pura de Python**
(`http.server.ThreadingHTTPServer` + plantillas HTML propias con sustitución
mínima + CSS/JS vanilla). Fundamento:

- cero dependencias nuevas mientras el stack no está cerrado;
- bajo consumo acorde al hardware objetivo;
- sin SPA (alineado con este ADR y ADR-005);
- tests ejecutables sin Internet.

Esta elección es **provisional y reemplazable**: la lógica vive en
`ailen.web.app.AILENWebApp` (request/response agnósticos de transporte), así
migrar a un framework ligero (Starlette/Flask/etc.) no reescribe handlers.
La decisión definitiva queda sujeta a benchmark en la Banghó y cierre de este ADR.

## Nota de implementación provisional (Face y Visión POC R2A, 2026-08-21)

1. **Rostro:**
   - Se separó la lógica de animación (`FaceAnimator`) y los modelos de pose (`FacePose`) de cualquier biblioteca gráfica.
   - Backend GUI POC: `TkinterFaceController` sin dependencia pip, pero requiere `python3-tk` y un stack gráfico del sistema. Es una elección provisional para validar contratos/render 2D; RAM/CPU y compatibilidad final de kiosk/appliance quedan pendientes de benchmark físico.
   - Backend Headless: `NullFaceController` permite operar sin renderer gráfico; su overhead exacto se medirá en hardware objetivo y no se declara como 0 MB.
   - Documentación de alternativas: `docs/research/FACE_BACKEND_POC.md`.

2. **Visión y Presencia:**
   - Detección de presencia basada en Haar cascades de OpenCV (`opencv-python-headless` como dependencia opcional `[vision]`), ejecutándose a baja resolución (320px) y 5 FPS.
   - `VisionDebouncer` desacopla la presencia instantánea de la presencia estable para evitar oscilaciones espurias.
   - Degrada a modo deshabilitado/simulado si la cámara o OpenCV no están presentes.
   - Documentación de alternativas: `docs/research/VISION_BACKEND_POC.md`.
