"""PCM utilities and energy calculations for AILEN audio processing.

Standard format: 16-bit signed little-endian PCM (s16le), mono, 16000 Hz.
"""

import math
import struct


def compute_pcm_rms(data: bytes) -> float:
    """Compute normalized Root Mean Square (RMS) amplitude from 16-bit PCM bytes.

    Returns a float in [0.0, 1.0], where 0.0 is complete silence and 1.0 is maximum peak.
    """
    if not data or len(data) < 2:
        return 0.0

    # Number of 16-bit samples
    num_samples = len(data) // 2
    if num_samples == 0:
        return 0.0

    # Unpack signed 16-bit little-endian samples
    # 'h' is 2-byte signed integer (-32768 to 32767)
    format_str = f"<{num_samples}h"
    try:
        samples = struct.unpack(format_str, data[: num_samples * 2])
    except struct.error:
        return 0.0

    # Sum of squares
    sum_squares = sum(s * s for s in samples)
    mean_square = sum_squares / num_samples
    rms = math.sqrt(mean_square)

    # Normalize to 0.0 .. 1.0 (32767 is max amplitude for signed 16-bit)
    normalized = rms / 32768.0
    return min(1.0, max(0.0, normalized))


def compute_pcm_duration_ms(
    data_len_bytes: int,
    sample_rate: int = 16000,
    bytes_per_sample: int = 2,
    channels: int = 1,
) -> float:
    """Calculate duration in milliseconds from byte length and format."""
    bytes_per_second = sample_rate * bytes_per_sample * channels
    if bytes_per_second <= 0:
        return 0.0
    return (data_len_bytes / bytes_per_second) * 1000.0


def generate_silence_pcm(
    duration_ms: float,
    sample_rate: int = 16000,
    channels: int = 1,
) -> bytes:
    """Generate empty silence PCM bytes (zeros)."""
    num_samples = int(sample_rate * channels * (duration_ms / 1000.0))
    return b"\x00\x00" * num_samples


def generate_tone_pcm(
    freq_hz: float,
    duration_ms: float,
    amplitude: float = 0.5,
    sample_rate: int = 16000,
) -> bytes:
    """Generate synthetic sine wave tone in 16-bit signed PCM for tests and benchmarks."""
    num_samples = int(sample_rate * (duration_ms / 1000.0))
    clamped_amp = min(1.0, max(0.0, amplitude)) * 32760.0
    two_pi_f = 2.0 * math.pi * freq_hz

    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        val = int(clamped_amp * math.sin(two_pi_f * t))
        samples.append(max(-32767, min(32767, val)))

    format_str = f"<{len(samples)}h"
    return struct.pack(format_str, *samples)
