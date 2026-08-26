# Local AI Model Comparison & Benchmark Report

**Host:** Asrock Workstation (Linux Mint 22.3, Ryzen 5 5500, 48 GB RAM, RTX 3060 12 GB)  
**Date:** 2026-08-22  
**Harness:** `ailen lab benchmark-ai` — Ollama native `/api/chat` when Ollama is detected, `think=false`, no model downloads.

## Measured performance

```text
==================================================================
AILEN — LOCAL AI INFERENCE BENCHMARK
Endpoint: http://127.0.0.1:11434/v1
==================================================================
MODEL                    STATUS          FIRST(ms)  AVG(ms)    P95(ms)    TOK/S    PASS%
----------------------------------------------------------------------------------------
qwen3.5:9b               PASS            342.1      1763.6     2616.3     42.63    100.0%
qwen2.5-coder:3b         PASS            103.1      570.3      940.0      127.13   100.0%
llama3.2:3b              NOT_INSTALLED   -          -          -          -        -
gemma3:4b                NOT_INSTALLED   -          -          -          -        -
qwen3.5:4b               NOT_INSTALLED   -          -          -          -        -
==================================================================
```

`FIRST(ms)` means the first observed benchmark turn. It is **not** claimed to be a cold start because the harness intentionally does not evict/unload an external runtime model. `TOK/S` is reported only when the runtime exposes generation duration/count; for Ollama it is derived from native `eval_count` / `eval_duration`, not from total request latency.

The benchmark prompts are longer than the physical short-voice turns. In the physical G600 session, warmed `qwen3.5:9b` commonly completed short replies in roughly 0.55–0.85 s, with occasional longer replies above 1 s. Those physical values and this benchmark answer different questions and should not be mixed.

## Findings

### qwen3.5:9b

- Current QUALITY reference on the Asrock lab only; the RTX 3060 is not a product requirement.
- Uses Ollama native API with thinking disabled for voice latency.
- Generation throughput in this run: ~42.6 tokens/s.
- Still gives higher conversational capacity than the installed 3B coder model.

### qwen2.5-coder:3b

- Much faster on this GPU: ~0.57 s average benchmark latency and ~127 tokens/s generation in this run.
- It is a coder-specialized model, so it is useful as a performance reference but **not** accepted as AILEN's general FAST baseline.
- Product FAST candidates remain `llama3.2:3b`, `qwen3.5:4b` and `gemma3:4b`, all currently `NOT_INSTALLED` on this host.

## TTS latency finding

The installed `piper-tts` Python API exposes sentence `AudioChunk` iteration. After the voice model is cached in-process, a local test produced the first chunk in ~65 ms and completed synthesis of a short two-sentence sample in ~0.40 s. The initial model load cost was about 2 s, so Lab now prewarms Piper before microphone capture begins. The cached Python API is the sole canonical synthesis route; an unavailable API degrades TTS explicitly instead of selecting a hidden CLI path.

## Next physical benchmarks

1. CPU-only FAST model on the Banghó Zero G05 / other 8 GB no-GPU hardware.
2. General-chat FAST candidates before choosing a default.
3. Physical TTFAR after Piper prewarm/chunked playback.
4. Vosk vs whisper.cpp recognition/latency with the same microphone and test phrases.
