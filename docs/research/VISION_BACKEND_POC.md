# Investigación y Evaluación de Backends de Visión y Presencia (Vision Backend POC)

**Fecha:** 2026-08-21  
**Contexto:** Detección de presencia física para Banghó Zero G05 (8 GB) y SF20BA (8 GB / 4 GB) bajo Debian 13 minimal con CPU modesta y sin GPU dedicada.

---

## 1. Requisitos del Backend de Visión

1. **Detección simple de presencia/rostro**:
   - Detectar si hay al menos una persona presente (`present: bool`).
   - Estimar coordenadas normalizadas aproximadas (`primary_x`, `primary_y` de -1.0 a 1.0) para que el rostro oriente la mirada hacia la persona.
   - Conteo estimado de caras detectadas (`faces_count: int`).
2. **Prohibiciones estrictas**:
   - **NO** reconocimiento facial (no identificar quién es).
   - **NO** almacenamiento de grabaciones continuas ni fotos de usuarios.
   - **NO** embeddings biométricos.
   - **NO** análisis emocional.
3. **Bajo consumo en CPU**:
   - Muestreo a baja tasa de cuadros (ej. 3 a 5 FPS configurables).
   - El porcentaje real de CPU debe medirse en Banghó/SF20BA; no se asume rendimiento de Celeron antes de la prueba física.
4. **Debounce temporal robusto**:
   - Filtrar parpadeos de detección (falsos positivos de 1 frame o micro-ausencias) usando `presence_debounce_seconds` configurable.
5. **Degradación limpia**:
   - Si la cámara `/dev/video0` no existe, está ocupada o el backend opcional no está instalado, AILEN no debe colapsar.

---

## 2. Comparativa de Opciones Evaluadas

| Opción | Consumo CPU (a 5 FPS) | Dependencias / Peso | Precisión Presencia / Mirada | Privacidad / Complejidad | Veredicto POC |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **OpenCV (Haar Cascades clásico)** | No medido aún en objetivo | Opcional (`opencv-python-headless`) | Suficiente como POC de presencia/coordenadas | Sin embeddings ni reconocimiento | **SELECCIONADO PARA POC REAL** |
| **MediaPipe (Face Detection)** | No medido en este proyecto | Dependencias mayores | Mejor tracking facial potencial | Más complejo que lo necesario para este POC | No elegido para MVP |
| **Diferencia de cuadros V4L2** | No medido | Implementación potencialmente pequeña | Detecta movimiento, no necesariamente rostro | No resuelve por sí sola la mirada al rostro | Insuficiente como único backend |
| **TFLite UltraFace / MobileNet** | No medido | Requiere runtime/modelo adicional | Potencialmente mejor detección | Candidato de optimización futura | Candidato post-POC |
| **FakeVisionBackend (Simulado)** | No aplica a hardware | Sin backend real | Control total en tests | Ideal para CI/headless determinista | **CANÓNICO PARA TESTS** |

---

## 3. Decisión para el POC R2A

1. **Clasificador clásico Haar Cascade de OpenCV**:
   - Empaquetado como dependencia opcional `[project.optional-dependencies] vision = ["opencv-python-headless>=4.8.0"]`.
   - Se ejecuta a baja frecuencia (default 5 FPS) sobre cuadros reducidos (320x240) en escala de grises, minimizando drásticamente el consumo de CPU.
2. **Debounce Temporal (`VisionDebouncer`)**:
   - Separación estricta entre la observación instantánea de cada frame y el estado de presencia estable.
   - Aplica `vision.presence_debounce_seconds` (default: 2.0s) tanto para confirmar presencia como para confirmar ausencia.
3. **Degradación**:
   - Si `/dev/video0` no está disponible o falla `cv2`, el backend usa estados existentes (`DISABLED`, `DEGRADED` o `UNHEALTHY`, según el caso) sin interrumpir el funcionamiento del Core ni del Face.
4. **Confidence**:
   - Haar Cascade no entrega una confianza calibrada equivalente a un detector moderno. `PresenceObservation.confidence` queda en `None` en este POC en vez de inventar un porcentaje.
