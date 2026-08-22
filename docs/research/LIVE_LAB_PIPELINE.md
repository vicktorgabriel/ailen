# Pipeline de Laboratorio en Vivo (R3B.2)

## 1. Visión General

El pipeline de laboratorio de AILEN (`LabRunner`) está cableado en software para conectar de extremo a extremo periféricos físicos, modelos locales de habla, visión de presencia y modelos de razonamiento (LLM local o enrutamiento cloud/reglas) de forma modular. Esta arquitectura no implica todavía que la sesión física Mint haya sido validada; esa evidencia corresponde a R3B.3.

```
+-----------------------------------------------------------------------------------+
|                               AILEN LIVE LAB PIPELINE                             |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  [V4L2 Camera] ----> OpenCvVisionBackend                                          |
|                             |                                                     |
|                             v                                                     |
|                    PresenceObservation                                            |
|                             |                                                     |
|                             v                                                     |
|                     VisionDebouncer                                               |
|                             |                                                     |
|                             v                                                     |
|                  InteractionCoordinator ----> SocialEngine                        |
|                             |                      |                              |
|                             v                      v                              |
|                      FaceController <------- Gaze / State                         |
|                             |                                                     |
+-----------------------------|-----------------------------------------------------+
|                             |                                                     |
|  [ALSA Mic] ------> AlsaAudioInputBackend                                         |
|                             |                                                     |
|                             v                                                     |
|                     EnergyVad (Frames)                                            |
|                             |                                                     |
|                             v                                                     |
|                    UtteranceCollector                                             |
|                             |                                                     |
|                             v                                                     |
|                     VoskSttBackend / WhisperCppSttBackend                         |
|                             |                                                     |
|                             v                                                     |
|                     Transcript (text)                                             |
|                             |                                                     |
|                             v                                                     |
|                     EventBus (TRANSCRIPT_READY)                                   |
|                             |                                                     |
|                             v                                                     |
|                   [Single-Flight Lock]                                            |
|                             |                                                     |
|                             v                                                     |
|                 ConversationCoordinator                                           |
|                   |-> AiContextBuilder (Memory / Privacy Filter)                  |
|                   |-> RuleBasedRouter (Profile, Privacy, Budget)                  |
|                   |-> AiOrchestrator (Local Ollama / llama.cpp / Cloud / Rule)    |
|                             |                                                     |
|                             v                                                     |
|                         AiResponse                                                |
|                             |                                                     |
|                             v                                                     |
|                 AudioInteractionCoordinator.speak()                               |
|                             |                                                     |
|                             +---> TurnGate (Half-Duplex Mic Inhibit)              |
|                             +---> PiperTtsBackend (Speech Synthesis)              |
|                             +---> AlsaAudioOutputBackend (Playback)               |
|                             +---> FaceController (RMS Mouth Envelope)             |
|                                                                                   |
+-----------------------------------------------------------------------------------+
```

## 2. Regla "No Silent Fakes"

En modo de laboratorio real (`ailen lab start` sin `--simulate`):
- Los adaptadores `FakeSttBackend`, `FakeTtsBackend`, `FakeAiBackend`, `FakeVisionBackend` y `FakeAudioBackend` quedan **estrictamente prohibidos**.
- Si un componente carece de biblioteca o modelo físico, el estado reportado en la tabla de arranque es `MISSING_MODEL`, `UNAVAILABLE` o `DISABLED`.
- El modo `--simulate` es el único mecanismo habilitado para correr con backends sintéticos con fines de desarrollo offline de interfaz.

## 3. Serialización de Interacción (Single-Flight Lock)

Para evitar condiciones de carrera donde múltiples utterances generen respuestas superpuestas:
1. Al recibir `TRANSCRIPT_READY`, se adquiere un candado atómico (`_interaction_lock`).
2. Mientras la inferencia o la síntesis de voz se encuentra activa (`PROCESSING` / `SPEAKING`), cualquier transcripción concurrente es ignorada limpiamente.
3. El `AudioTurnGate` inhabilita la captura del micrófono durante la reproducción de audio (Half-Duplex estricto).
4. Al concluir la locución, el sistema retorna a `ATTENTION` (si la cámara detecta presencia continua) o `IDLE`.

## 4. Ownership de Procesos de Inferencia

- **Runtimes preexistentes (Ollama / servidores externos):** AILEN los detecta y consume vía HTTP OpenAI-compatible sin asumir propiedad ni detenerlos al salir.
- **Runtimes gestionados (`ManagedLlamaRuntime`):** `ailen lab prepare-ai --start-runtime` sólo realiza un smoke/health-check temporal y lo detiene antes de salir. La sesión `ailen lab start` es la única que puede mantener un `llama-server` propio vivo; registra `owned_by_ailen=True` y lo finaliza limpiamente (`SIGTERM` con fallback `SIGKILL`) ante Ctrl+C o cierre.
