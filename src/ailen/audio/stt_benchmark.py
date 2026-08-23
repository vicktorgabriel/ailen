"""Reproducible STT quality benchmark for AILEN Lab.

Passes the exact same WAV audio through multiple offline STT engines (Vosk,
whisper.cpp) and compares transcripts and latency. Never downloads models:
missing engines/models are reported as NOT_INSTALLED.

WER is computed with a simple word-level Levenshtein alignment over normalized
text (lowercase, basic Spanish punctuation stripped, whitespace collapsed).
Transcripts are never semantically corrected before scoring.
"""

import logging
import wave
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ailen.audio.contracts import AudioSegment

logger = logging.getLogger(__name__)

SUPPORTED_ENGINES: tuple[str, ...] = ("vosk", "whisper_cpp")

# Basic Spanish punctuation stripped before WER (accents are preserved).
_PUNCTUATION_CHARS = ".,;:!?¡¿\"'()[]{}<>«»…-–—_"


@dataclass
class WerDetail:
    """Word-level error decomposition between reference and hypothesis."""

    wer: float
    substitutions: int
    deletions: int
    insertions: int
    reference_words: int
    hypothesis_words: int


@dataclass
class SttBenchmarkResult:
    """One engine run over one WAV file."""

    engine: str
    model_label: str
    wav_path: str
    status: str  # "OK" | "NOT_INSTALLED" | "ERROR"
    detail: str = ""
    transcript: str = ""
    latency_ms: float | None = None
    word_count: int = 0
    empty_transcript: bool = True
    exact_match: bool | None = None
    normalized_match: bool | None = None
    wer: float | None = None
    wer_detail: WerDetail | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "model_label": self.model_label,
            "wav_path": self.wav_path,
            "status": self.status,
            "detail": self.detail,
            "transcript": self.transcript,
            "latency_ms": None if self.latency_ms is None else round(self.latency_ms, 2),
            "word_count": self.word_count,
            "empty_transcript": self.empty_transcript,
            "exact_match": self.exact_match,
            "normalized_match": self.normalized_match,
            "wer": None if self.wer is None else round(self.wer, 4),
            "wer_detail": None
            if self.wer_detail is None
            else {
                "substitutions": self.wer_detail.substitutions,
                "deletions": self.wer_detail.deletions,
                "insertions": self.wer_detail.insertions,
                "reference_words": self.wer_detail.reference_words,
                "hypothesis_words": self.wer_detail.hypothesis_words,
            },
        }


def normalize_text_es(text: str) -> str:
    """Lowercase, strip basic punctuation and collapse whitespace."""
    lowered = (text or "").lower()
    for ch in _PUNCTUATION_CHARS:
        lowered = lowered.replace(ch, " ")
    return " ".join(lowered.split())


def word_error_rate(reference: str, hypothesis: str) -> WerDetail:
    """Word-level WER with substitution/deletion/insertion counts."""
    ref_words = normalize_text_es(reference).split()
    hyp_words = normalize_text_es(hypothesis).split()

    if not ref_words:
        if not hyp_words:
            return WerDetail(0.0, 0, 0, 0, 0, len(hyp_words))
        return WerDetail(1.0, 0, 0, len(hyp_words), 0, len(hyp_words))

    rows = len(ref_words) + 1
    cols = len(hyp_words) + 1
    # DP matrices for distance and operation counts.
    dist = [[0] * cols for _ in range(rows)]
    subs = [[0] * cols for _ in range(rows)]
    dels = [[0] * cols for _ in range(rows)]
    ins = [[0] * cols for _ in range(rows)]

    for i in range(1, rows):
        dist[i][0] = i
        dels[i][0] = i
    for j in range(1, cols):
        dist[0][j] = j
        ins[0][j] = j

    for i in range(1, rows):
        for j in range(1, cols):
            if ref_words[i - 1] == hyp_words[j - 1]:
                dist[i][j] = dist[i - 1][j - 1]
                subs[i][j] = subs[i - 1][j - 1]
                dels[i][j] = dels[i - 1][j - 1]
                ins[i][j] = ins[i - 1][j - 1]
            else:
                sub_cost = dist[i - 1][j - 1] + 1
                del_cost = dist[i - 1][j] + 1
                ins_cost = dist[i][j - 1] + 1
                best = min(sub_cost, del_cost, ins_cost)
                dist[i][j] = best
                if best == sub_cost:
                    subs[i][j] = subs[i - 1][j - 1] + 1
                    dels[i][j] = dels[i - 1][j - 1]
                    ins[i][j] = ins[i - 1][j - 1]
                elif best == del_cost:
                    subs[i][j] = subs[i - 1][j]
                    dels[i][j] = dels[i - 1][j] + 1
                    ins[i][j] = ins[i - 1][j]
                else:
                    subs[i][j] = subs[i][j - 1]
                    dels[i][j] = dels[i][j - 1]
                    ins[i][j] = ins[i][j - 1] + 1

    total_errors = dist[-1][-1]
    return WerDetail(
        wer=total_errors / len(ref_words),
        substitutions=subs[-1][-1],
        deletions=dels[-1][-1],
        insertions=ins[-1][-1],
        reference_words=len(ref_words),
        hypothesis_words=len(hyp_words),
    )


def load_wav_pcm16_mono(path: str | Path, expected_sample_rate: int = 16000) -> AudioSegment:
    """Load a PCM16 mono WAV file as an AudioSegment for STT engines.

    Raises ValueError with an operator-actionable message for unsupported files.
    """
    wav_path = Path(path)
    if not wav_path.is_file():
        raise ValueError(f"Archivo WAV no encontrado: {wav_path}")

    try:
        with wave.open(str(wav_path), "rb") as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
    except (wave.Error, EOFError) as exc:
        raise ValueError(f"{wav_path.name}: archivo WAV inválido o corrupto ({exc})") from exc

    if sampwidth != 2:
        raise ValueError(f"{wav_path.name}: se requiere PCM 16-bit (sampwidth=2), obtenido sampwidth={sampwidth}")
    if channels != 1:
        raise ValueError(f"{wav_path.name}: se requiere mono (channels=1), obtenido channels={channels}")
    if rate != expected_sample_rate:
        raise ValueError(
            f"{wav_path.name}: se requiere sample rate {expected_sample_rate} Hz, obtenido {rate} Hz"
        )
    duration_ms = (len(frames) / 2.0) / rate * 1000.0
    return AudioSegment(data=frames, sample_rate=rate, channels=channels, duration_ms=duration_ms)


def resolve_vosk_model(configured_path: str = "") -> str | None:
    """Resolve an existing local Vosk model directory or None (never downloads)."""
    if not configured_path:
        return None
    candidate = Path(configured_path).expanduser()
    return str(candidate) if candidate.is_dir() else None


def resolve_whisper_assets(binary_path: str = "", model_path: str = "") -> tuple[str | None, str | None]:
    """Resolve existing whisper.cpp binary and model or (None, None). Never downloads."""
    from ailen.audio.whisper_backend import WhisperCppSttBackend

    backend = WhisperCppSttBackend(binary_path=binary_path or "whisper-cli", model_path=model_path)
    resolved_binary = backend._resolve_binary()
    model_ok = bool(model_path) and Path(model_path).expanduser().is_file()
    return (resolved_binary, str(Path(model_path).expanduser()) if model_ok else None)


@dataclass
class SttBenchmarkRunner:
    """Runs identical WAV inputs through multiple STT engines."""

    vosk_model_path: str = ""
    whisper_binary: str = "whisper-cli"
    whisper_model_path: str = ""
    language: str = "es"
    backends: dict[str, Any] = field(default_factory=dict, repr=False)

    def run(
        self,
        wav_paths: Sequence[str | Path],
        *,
        engines: list[str] | None = None,
        reference: str | None = None,
    ) -> list[SttBenchmarkResult]:
        """Transcribe each WAV with each requested engine and score against reference."""
        requested_engines = engines or list(SUPPORTED_ENGINES)
        unsupported = [e for e in requested_engines if e not in SUPPORTED_ENGINES]
        if unsupported:
            raise ValueError(f"Motores STT no soportados: {', '.join(unsupported)}")
        selected_engines = list(requested_engines)
        results: list[SttBenchmarkResult] = []

        for wav_path in wav_paths:
            try:
                segment = load_wav_pcm16_mono(wav_path)
            except ValueError as exc:
                for engine in selected_engines:
                    results.append(
                        SttBenchmarkResult(
                            engine=engine,
                            model_label=self._model_label(engine),
                            wav_path=str(wav_path),
                            status="ERROR",
                            detail=str(exc),
                        )
                    )
                continue

            for engine in selected_engines:
                results.append(self._run_engine(engine, segment, str(wav_path), reference))

        return results

    def _model_label(self, engine: str) -> str:
        if engine == "vosk":
            return self.vosk_model_path or "<unconfigured>"
        if engine == "whisper_cpp":
            return self.whisper_model_path or "<unconfigured>"
        return "<unknown>"

    def _run_engine(
        self,
        engine: str,
        segment: AudioSegment,
        wav_path: str,
        reference: str | None,
    ) -> SttBenchmarkResult:
        label = self._model_label(engine)

        try:
            backend = self._get_backend(engine)
        except _NotInstalledError as exc:
            return SttBenchmarkResult(
                engine=engine,
                model_label=label,
                wav_path=wav_path,
                status="NOT_INSTALLED",
                detail=str(exc),
            )

        transcript = backend.transcribe(segment)
        text = (transcript.text or "").strip()

        result = SttBenchmarkResult(
            engine=engine,
            model_label=label,
            wav_path=wav_path,
            status="OK",
            transcript=text,
            latency_ms=transcript.latency_ms,
            word_count=len(text.split()),
            empty_transcript=not text,
        )

        if reference is not None:
            result.exact_match = text.strip() == reference.strip()
            result.normalized_match = normalize_text_es(text) == normalize_text_es(reference)
            detail = word_error_rate(reference, text)
            result.wer = detail.wer
            result.wer_detail = detail

        return result

    def _get_backend(self, engine: str) -> Any:
        cached = self.backends.get(engine)
        if cached is not None:
            return cached

        if engine == "vosk":
            from ailen.audio.vosk_backend import VoskSttBackend

            model_path = resolve_vosk_model(self.vosk_model_path)
            if model_path is None:
                raise _NotInstalledError(f"modelo Vosk no encontrado: '{self.vosk_model_path or '<vacío>'}'")
            vosk_backend = VoskSttBackend(model_path=model_path, sample_rate=16000)
            health = vosk_backend.health()
            if health.status.name != "HEALTHY":
                raise _NotInstalledError(f"Vosk no disponible: {health.detail}")
            self.backends[engine] = vosk_backend
            return vosk_backend

        if engine == "whisper_cpp":
            from ailen.audio.whisper_backend import WhisperCppSttBackend

            binary, model = resolve_whisper_assets(self.whisper_binary, self.whisper_model_path)
            if binary is None:
                raise _NotInstalledError(f"binario whisper.cpp no encontrado: '{self.whisper_binary}'")
            if model is None:
                raise _NotInstalledError(f"modelo whisper ggml no encontrado: '{self.whisper_model_path or '<vacío>'}'")
            whisper_backend = WhisperCppSttBackend(
                binary_path=binary,
                model_path=model,
                language=self.language,
            )
            health = whisper_backend.health()
            if health.status.name != "HEALTHY":
                raise _NotInstalledError(f"whisper.cpp no disponible: {health.detail}")
            self.backends[engine] = whisper_backend
            return whisper_backend

        raise _NotInstalledError(f"motor desconocido: {engine}")


class _NotInstalledError(Exception):
    """Raised internally when an engine or its assets are unavailable."""
