# Evaluación de Runtimes de Inferencia Local (2026)

**Fecha de evaluación:** 2026-08-21  
**Autor:** Antigravity / AILEN Team  
**Estado:** Evaluated / Runtime Baseline  

## 1. Runtimes Candidatos

Para ejecutar inferencia GGUF en el laboratorio (Linux Mint y Windows 11), se evaluaron dos soluciones principales:

### 1.1 `llama.cpp server` (`llama-server`)
- **Naturaleza:** Binario ligero compilado en C/C++ nativo.
- **Protocolo:** Expone endpoint HTTP compatible con OpenAI en `http://127.0.0.1:8080/v1/chat/completions`.
- **Ventajas:**
  - Consumo mínimo de memoria base (solo el peso del modelo + contexto KV cache).
  - Cero dependencias de demonios de fondo o servicios de sistema.
  - Control granular de hilos CPU (`-t`), capas GPU (`-ngl`), tamaño de contexto (`-c`) y temperatura.
  - Compatible tanto con Linux x86_64 como con Windows x64.
- **Desventajas:**
  - Requiere compilar o disponer del binario ejecutable (`llama-server` o `llama-server.exe`).

### 1.2 `Ollama`
- **Naturaleza:** Servicio de gestión y ejecución de modelos locales con API REST en `http://127.0.0.1:11434/v1`.
- **Ventajas:**
  - Muy extendido en entornos de desarrollo y workstations.
  - API OpenAI-compatible lista para usar.
- **Desventajas:**
  - Corre como servicio o demonio permanente.
  - Añade capas de abstracción para la gestión de manifests y almacenamiento.

---

## 2. Decisión Arquitectónica de Desacoplamiento

1. **Protocolo común:** AILEN interactúa con el runtime local exclusivamente a través de HTTP estándar mediante `LocalAiBackend`.
2. **`LocalRuntimeManager`:** Capa de abstracción que detecta si existe un servidor local activo en los puertos habituales (e.g. 8080, 11434), verifica su estado de salud (`/health` o `/v1/models`), y asocia los parámetros del `ModelPlan` al backend.
3. **Aislamiento en Lab Mode:** En modo laboratorio, AILEN no fuerza la instalación de paquetes ni modifica servicios del sistema operativo anfitrión. Si ningún runtime local está activo, AILEN informa el estado y degrada limpiamente a LAN Brain, Cloud o respuestas de regla.
