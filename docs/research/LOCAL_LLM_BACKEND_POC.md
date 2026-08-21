# Investigación y Arquitectura POC — Local LLM Backend (R3A)

## 1. Desacoplamiento de Proceso vs In-Process C++ Bindings

Para mantener el proceso Core de AILEN ligero (< 30-50 MB RAM baseline) y evitar fallos por corrupción de memoria C/CUDA o bloqueos de GIL, se adopta el patrón de **servidor desacoplado por HTTP**.

### Comparativa de Enfoques:

| Característica | Enfoque A: `llama-cpp-python` in-process | Enfoque B: Servidor HTTP desacoplado (`llama-server` / `Ollama`) |
| :--- | :--- | :--- |
| **Aislamiento de fallos** | Crash de C++ mata todo el proceso AILEN Core. | Crash del servidor LLM no afecta al Core; el Router conmuta a fallback. |
| **Consumo de RAM Core** | Core inflado con runtime de inferencia y pesos. | Core permanece ligero; el servidor LLM se levanta o suspende independientemente. |
| **Reutilización de API** | Código específico dependiente del binding. | **Protocolo estándar HTTP OpenAI-compatible** común para Local, LAN y Cloud. |
| **Empaquetado / Releases** | Compleja compilación de ruedas binarias C++ por plataforma. | Paquete Python puro estándar; servidor instalado como binario del sistema o appliance. |

**Decisión:** Se utiliza un backend cliente HTTP OpenAI-compatible (`LocalAiBackend`) que se comunica con un endpoint local (`http://127.0.0.1:8080/v1` o similar) vía `urllib.request` de Python stdlib (cero dependencias pesadas).

---

## 2. Modelos Cuantizados Recomendados para Hardware Objetivo

> **NOTA:** Ningún modelo se descarga automáticamente en los tests ni en la inicialización del Core. La descarga y aprovisionamiento de pesos GGUF es responsabilidad del setup del nodo/appliance.

* **Banghó Zero G05 (8 GB RAM / CPU Intel N-series o Celeron/Pentium):**
  * Modelos de 1B a 3B parámetros cuantizados a Q4_K_M (e.g. `Qwen2.5-1.5B-Instruct-GGUF`, `Llama-3.2-1B-Instruct-GGUF`, `SmolLM2-1.7B-Instruct-GGUF`).
  * Huella de memoria RAM esperada: ~1.2 GB a 2.5 GB.
* **SF20BA (4 GB RAM / CPU modesta):**
  * Modelos ultra-compactos de 0.5B a 1B (e.g. `Qwen2.5-0.5B-Instruct-GGUF`, `SmolLM2-360M-Instruct-GGUF`).
  * Huella de memoria RAM esperada: ~400 MB a 900 MB.
