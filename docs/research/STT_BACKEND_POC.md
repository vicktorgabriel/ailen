# Evaluación e Investigación de Backends STT — AILEN R2B

**Fecha:** 2026-08-21  
**Estado:** Evaluación comparativa / POC preliminar  
**Hardware objetivo:** Banghó Zero G05 (8 GB) y SF20BA (4 GB / 8 GB, Celeron N3060 / Braswell).

---

## 1. Opciones Evaluadas para STT Offline en Español

| Backend STT | Arquitectura / Motor | Tamaño de Modelo (Español) | Memoria RAM Estimada | Streaming Nativo | Compatibilidad CPU Antigua | Estado Medición en Target |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Vosk (Kaldi)** | Reconocimiento offline clásico | `vosk-model-small-es-0.42`: 39 MB según catálogo oficial | **NO MEDIDO** | Sí | Candidato principal para hardware limitado por su modelo español pequeño y soporte offline. | **NO MEDIDO** en Banghó/SF20BA. |
| **whisper.cpp** | Whisper en C/C++ (`ggml`) | Depende del modelo/cuantiación | **NO MEDIDO** | CLI batch; el proyecto también ofrece ejemplos de streaming | Candidato para hardware más capaz; rendimiento real dependerá de CPU/modelo. | **NO MEDIDO** en Banghó/SF20BA. |
| **Faster-Whisper (CTranslate2)** | Transformer vía CTranslate2 | Depende del modelo | **NO MEDIDO** | Parcial | No elegido para el POC por stack Python/runtime más pesado que Vosk/whisper.cpp. | **NO MEDIDO**. |
| **Sherpa-ONNX** | ONNX Runtime | Depende del modelo | **NO MEDIDO** | Sí | Alternativa futura a benchmarkear si Vosk/whisper.cpp no alcanzan. | **NO MEDIDO**. |
| **PocketSphinx** | Reconocimiento clásico | Depende del modelo | **NO MEDIDO** | Sí | No seleccionado para el POC; la calidad en nuestro dominio español no fue medida. | **NO MEDIDO**. |

---

## 2. Análisis para Perfiles de Hardware

1. **Perfil 4 GB / CPU Modesta (SF20BA Celeron N3060):**
   - **Vosk** es el candidato preferente inicial porque el catálogo oficial ofrece `vosk-model-small-es-0.42` de 39 MB y está diseñado como modelo ligero; RAM y latencia quedan pendientes de medición física.
2. **Perfil 8 GB / CPU Media (Banghó Zero G05):**
   - **whisper.cpp** (modelo `tiny` o `base` cuantizado) ofrece mayor riqueza sintáctica y robustez ante ruido ambiente.

---

## 3. Decisión Técnica para el POC de AILEN

1. **Contrato Agnóstico `SttBackend`:**
   - La interfaz `transcribe(segment: AudioSegment) -> Transcript` no ata la arquitectura a ningún motor.
2. **Implementaciones POC:**
   - `VoskSttBackend`: Envoltorio de `vosk` (`pip install vosk` opcional).
   - `WhisperCppSttBackend`: envoltorio para el binario actual `whisper-cli`, con compatibilidad best-effort para nombres legacy si están presentes.
   - `FakeSttBackend`: Modo determinista sin dependencias para testing y desarrollo.
3. **Manejo de Faltantes y Degradación:**
   - Si la librería o el modelo en disco no existen, el backend reporta `AudioBackendHealth(status=ServiceStatus.DISABLED, detail="...")` y retorna un `Transcript(text="", confidence=0.0)` sin lanzar excepciones fatales ni inventar textos.
   - **Los modelos no se descargan automáticamente en tests ni se incluyen en el repositorio Git.**
