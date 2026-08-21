# Investigación y Evaluación de Backends Gráficos para el Rostro (Face Backend POC)

**Fecha:** 2026-08-21  
**Contexto:** Hardware objetivo final: Banghó Zero G05 (8 GB) y SF20BA (8 GB / 4 GB) bajo Debian 13 minimal sin GPU dedicada.

---

## 1. Requisitos del Backend Gráfico

1. **Bajo consumo de memoria y CPU**:
   - Renderizado 2D simple de formas geométricas (ojos, pupilas, párpados, boca).
   - Objetivo: overhead pequeño frente al resto del sistema.
   - Los límites reales de RAM/CPU se medirán en Banghó/SF20BA; no se fijan porcentajes antes del benchmark físico.
2. **Independencia de dependencias pesadas**:
   - No requerir Qt/PySide (que ocupan cientos de MB de disco y sobrecarga de memoria).
   - Cero dependencias obligatorias en el Core (`dependencies = []`).
3. **Compatibilidad de despliegue**:
   - Compatible con servidores X11 minimalistas (ej. Openbox/Xorg) y Wayland (cage/labwc/sway) en modo Kiosk fullscreen.
   - Posibilidad de ejecución headless total (servidores o terminales sin monitor).

---

## 2. Comparativa de Candidatos Evaluados

| Candidato | Consumo RAM | Consumo CPU (2D) | Dependencias / Empaquetado | Soporte Kiosk / Fullscreen | Veredicto POC |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Tkinter Canvas** | No medido aún | No medido aún | Sin dependencia pip; requiere `python3-tk` del sistema | Funciona sobre el stack gráfico que provea Tk; validar X11/Wayland real | **SELECCIONADO PARA POC** |
| **Pygame (SDL2)** | No medido aún | No medido aún | Requiere `pygame`/SDL2 | Buen candidato para kiosk y posible KMS/DRM según build | **Candidato Alternativo** |
| **Raylib / Pyray** | No medido aún | No medido aún | Requiere bindings/binarios | Potencial para salida más directa | Candidato futuro |
| **PySide6 / PyQt6** | No medido en este proyecto | No medido en este proyecto | Dependencias significativamente mayores | Compatible con escritorio/kiosk, pero sobredimensionado para el POC | **No elegido para MVP** |
| **DRM/KMS directo** | No medido aún | No medido aún | Mayor complejidad de implementación | Ideal conceptual para appliance sin compositor | Candidato de optimización |
| **Null (Headless)** | Overhead no aislado aún | Overhead no aislado aún | Sin renderer gráfico | N/A | **SELECCIONADO PARA HEADLESS** |

---

## 3. Decisión para el POC R2A

1. **Separación lógica total**: `FaceAnimator` y `FacePose` viven en Python puro, calculando geometrías normalizadas (-1.0 a 1.0) sin acoplarse a ninguna librería gráfica.
2. **Backend GUI POC**: Se implementa `TkinterFaceController`. No agrega paquetes pip, pero Debian minimal puede requerir instalar `python3-tk` y un servidor/compositor gráfico. Su objetivo es validar rápidamente el contrato y el render 2D, no fijar todavía el backend definitivo del appliance.
3. **Backend Headless**: `NullFaceController` procesa y expone las poses sin abrir ventanas, permitiendo que nodos de 2 GB o unidades sin pantalla operen al 100% de sus capacidades sociales.
4. **Futuro (fase de optimización C/appliance)**: Si el prototipo en Banghó/SF20BA requiere prescindir por completo de Xorg/Wayland, se evaluará un ejecutable nativo en C/Rust con DRM/KMS o SDL2 directo que consuma el stream de poses de AILEN.
