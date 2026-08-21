# Arquitectura de Detección de Hardware Multiplataforma (V2)

**Fecha de evaluación:** 2026-08-21  
**Autor:** Antigravity / AILEN Team  
**Estado:** Proposed / R3B  

## 1. Contexto y Objetivos

La versión inicial de `HardwareDiagnostics` en AILEN fue diseñada como un baseline centrado en Linux. En escenarios donde no se encontraban periféricos o no se podía consultar el sistema, existían mecanismos de fallback que asignaban valores sintéticos (e.g. `display: default`, `audio: default`).

Para el **Lab Mode** (Linux Mint y Windows 11) y el posterior **Appliance Mode** (Debian 13 minimal), AILEN requiere:
1. **Verdad de hardware:** Si un periférico o métrica no puede detectarse, se declara explícitamente como `UNKNOWN` o `UNAVAILABLE`. Nunca se inventan dispositivos ficticios.
2. **Capacidades avanzadas de inferencia:** Para planificar la ejecución de modelos de lenguaje locales (LLM), es imperativo conocer:
   - Conjunto de instrucciones de la CPU (`AVX`, `AVX2`, `FMA`, `SSE4.1`, `SSE4.2`, `NEON`, etc.).
   - Memoria RAM total y disponible en tiempo real.
   - Presencia de GPU dedicada o integrada, memoria de video (VRAM) total y disponible, y vendedor (NVIDIA, AMD, Intel, Apple Silicon).
   - Espacio disponible en disco en la partición donde se ubica el almacén de modelos (`ModelStore`).
   - Dispositivos de audio reales (micrófonos y salidas) y cámaras de video reales.
3. **Aislamiento por adaptador de sistema operativo:** Desacoplar la lógica central de AILEN de los comandos o archivos específicos de Linux o Windows.

---

## 2. Modelo de Dominio: `HardwareCapabilityReport`

El reporte de hardware estructurado se compone de las siguientes entidades tipadas:

```
HardwareCapabilityReport
├── OS: system, version, distribution, architecture, is_wsl, is_container
├── CPU: model, architecture, physical_cores, logical_cores, flags, has_avx2, has_fma
├── RAM: total_bytes, available_bytes, total_mb, available_mb
├── GPU: list[GpuInfo] (vendor, model, vram_total_mb, vram_available_mb, driver_version, backend)
├── Disk: path, total_bytes, free_bytes, free_mb
├── Audio: input_devices: list[AudioDeviceReport], output_devices: list[AudioDeviceReport]
├── Cameras: list[CameraDeviceReport] (device_path, index, name, is_available)
├── Displays: list[DisplayDeviceReport] (name, width, height, is_primary)
└── Runtime: python_version, executable, os_family
```

---

## 3. Adaptadores de Sistema Operativo

### 3.1 Linux Hardware Adapter (`LinuxHardwareAdapter`)
- **CPU & RAM:** Inspección directa de los pseudo-sistemas de archivos `/proc/cpuinfo` y `/proc/meminfo`.
- **GPU:**
  - NVIDIA: Consulta a `nvidia-smi` mediante `subprocess.run` con lista fija de argumentos (`--query-gpu=name,memory.total,memory.free,driver_version --format=csv,noheader,nounits`), timeout estricto (2.0s) y captura segura de excepciones.
  - DRM/PCI: Inspección de `/sys/class/drm/` y `lspci` allowlisted.
- **Audio & Cámaras:**
  - ALSA via `arecord -l` y `aplay -l` parseados defensivamente.
  - V4L2 via enumeración de `/sys/class/video4linux/` o `/dev/video*`.
- **Disco:** `shutil.disk_usage` sobre el directorio configurado de datos o modelos.

### 3.2 Windows Hardware Adapter (`WindowsHardwareAdapter`)
- **CPU & RAM:** Consulta a APIs de stdlib (`platform`, `ctypes.windll.kernel32.GlobalMemoryStatusEx`) y consultas CIM fijas mediante PowerShell invocadas como subproceso con `argv` estrictamente controlado (sin `shell=True`, sin concatenación de strings de usuario).
- **GPU:** Detección de `nvidia-smi` en `C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe` o PATH, más Win32_VideoController via CIM.
- **Audio & Cámaras:** Declarados defensivamente como `UNKNOWN` o enumerados via Win32 PnP entities con comandos allowlisted.

### 3.3 Fake Hardware Adapter (`FakeHardwareAdapter`)
- Permite inyectar cualquier topología de hardware en tests unitarios offline (e.g. PC Laboratorio RTX 3060 12GB / 48GB RAM, Netbook SF20BA 4GB Celeron sin AVX2, Nodo Satellite 2GB), garantizando cobertura 100% determinista sin dependencias de hardware real.
