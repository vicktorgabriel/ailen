# Hardware de prototipo

## Banco de desarrollo

### LAB-01

- CPU: AMD Ryzen 5 5500
- RAM: 48 GB DDR4
- GPU: NVIDIA RTX 3060 12 GB VRAM
- Almacenamiento: NVMe ~400 GB + 4 TB HDD
- Uso: desarrollo, pruebas de modelos, cuantizaciones y benchmarks rápidos.

Regla: ninguna capacidad básica del producto puede declararse dependiente de este hardware.

### LAB-02

- CPU: AMD FX-8350
- RAM: 20 GB
- GPU: 8 GB VRAM
- Almacenamiento: SSD 250 GB + 4 TB HDD
- Uso: segundo entorno de pruebas, posible Hub/LAN Brain experimental.

### NODE-OPTIONAL-01

- Dell Optiplex 3050
- Intel Core i7
- 12 GB DDR4
- Uso actual: otras actividades
- Uso futuro posible: Hub/LAN Brain o nodo moderno.

## Primer prototipo físico

### PROTO-01 — Banghó Zero G05

- RAM instalada: 8 GB
- Almacenamiento: M.2 500 GB
- Periféricos de interés: pantalla, cámara, micrófono y parlantes integrados
- Objetivo: validar el ciclo end-to-end antes de desarmar o fabricar carcasa.

## Hardware objetivo posterior

### SF20BA

Probar por separado:

1. 8 GB;
2. 4 GB;
3. 2 GB si la unidad lo permite y el perfil Satellite/Cloud resulta viable.

No asumir rendimiento por compartir modelo de placa: registrar CPU, memoria, almacenamiento y periféricos de cada unidad.

## Equipos con pantalla rota

Se consideran válidos para:

- monitor HDMI/VGA externo según placa;
- integración detrás de monitor;
- modo voz/headless;
- nodo Satellite/LAN.

## Checklist por unidad

Antes de incorporar un equipo al soporte:

- [ ] arquitectura CPU compatible;
- [ ] RAM detectada;
- [ ] almacenamiento y salud básica;
- [ ] cámara;
- [ ] micrófono;
- [ ] salida de audio;
- [ ] Wi-Fi/Ethernet;
- [ ] display interno/externo;
- [ ] temperatura idle/carga;
- [ ] consumo RAM idle;
- [ ] latencia STT;
- [ ] latencia TTS;
- [ ] latencia IA;
- [ ] prueba prolongada.
