# Planificador Adaptativo de Modelos (`ModelPlanner`)

**Fecha de evaluación:** 2026-08-21  
**Autor:** Antigravity / AILEN Team  
**Estado:** Design & Heuristics Baseline  

## 1. Principios del Planificador

El `ModelPlanner` es el componente responsable de transformar un `HardwareCapabilityReport` y un `DeviceProfile` en una recomendación ejecutable de modelo y runtime (`ModelPlan`), o determinar que la inferencia local no es viable (`NO_MODEL_PLAN`).

### Heurísticas Fundamentales:
1. **Márgenes de seguridad inviolables:** Un modelo nunca debe consumir el 100% de la RAM o VRAM disponible.
   - **Límite de RAM:** Por defecto $\le 60\%$ de la RAM libre (`max_ram_fraction = 0.60`), garantizando memoria suficiente para el sistema operativo, renderizado del rostro (Face), captura de cámara (Vision), síntesis/reconocimiento de audio (STT/TTS) y el Core.
   - **Límite de VRAM:** Por defecto $\le 80\%$ de la VRAM libre (`max_vram_fraction = 0.80`), previniendo desbordes en el compositor gráfico.
2. **Priorización de GPU:** Si existe una GPU compatible con VRAM suficiente para albergar el modelo y su contexto, se selecciona aceleración por hardware (`device="cuda"`, `gpu_layers="all"`).
3. **Inferencia en CPU:** Si no hay GPU o la VRAM es insuficiente, pero la CPU soporta `AVX2` y hay suficiente RAM libre dentro del margen seguro, se selecciona ejecución en CPU.
4. **Degradación Segura (`NO_MODEL_PLAN`):** Si ningún modelo del catálogo cumple con los requisitos de memoria o arquitectura, el planificador no fuerza una selección errónea. Emite un plan no viable con códigos de razón explícitos (`INSUFFICIENT_MEMORY_MARGIN`, `CPU_INSTRUCTION_SET_UNSUPPORTED`, `NO_VIABLE_LOCAL_MODEL`). En tal situación, AILEN opera mediante LAN Brain, Cloud o reglas locales.

---

## 2. Contrato de Entrada y Salida

### Entrada:
- `hardware_report: HardwareCapabilityReport`
- `device_profile: DeviceProfile`
- `catalog: ModelCatalog`
- `prefer_gpu: bool = True`
- `max_ram_fraction: float = 0.60`
- `max_vram_fraction: float = 0.80`
- `desired_context: int = 2048`

### Salida (`ModelPlan`):
- `selected_model_id: str | None`
- `runtime: str` (e.g. `"llama.cpp"`, `"ollama"`, `"none"`)
- `device: str` (`"cuda"`, `"cpu"`, `"none"`)
- `gpu_layers: int | str` (`"all"`, `0`, etc.)
- `estimated_ram_mb: int`
- `estimated_vram_mb: int`
- `context_size: int`
- `reason_codes: list[str]`
- `is_viable: bool`
