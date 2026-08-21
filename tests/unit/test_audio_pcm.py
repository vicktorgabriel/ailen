"""Unit tests for PCM audio processing and energy calculations."""

import pytest

from ailen.audio.pcm import (
    compute_pcm_duration_ms,
    compute_pcm_rms,
    generate_silence_pcm,
    generate_tone_pcm,
)


def test_compute_pcm_rms_silence_and_empty() -> None:
    assert compute_pcm_rms(b"") == 0.0
    assert compute_pcm_rms(b"\x00") == 0.0

    silence = generate_silence_pcm(duration_ms=100.0, sample_rate=16000)
    assert compute_pcm_rms(silence) == 0.0


def test_compute_pcm_rms_known_tone() -> None:
    # 50% amplitude sine wave has theoretical RMS of 0.5 / sqrt(2) ≈ 0.3535
    tone = generate_tone_pcm(freq_hz=440.0, duration_ms=200.0, amplitude=0.5, sample_rate=16000)
    rms = compute_pcm_rms(tone)
    assert 0.30 <= rms <= 0.40

    # Low amplitude tone
    quiet_tone = generate_tone_pcm(freq_hz=440.0, duration_ms=200.0, amplitude=0.05, sample_rate=16000)
    quiet_rms = compute_pcm_rms(quiet_tone)
    assert 0.02 <= quiet_rms <= 0.05


def test_compute_pcm_duration_ms() -> None:
    # 16000 Hz, 16-bit (2 bytes), 1 channel: 32000 bytes = 1000 ms
    assert compute_pcm_duration_ms(32000, sample_rate=16000, channels=1) == pytest.approx(1000.0)
    # 640 bytes = 20 ms
    assert compute_pcm_duration_ms(640, sample_rate=16000, channels=1) == pytest.approx(20.0)
    # Invalid rate
    assert compute_pcm_duration_ms(640, sample_rate=0) == 0.0


def test_generate_silence_and_tone_pcm_lengths() -> None:
    # 20 ms @ 16kHz mono = 320 samples * 2 bytes = 640 bytes
    silence = generate_silence_pcm(duration_ms=20.0, sample_rate=16000, channels=1)
    assert len(silence) == 640

    tone = generate_tone_pcm(freq_hz=440.0, duration_ms=50.0, sample_rate=16000)
    # 50 ms @ 16kHz = 800 samples * 2 bytes = 1600 bytes
    assert len(tone) == 1600
