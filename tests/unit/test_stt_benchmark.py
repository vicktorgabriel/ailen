"""Unit tests for the STT benchmark: normalization, WER, engine runner, WAV loading."""

import struct
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

from ailen.audio.contracts import AudioSegment, Transcript
from ailen.audio.stt_benchmark import (
    SttBenchmarkRunner,
    load_wav_pcm16_mono,
    normalize_text_es,
    word_error_rate,
)


class _FakeBackend:
    def __init__(self, text: str, latency_ms: float = 42.0) -> None:
        self.text = text
        self.latency_ms = latency_ms

    def transcribe(self, segment: AudioSegment) -> Transcript:
        return Transcript(text=self.text, confidence=None, latency_ms=self.latency_ms)


def test_normalize_text_es() -> None:
    assert normalize_text_es("Hola, Mundo!") == "hola mundo"
    assert normalize_text_es("  ¿Cómo   estás? ") == "cómo estás"
    assert normalize_text_es("") == ""
    # Accents are preserved (they are meaningful in Spanish).
    assert normalize_text_es("SÍ, MAMÁ") == "sí mamá"


def test_wer_identical_transcripts_is_zero() -> None:
    detail = word_error_rate("hola mundo", "Hola, mundo!")
    assert detail.wer == 0.0
    assert detail.substitutions == 0
    assert detail.reference_words == 2


def test_wer_counts_substitutions_deletions_and_insertions() -> None:
    detail = word_error_rate("detecto un rostro frente a la cámara", "detecto hayden rostro a la")
    # ref: detecto un rostro frente a la cámara (7)
    # hyp: detecto hayden rostro a la        (5)
    assert detail.reference_words == 7
    assert detail.hypothesis_words == 5
    assert detail.wer > 0.4


def test_wer_completely_wrong_and_empty_hypothesis() -> None:
    detail = word_error_rate("cuatro", "hayden")
    assert detail.wer == 1.0
    empty = word_error_rate("hola mundo", "")
    assert empty.wer == 1.0
    assert empty.deletions == 2


def _write_wav(path: Path, sample_rate: int = 16000, channels: int = 1, sampwidth: int = 2) -> None:
    frames = b"\x00\x00" * sample_rate  # 1 second of silence
    if channels == 2:
        frames = frames * 2
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        wf.writeframes(frames)


def test_load_wav_validates_format() -> None:
    with TemporaryDirectory() as tmp:
        good = Path(tmp) / "good.wav"
        _write_wav(good)
        segment = load_wav_pcm16_mono(good)
        assert segment.sample_rate == 16000
        assert segment.channels == 1
        assert segment.duration_ms == 1000.0

        stereo = Path(tmp) / "stereo.wav"
        _write_wav(stereo, channels=2)
        try:
            load_wav_pcm16_mono(stereo)
            raise AssertionError("expected ValueError for stereo file")
        except ValueError as exc:
            assert "mono" in str(exc)

        wrong_rate = Path(tmp) / "44k.wav"
        _write_wav(wrong_rate, sample_rate=44100)
        try:
            load_wav_pcm16_mono(wrong_rate)
            raise AssertionError("expected ValueError for 44.1 kHz file")
        except ValueError as exc:
            assert "sample rate" in str(exc)

        missing = Path(tmp) / "missing.wav"
        try:
            load_wav_pcm16_mono(missing)
            raise AssertionError("expected ValueError for missing file")
        except ValueError as exc:
            assert "no encontrado" in str(exc)


def test_runner_scores_reference_and_reports_not_installed_engines() -> None:
    runner = SttBenchmarkRunner(
        vosk_model_path="/tmp/unused-model-dir",
        whisper_binary="definitely-not-installed-binary",
        whisper_model_path="",
    )
    fake_vosk = _FakeBackend("Detecto un rostro frente a la cámara")
    runner.backends["vosk"] = fake_vosk  # injected backend skips model resolution

    with TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "utt.wav"
        _write_wav(wav_path)
        results = runner.run(
            [wav_path],
            engines=["vosk", "whisper_cpp"],
            reference="Detecto un rostro frente a la cámara.",
        )

    by_engine = {r.engine: r for r in results}
    vosk_res = by_engine["vosk"]
    assert vosk_res.status == "OK"
    assert vosk_res.word_count == 7
    assert vosk_res.empty_transcript is False
    assert vosk_res.exact_match is False  # trailing punctuation differs
    assert vosk_res.normalized_match is True
    assert vosk_res.wer == 0.0
    assert vosk_res.latency_ms == 42.0

    whisper_res = by_engine["whisper_cpp"]
    assert whisper_res.status == "NOT_INSTALLED"
    assert whisper_res.transcript == ""
    assert whisper_res.wer is None


def test_runner_empty_transcript_with_reference_has_full_wer() -> None:
    runner = SttBenchmarkRunner()
    runner.backends["vosk"] = _FakeBackend("")
    with TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "utt.wav"
        _write_wav(wav_path)
        results = runner.run([wav_path], engines=["vosk"], reference="hola que tal")

    res = results[0]
    assert res.empty_transcript is True
    assert res.wer == 1.0
    assert res.normalized_match is False


def test_runner_invalid_wav_yields_error_result_per_engine() -> None:
    runner = SttBenchmarkRunner()
    runner.backends["vosk"] = _FakeBackend("x")
    with TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.wav"
        bad.write_bytes(struct.pack("<4s", b"JUNK"))
        results = runner.run([bad], engines=["vosk"])
    assert results[0].status == "ERROR"


def test_runner_rejects_unknown_engine() -> None:
    runner = SttBenchmarkRunner()
    with TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "utt.wav"
        _write_wav(wav_path)
        try:
            runner.run([wav_path], engines=["made_up_engine"])
            raise AssertionError("expected ValueError for unsupported engine")
        except ValueError as exc:
            assert "no soportados" in str(exc)
