# Evaluación de Modelos Locales GGUF (2026)

**Fecha de evaluación:** 2026-08-21  
**Autor:** Antigravity / AILEN Team  
**Estado:** Evaluated / Catalog Baseline  

## 1. Criterios de Selección

Para que un modelo local sea considerado viable en AILEN para Lab Mode o Appliance Mode, debe cumplir con los siguientes requisitos:
1. **Formato estandarizado:** Debe estar disponible en formato **GGUF** compatible con `llama.cpp` y runtimes modernos.
2. **Capacidad en español:** Debe poseer entrenamiento multilingüe sólido con capacidad de seguir instrucciones concisas en español sin caer en degradación de sintaxis o cambio de idioma inesperado.
3. **Eficiencia en CPU:** Debe ser ejecutable en procesadores x86_64 con `AVX2` con una latencia aceptable para conversación (mínimo 5-10 tokens/segundo).
4. **Soporte de GPU Offload:** Capacidad de descargar capas (layers) a VRAM en placas NVIDIA / Vulkan / Metal para aceleración de inferencia.
5. **Licencia permisiva:** Licencias abiertas para uso de desarrollo y producción (Apache 2.0, MIT, Llama 3.2 Community License, etc.).

---

## 2. Catálogo verificado y candidatos

### 2.1 Sanity models verificados (2026-08-21)

Fuente oficial: `ggml-org/Qwen3.5-0.8B-GGUF`. Estos son los únicos artefactos habilitados para descarga automática en el baseline R3B.1:

- `qwen3.5-0.8b-q4_0` — 563,036,064 bytes, SHA-256 `57d1997790d1744fba5b40a7317df71ea5e2acee28c47e78f0cce39c0703f8cf`, Apache-2.0.
- `qwen3.5-0.8b-q8_0` — 833,592,096 bytes, SHA-256 `37ae482d336108d23516fa35e8e0c4126688d81018b87178a18d752a1357814f`, Apache-2.0.

Su objetivo inicial es validar de extremo a extremo descarga, integridad, runtime, routing y latencia. **No se consideran automáticamente el modelo definitivo ni el modelo de mayor calidad para hardware potente.**

### 2.2 Candidatos históricos / no verificados

Qwen 2.5, SmolLM2 y Llama 3.2 permanecen como metadata comparativa con `downloadable=False`. No deben ser recomendados como plan accionable ni descargados automáticamente hasta volver a verificar release, URL, tamaño, hash y licencia.

### 2.3 Catálogo de capacidad media/alta pendiente

Antes de medir la RTX 3060 o futuros equipos con 8–24 GB de VRAM se ampliará el catálogo con modelos actuales de clases small/medium. La selección se hará con fuentes y hashes verificados en la fecha de incorporación; no se conservará un modelo antiguo sólo porque encaje en memoria.

---

## 3. Catálogo Declarativo vs Invocación Dinámica

> [!IMPORTANT]
> AILEN prohíbe terminantemente que un modelo o LLM elija dinámicamente URLs de descarga o rutas de artefactos. Todas las fuentes de descarga, hashes SHA-256 y parámetros de memoria deben estar definidos de forma declarativa e inmutable en el `ModelCatalog`.
