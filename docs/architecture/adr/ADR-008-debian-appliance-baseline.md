# ADR-008 — Debian appliance baseline

**Estado:** Accepted
**Fecha:** 2026-08-21

## Contexto

AILEN debe ejecutarse desde notebooks recicladas de 2–8 GB de RAM y, a futuro, hardware más moderno. El objetivo no es ofrecer un escritorio Linux sino un appliance dedicado con audio, cámara, rostro, panel LAN y backends de IA intercambiables.

Se consideraron Debian minimal, Alpine y distribuciones desktop ligeras. Reducir algunos MB de userland no debe aumentar de forma significativa la complejidad de drivers, paquetes, wheels Python, binarios externos, actualizaciones y soporte de campo.

## Decisión

El baseline soportado de AILEN será **Debian 13 stable amd64 instalado mediante netinst/minimal**, sin entorno de escritorio.

### Nodo con pantalla usando el POC Tkinter

Mientras el renderer POC sea Tkinter, la imagen necesita únicamente un stack gráfico mínimo, no un desktop completo:

- Xorg mínimo / servidor X;
- `xinit` o arranque equivalente;
- `python3-tk`;
- AILEN como única aplicación visible, iniciada automáticamente.

No se requiere GNOME, KDE, XFCE ni un navegador kiosk para el rostro. Tampoco es obligatorio un window manager si el renderer puede ocupar directamente la sesión X.

### Nodo headless / Satellite sin pantalla

No instala servidor gráfico. Core, Web, audio, visión y backends remotos pueden funcionar sin X mediante `NullFaceController`.

### Futuro renderer DRM/KMS/SDL2

Si el benchmark físico demuestra beneficio suficiente, se podrá reemplazar el POC Tkinter por SDL2/DRM-KMS y eliminar Xorg de los nodos con pantalla. Esto no cambia el sistema base Debian.

## Por qué no Alpine como baseline

Alpine es más pequeño y válido técnicamente, pero usa musl, BusyBox, `apk` y OpenRC. Mantenerlo como plataforma principal duplicaría trabajo de empaquetado/despliegue y puede complicar software precompilado pensado para glibc. La reducción de footprint del sistema base no es actualmente el cuello de botella principal frente a STT/TTS/OpenCV/LLM.

Alpine queda como **experimento futuro**, únicamente si un perfil Satellite extremadamente limitado demuestra mediante benchmark una ventaja material que compense una segunda plataforma soportada.

## Compatibilidad 32-bit

Debian 13 ya no ofrece i386 como arquitectura de instalación regular. Hardware verdaderamente 32-bit queda fuera del baseline Debian 13 y deberá evaluarse por separado (por ejemplo Debian 12 u otra plataforma) sin condicionar el producto amd64.

## Consecuencias

- una sola base de despliegue para Cloud/Hybrid/Local y la mayoría de Satellites;
- systemd como supervisor canónico;
- apt/dpkg como mecanismo de dependencias del sistema;
- mejor reproducibilidad para soporte comercial;
- renderer gráfico desacoplado del OS base;
- ninguna afirmación de consumo final hasta benchmarkear la imagen real en Banghó/SF20BA.
