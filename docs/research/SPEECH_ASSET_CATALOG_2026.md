# SPEECH_ASSET_CATALOG_2026.md — Catálogo Canónico de Modelos de Voz y Habla

> **Fecha de verificación:** Agosto 2026  
> **Alcance:** Modelos locales y offline para STT (Vosk, Whisper.cpp) y TTS (Piper ONNX)  
> **Ubicación de almacenamiento local:** `~/.local/share/ailen/speech/{stt,tts}/` (Linux/POSIX) o `%LOCALAPPDATA%/AILEN/speech` (Windows)

---

## 1. Principios de Seguridad e Integridad

1. **Protocolo Criptográfico Estricto:** Todo asset debe descargarse exclusivamente por **HTTPS**, con tamaño exacto en bytes y **SHA-256 verificado** antes de su integración al runtime.
2. **Fail-Closed:** Si un checksum falla o la descarga se interrumpe, el archivo temporal se destruye inmediatamente.
3. **Protección Path Traversal:** Toda resolución de rutas valida que el destino esté estrictamente dentro del subdirectorio correspondiente (`stt/` o `tts/`), sanitizando `asset_id` contra secuencias como `..` o separadores de directorio.
4. **Protección Zip-Slip:** Las extracciones de archivos comprimidos (`.zip` de Vosk) rechazan cualquier entrada con rutas relativas que intenten escapar del directorio objetivo.
5. **No Inferencia de Género por Nombre:** El género o tipo de voz nunca se deduce de nombres humanos; se extrae únicamente de la metadata oficial del dataset.

---

## 2. Modelos STT (Speech-to-Text) Verificados

### 2.1 Vosk Spanish Small (`vosk-model-small-es-0.42`)
- **ID:** `vosk-model-small-es-0.42`
- **Motor:** Vosk (Kaldi-based)
- **Idioma / Región:** Español (`es` / `es_ES`)
- **URL:** `https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip`
- **Tamaño:** `39,817,833` bytes (~38.0 MB)
- **SHA-256:** `09b239888f633ef2f0b4e09736e3d9936acfd810bc65d53fad45261762c6511f`
- **Licencia:** Apache-2.0
- **Uso Recomendado:** STT liviano en hardware de bajos recursos (CPU modesto, bajo consumo de RAM).

### 2.2 Whisper.cpp Tiny (`whisper-ggml-tiny`)
- **ID:** `whisper-ggml-tiny`
- **Motor:** Whisper.cpp (GGML quantized)
- **Idioma / Región:** Multilingüe / Global
- **URL:** `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin`
- **Tamaño:** `77,691,713` bytes (~74.1 MB)
- **SHA-256:** `be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21`
- **Licencia:** MIT
- **Uso Recomendado:** STT universal en CPU/GPU con bajo consumo.

### 2.3 Whisper.cpp Base (`whisper-ggml-base`)
- **ID:** `whisper-ggml-base`
- **Motor:** Whisper.cpp (GGML quantized)
- **Idioma / Región:** Multilingüe / Global
- **URL:** `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin`
- **Tamaño:** `147,951,465` bytes (~141.1 MB)
- **SHA-256:** `60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe`
- **Licencia:** MIT
- **Uso Recomendado:** Mayor precisión STT en hardware con 8+ GB RAM o aceleración CUDA/Vulkan.

---

## 3. Voces TTS (Text-to-Speech) Piper ONNX Verificadas

Cada voz de Piper consta de dos archivos inseparables: el modelo `.onnx` y su archivo de configuración `.onnx.json` (que define sample rate, phonemizer y parámetros de síntesis).

### 3.1 `es_ES-davefx-medium` (Davefx — España)
- **ID Modelo:** `es_ES-davefx-medium`
- **URL Modelo:** `https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx`
- **Tamaño Modelo:** `63,201,294` bytes (~60.3 MB)
- **SHA-256 Modelo:** `6658b03b1a6c316ee4c265a9896abc1393353c2d9e1bca7d66c2c442e222a917`
- **ID Config:** `es_ES-davefx-medium.json`
- **URL Config:** `https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx.json`
- **Tamaño Config:** `4,817` bytes
- **SHA-256 Config:** `0e0dda87c732f6f38771ff274a6380d9252f327dca77aa2963d5fbdf9ec54842`
- **Género:** `unknown` — el model card consultado no declara de forma inequívoca el género de la voz; AILEN no lo infiere por el nombre.
- **Dataset:** Davefx single-speaker dataset
- **Licencia:** CC0-1.0

### 3.2 `es_AR-daniela-high` (Daniela — Argentina)
- **ID Modelo:** `es_AR-daniela-high`
- **URL Modelo:** `https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_AR/daniela/high/es_AR-daniela-high.onnx`
- **Tamaño Modelo:** `114,199,011` bytes (~108.9 MB)
- **SHA-256 Modelo:** `7ceb1fc0dab349418c5b54a639ae9ee595212d7c9ea422220d8419163d5cc985`
- **ID Config:** `es_AR-daniela-high.json`
- **URL Config:** `https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_AR/daniela/high/es_AR-daniela-high.onnx.json`
- **Tamaño Config:** `7,248` bytes
- **SHA-256 Config:** `aedbf69647e1d754c62ecf8e0366ca5f16af3e768e3c6b5329af6eb6bde3852b`
- **Género:** `unknown` — el model card consultado no declara de forma inequívoca el género de la voz; AILEN no lo infiere por el nombre.
- **Dataset:** OpenSLR 61 (Crowdsourced Latin American Spanish)
- **Licencia:** CC-BY-SA-4.0

### 3.3 `es_ES-sharvard-medium` (Voz Multi-speaker — España)
- **ID Modelo:** `es_ES-sharvard-medium`
- **URL Modelo:** `https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/sharvard/medium/es_ES-sharvard-medium.onnx`
- **Tamaño Modelo:** `76,733,615` bytes (~73.2 MB)
- **SHA-256 Modelo:** `40febfb1679c69a4505ff311dc136e121e3419a13a290ef264fdf43ddedd0fb1`
- **ID Config:** `es_ES-sharvard-medium.json`
- **URL Config:** `https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/sharvard/medium/es_ES-sharvard-medium.onnx.json`
- **Tamaño Config:** `4,903` bytes
- **SHA-256 Config:** `7438c9b699c72b0c3388dae1b68d3f364dc66a2150fe554a1c11f03372957b2c`
- **Género Oficial:** `unknown` (Multi-speaker: Speaker 0 Masculino, Speaker 1 Femenino)
- **Dataset:** Spanish Harvard Sentences
- **Licencia:** CC-BY-3.0

### 3.4 `es_ES-carlfm-x_low` (Carlfm Ultra Liviana — España)
- **ID Modelo:** `es_ES-carlfm-x_low`
- **URL Modelo:** `https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/carlfm/x_low/es_ES-carlfm-x_low.onnx`
- **Tamaño Modelo:** `28,130,791` bytes (~26.8 MB)
- **SHA-256 Modelo:** `d69677323a907cd4963f42b29c20a98b5d6bfa7f3e64df339915e4650c00d125`
- **ID Config:** `es_ES-carlfm-x_low.json`
- **URL Config:** `https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/carlfm/x_low/es_ES-carlfm-x_low.onnx.json`
- **Tamaño Config:** `4,159` bytes
- **SHA-256 Config:** `d9bdfa9ff01eb2bc9e62e7d2593939d1e4c4d8eb7cf75f972731539d12399966`
- **Género:** `unknown` — el model card consultado no declara de forma inequívoca el género de la voz; AILEN no lo infiere por el nombre.
- **Dataset:** carlfm single-speaker dataset
- **Licencia del dataset/model card:** Public Domain
- **Uso Recomendado:** Dispositivos con restricción severa de almacenamiento o cómputo (e.g. Banghó Zero G05 / SF20BA).

---

## 4. Runtime Piper actual

Los archivos de voz tienen sus propias licencias, separadas de la licencia del runtime. La implementación actual de Piper mantenida por OHF-Voice (`piper1-gpl` / paquete `piper-tts`) usa GPL-3.0-or-later. Para el prototipo de laboratorio puede instalarse dentro del virtualenv de forma explícita por el operador; antes de distribuir una versión comercial empaquetada se debe revisar de forma deliberada cómo se incluirá o separará este runtime.

El catálogo no etiqueta voces como masculina/femenina salvo que una fuente oficial lo declare explícitamente. En ausencia de esa evidencia, `voice_gender=unknown`. La selección de voz sigue siendo completamente configurable y puede hacerse por escucha/preferencia.

---

## 5. Comandos de Gestión CLI

```bash
# Listar todos los speech assets y su estado local
ailen speech list

# Ver plan recomendado según motor STT y voz deseada
ailen speech plan --stt vosk --voice es_ES-davefx-medium

# Descargar asset individual verificado
ailen speech fetch vosk-model-small-es-0.42 -y
ailen speech fetch es_ES-davefx-medium -y

# Verificar integridad SHA-256 en disco
ailen speech verify vosk-model-small-es-0.42
ailen speech verify es_ES-davefx-medium

# Preparar y descargar automáticamente todo el pipeline de voz para el laboratorio
ailen lab prepare-speech --yes
```
