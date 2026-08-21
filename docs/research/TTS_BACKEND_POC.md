# Evaluación e Investigación de Backends TTS — AILEN R2B

**Fecha:** 2026-08-21  
**Estado:** Evaluación comparativa / POC preliminar  
**Hardware objetivo:** Banghó Zero G05 (8 GB) y SF20BA (4 GB / 8 GB, Celeron N3060 / Braswell).

---

## 1. Opciones Evaluadas para TTS Offline en Español

| Backend TTS | Motor / Runtime | Voces en Español | Tamaño Modelo | RAM Estimada | Calidad de Voz | Latencia Inicial | Estado Medición en Target |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Piper TTS** | Síntesis neural local | Varias voces/modelos | Depende de la voz | **NO MEDIDO** | Candidato principal por calidad y ejecución local | **NO MEDIDO** | **NO MEDIDO** en Banghó/SF20BA. |
| **eSpeak-NG** | Síntesis formántica | Español disponible | Pequeño | **NO MEDIDO** | Robótica pero muy simple | **NO MEDIDO** | Posible fallback de rescate; no benchmarkeado todavía. |
| **Mimic 3** | Síntesis neural | Catálogo variable | Depende del modelo | **NO MEDIDO** | No evaluado físicamente | **NO MEDIDO** | No seleccionado para el POC. |
| **Coqui TTS** | Stack Python/ML | Múltiples | Depende del modelo | **NO MEDIDO** | No evaluado físicamente | **NO MEDIDO** | No seleccionado para el POC por mayor complejidad del stack. |
| **Sherpa-ONNX TTS** | ONNX Runtime | Catálogo variable | Depende del modelo | **NO MEDIDO** | Alternativa futura | **NO MEDIDO** | Candidato futuro si Piper no satisface benchmarks físicos. |

---

## 2. Identidad y Configuración de Voces

* **Independencia de Género:** AILEN es una plataforma de asistencia agnóstica de género. La identidad del personaje (`[identity].display_name`), su apariencia visual y su voz son ortogonales e independientes.
* **Configuración:** La voz se define mediante `[speech].tts_voice` (ej. `es_ES-davefx-medium`, `es_ES-sharvard-medium`, `es_MX-ald-medium`) y la ruta a los modelos mediante `[speech].tts_model_path`.
* No se asume género a partir de `display_name` ni de `personality_seed`.

---

## 3. Decisión Técnica para el POC de AILEN

1. **Backend Principal POC:**
   - **`PiperTtsBackend`:** envoltorio sobre el CLI actual de Piper mediante `subprocess.run` seguro (`shell=False`, argv estricto y cleanup garantizado).
   - Piper genera un WAV temporal; AILEN extrae PCM 16-bit y conserva `sample_rate`/canales reales del archivo en vez de asumir una frecuencia fija.
2. **Backend Fake / Headless:**
   - **`FakeTtsBackend`:** Genera audio sintético en memoria para tests y CI sin binarios ni dependencias externas.
3. **Manejo de Errores y Degradación:**
   - Si el binario de `piper` o el modelo ONNX no están presentes, reporta `AudioBackendHealth(status=ServiceStatus.DISABLED, detail="...")` y degrada sin romper el ciclo de interacción.
   - **No se descargan modelos de voz automáticamente durante tests ni se incluyen en el repositorio.**
