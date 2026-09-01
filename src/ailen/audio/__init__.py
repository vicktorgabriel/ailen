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
    StagedAudioFrameProcessor,
    SttBackend,
    Transcript,
    TranscriptAlternative,
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
from ailen.audio.level import (
    AudioProcessorChain,
    CaptureLevelMetrics,
    CaptureLevelProcessor,
    build_capture_processor,
)
from ailen.audio.pcm import (
    compute_pcm_duration_ms,
    compute_pcm_rms,
    generate_silence_pcm,
    generate_tone_pcm,
)
from ailen.audio.piper_backend import PiperTtsBackend
from ailen.audio.speech_text import (
    IncrementalSpeechSegmenter,
    normalize_text_for_speech,
    split_speech_for_streaming,
    split_speech_into_sentences,
)
from ailen.audio.stt_cascade import CascadingSttBackend
from ailen.audio.stt_quality import (
    SttConfidenceBand,
    SttQualityAssessment,
    SttQualityEvaluator,
)
from ailen.audio.turn_gate import AudioTurnGate, GateState
from ailen.audio.vad import EnergyVad, UtteranceCollector, VadProfile, get_vad_profile_timings
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
    "AudioProcessorChain",
    "AudioSegment",
    "AudioTurnGate",
    "CaptureLevelMetrics",
    "CaptureLevelProcessor",
    "CascadingSttBackend",
    "EnergyVad",
    "FakeAudioInputBackend",
    "FakeAudioOutputBackend",
    "FakeDeviceEnumerator",
    "FakeSttBackend",
    "FakeTtsBackend",
    "GateState",
    "IncrementalSpeechSegmenter",
    "PiperTtsBackend",
    "SpeechOutput",
    "SpeechRequest",
    "StagedAudioFrameProcessor",
    "SttBackend",
    "SttConfidenceBand",
    "SttQualityAssessment",
    "SttQualityEvaluator",
    "Transcript",
    "TranscriptAlternative",
    "TtsBackend",
    "UtteranceCollector",
    "VadProfile",
    "VadResult",
    "VoiceActivityDetector",
    "VoskSttBackend",
    "WhisperCppSttBackend",
    "build_capture_processor",
    "compute_pcm_duration_ms",
    "compute_pcm_rms",
    "generate_silence_pcm",
    "generate_tone_pcm",
    "get_vad_profile_timings",
    "normalize_text_for_speech",
    "split_speech_for_streaming",
    "split_speech_into_sentences",
]
