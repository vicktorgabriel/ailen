"""Audio package: I/O, VAD, STT, TTS, TurnGate, and Coordinator."""

from ailen.audio.alsa_backend import (
    AlsaAudioInputBackend,
    AlsaAudioOutputBackend,
    AlsaDeviceEnumerator,
)
from ailen.audio.contracts import (
    AudioBackendHealth,
    AudioDevice,
    AudioDeviceEnumerator,
    AudioInputBackend,
    AudioOutputBackend,
    AudioSegment,
    SpeechOutput,
    SpeechRequest,
    SttBackend,
    Transcript,
    TtsBackend,
    VadResult,
    VoiceActivityDetector,
)
from ailen.audio.coordinator import AudioInteractionCoordinator
from ailen.audio.fake import (
    FakeAudioInputBackend,
    FakeAudioOutputBackend,
    FakeDeviceEnumerator,
    FakeSttBackend,
    FakeTtsBackend,
)
from ailen.audio.pcm import (
    compute_pcm_duration_ms,
    compute_pcm_rms,
    generate_silence_pcm,
    generate_tone_pcm,
)
from ailen.audio.piper_backend import PiperTtsBackend
from ailen.audio.turn_gate import AudioTurnGate, GateState
from ailen.audio.vad import EnergyVad, UtteranceCollector
from ailen.audio.vosk_backend import VoskSttBackend
from ailen.audio.whisper_backend import WhisperCppSttBackend

__all__ = [
    "AlsaAudioInputBackend",
    "AlsaAudioOutputBackend",
    "AlsaDeviceEnumerator",
    "AudioBackendHealth",
    "AudioDevice",
    "AudioDeviceEnumerator",
    "AudioInputBackend",
    "AudioInteractionCoordinator",
    "AudioOutputBackend",
    "AudioSegment",
    "AudioTurnGate",
    "EnergyVad",
    "FakeAudioInputBackend",
    "FakeAudioOutputBackend",
    "FakeDeviceEnumerator",
    "FakeSttBackend",
    "FakeTtsBackend",
    "GateState",
    "PiperTtsBackend",
    "SpeechOutput",
    "SpeechRequest",
    "SttBackend",
    "Transcript",
    "TtsBackend",
    "UtteranceCollector",
    "VadResult",
    "VoiceActivityDetector",
    "VoskSttBackend",
    "WhisperCppSttBackend",
    "compute_pcm_duration_ms",
    "compute_pcm_rms",
    "generate_silence_pcm",
    "generate_tone_pcm",
]
