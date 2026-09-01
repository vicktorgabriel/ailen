# Voice Turn, Local AI and Streaming Integration Plan

> **For agentic workers:** execute inline in the current checkout. Do not create a worktree, commit, push, reset, restore, clean, or discard unrelated changes.

**Goal:** close only the missing integration between real STT evidence, controlled tool routing, incremental LLM-to-TTS speech, and capability-based local/LAN/external inference.

**Architecture:** Keep `AiBackend` as the single inference boundary used by Ollama, llama.cpp/OpenAI-compatible, LAN, and external providers. Enrich the existing `Transcript` contract instead of adding a parallel voice-turn type; pass it intact through `LabRunner` to `ConversationCoordinator`. For voice output, feed real backend deltas into a bounded phrase queue consumed by one audio speech session so playback starts before generation ends and the existing barge-in cancellation stops playback, pending TTS, and the producer callback.

**Tech Stack:** Python 3.11+, stdlib threads/queues/events, existing Vosk/Piper/HTTP adapters, pytest, Ruff, mypy.

**Spec:** `docs/architecture/adr/ADR-011-configurable-external-ai-providers-and-admin.md`

## Global Constraints

- ASRock is a contended Lab and cannot prove 4 GB or 8 GB support.
- Local AI may be required by an installation, but `ai.local.enabled=false` remains a strict administrator boundary.
- Never load more than one conversational model merely to route a turn.
- No user PCM, transcripts, secrets, or private memories in benchmark artifacts.
- Vosk/Piper/FacePack remain the baseline; physical VAD and barge-in closure is separate from unit tests.

---

### Task 1: Preserve acoustic evidence end to end

**Files:**
- Modify: `src/ailen/audio/contracts.py`
- Modify: `src/ailen/audio/{vosk_backend,whisper_backend,fake,stt_cascade,coordinator}.py`
- Modify: `src/ailen/runtime/runner.py`
- Modify: `src/ailen/core/conversation.py`
- Test: `tests/unit/test_audio_coordinator.py`
- Test: `tests/unit/test_lab_runner_wiring.py`
- Test: `tests/unit/test_conversation_tools_integration.py`

**Produces:** one `Transcript` carrying `text`, real `confidence`, STT engine, audio duration, utterance id, interruption state, and optional alternatives from STT through routing.

- [ ] Add failing tests proving the event and conversation handler preserve every field.
- [ ] Run the focused tests and confirm they fail because metadata is currently discarded.
- [ ] Extend `Transcript` and enrich it at utterance finalization without fabricating confidence or alternatives.
- [ ] Make `LabRunner` pass the contract to `ConversationCoordinator.handle_transcript()` instead of reducing it to text.
- [ ] Re-run the focused tests.

### Task 2: Gate side effects with acoustic and semantic confidence

**Files:**
- Modify: `src/ailen/tools/contracts.py`
- Modify: `src/ailen/tools/executor.py`
- Modify: `src/ailen/tools/builtin/*.py`
- Modify: `src/ailen/tools/fake.py`
- Modify: `src/ailen/core/config.py`
- Modify: `src/ailen/core/conversation.py`
- Modify: `config/ailen.example.toml`
- Test: `tests/unit/test_tool_executor.py`
- Test: `tests/unit/test_conversation_tools_integration.py`

**Produces:** `Tool.is_side_effecting(arguments)` plus a central fail-closed voice guard. Read-only queries remain available; changing volume/music/timers/notes/reminders/camera/face requires sufficient acoustic confidence, an unambiguous resolver result, and a complete non-interrupted utterance.

- [ ] Add failing low-confidence/interrupted/high-confidence tests using real registered tools.
- [ ] Add explicit side-effect classification to the tool contract and each built-in.
- [ ] Add a configurable voice action confidence floor with validation.
- [ ] Return the existing deterministic STT-reprompt class of response before tool execution when the guard fails.
- [ ] Verify text input and low-confidence read-only queries remain unaffected.

### Task 3: Keep open conversation on the LLM path

**Files:**
- Modify: `src/ailen/ai/router.py`
- Test: `tests/unit/test_ai_router.py`
- Test: `tests/unit/test_conversation_tools_integration.py`

**Produces:** direct user greetings, humor, opinions, and open chat reach a conversational backend. Only verified Core results, operational errors, tool confirmations, and STT/tool clarification remain deterministic.

- [ ] Add a failing test showing `intent="greeting"` currently routes to `rule`.
- [ ] Remove conversational greeting from the rule-only intent set.
- [ ] Characterize capability-registry and tool clarifications as verified/operational rule responses, not chat replacements.

### Task 4: Stream complete phrases into one cancelable speech session

**Files:**
- Modify: `src/ailen/audio/speech_text.py`
- Modify: `src/ailen/audio/coordinator.py`
- Modify: `src/ailen/core/conversation.py`
- Test: `tests/unit/test_speech_text.py`
- Test: `tests/unit/test_audio_coordinator.py`
- Test: `tests/unit/test_ai_conversation.py`

**Produces:** an incremental sentence segmenter and `AudioInteractionCoordinator.speak_requests()` using a bounded one-chunk prefetch queue. The voice path starts TTS after the first safe phrase, continues model generation concurrently, and stops the backend callback when barge-in sets the canonical speech cancellation event.

- [ ] Add failing tests for split deltas, no metadata pronunciation, early first playback, bounded order, and cancellation.
- [ ] Implement the segmenter with punctuation boundaries and a bounded final flush.
- [ ] Refactor `speak()` to delegate to one multi-request speech session; do not duplicate playback/face/gate logic.
- [ ] Connect `ConversationCoordinator` streaming deltas to a bounded phrase queue and skip the old second full-response `speak()`.
- [ ] Preserve full generated text for memory unless the turn was interrupted; never claim an active Piper ONNX call itself is abortable.

### Task 5: Reconcile hardware tiers and model residency

**Files:**
- Modify: `src/ailen/models/inference_profile.py`
- Modify: `src/ailen/ai/residency.py`
- Modify: `src/ailen/runtime/runner.py` only if a safe lifecycle hook already exists
- Test: `tests/unit/test_inference_profile.py`
- Test: `tests/unit/test_model_residency.py`

**Produces:** deterministic planning envelopes for constrained 4 GB, 8 GB CPU/iGPU, dedicated GPU, and LAN delegation. Recommendations remain hypotheses until physical benchmarks. FAST profiles avoid eager secondary-model prewarm; Ollama keep-alive provides lazy reload/idle release, while owned llama.cpp lifecycle remains explicit.

- [ ] Add failing tests for the exact memory envelopes and strict user disable boundary.
- [ ] Consolidate duplicated thresholds so detector/planner recommendations cannot disagree.
- [ ] Encode pressure/idle release decisions as pure policy before wiring any process control.
- [ ] Wire only lifecycle actions that are ownership-safe and automatically recoverable on the next inference.

### Task 6: Canonical documentation and gates

**Files:**
- Modify: `docs/architecture/adr/ADR-011-configurable-external-ai-providers-and-admin.md`
- Modify: `ARCHITECTURE.md`
- Modify: `docs/architecture/MODULE_CONTRACTS.md`
- Modify: `docs/memory/{CURRENT_STATE,RECENT_DECISIONS}.md`
- Modify: `ROADMAP.md`, `TASKS.md`, `CHANGELOG.md`
- Modify: `config/ailen.toml` only to remove the confirmed workshop-only persona description.

- [ ] Document local Ollama, local llama.cpp, trusted LAN, external APIs, and automatic fallback as peers behind `AiBackend`.
- [ ] Document that 4/8 GB model bands are candidates pending physical TTFA/RTF/RSS measurements.
- [ ] Document WebRTC mode 2/3 and 380/500/600 ms as a no-recording physical matrix; do not change thresholds from unit evidence.
- [ ] Run focused tests, full pytest, Ruff, mypy, `git diff --check`, and secret/media checks.
- [ ] Report physical items honestly: microphone/VAD, preserved barge-in transcript, CPU contention, Chatterbox LAN, and real 4/8 GB pressure.
