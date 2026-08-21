# Plan de benchmarks — AILEN

## Objetivo

Tomar decisiones de soporte y routing basadas en mediciones reales por equipo.

## Métricas mínimas

### Sistema

- RAM idle del sistema;
- RAM idle de AILEN;
- RAM pico;
- CPU idle/promedio/pico;
- temperatura idle/carga;
- almacenamiento ocupado por runtime/modelos;
- tiempo de arranque hasta estado usable.

### Audio

- latencia desde fin de voz a texto;
- uso RAM/CPU de STT;
- latencia desde texto hasta primer audio de TTS;
- estabilidad de dispositivos ALSA/PipeWire según stack final.

### Visión/rostro

- FPS del rostro;
- CPU idle del render;
- frecuencia de detección;
- impacto combinado cámara + render.

### IA

Por backend:

- tiempo al primer token;
- tokens/segundo cuando aplique;
- tiempo total;
- RAM/VRAM;
- porcentaje de fallos;
- costo estimado/real para cloud.

### End-to-end

Medir desde el final de una frase del usuario hasta el inicio del audio de respuesta.

## Escenarios

1. idle sin persona;
2. persona detectada sin conversación;
3. conversación local;
4. conversación cloud;
5. LAN Brain;
6. música + rostro;
7. música + conversación;
8. Internet caído;
9. LAN Brain caído;
10. jornada prolongada.

## Equipos iniciales

- Banghó Zero G05 8 GB;
- SF20BA 8 GB;
- SF20BA 4 GB;
- hardware 2 GB candidato;
- Ryzen/RTX sólo como referencia de laboratorio.

## Regla

No optimizar contra un benchmark sintético aislado si perjudica la experiencia end-to-end. La métrica principal del usuario es la latencia percibida y la estabilidad.
