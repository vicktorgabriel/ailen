"""Unit tests for Voice Activity Detection and Utterance Collector."""

from ailen.audio.pcm import generate_silence_pcm, generate_tone_pcm
from ailen.audio.vad import EnergyVad, UtteranceCollector


def test_energy_vad_speech_detection_and_hangover() -> None:
    vad = EnergyVad(threshold_rms=0.02, hangover_frames=3)

    silence_frame = generate_silence_pcm(duration_ms=20.0, sample_rate=16000)
    voice_frame = generate_tone_pcm(freq_hz=440.0, duration_ms=20.0, amplitude=0.1, sample_rate=16000)

    # 1. Silence frame -> is_speech = False
    res1 = vad.process_frame(silence_frame)
    assert res1.is_speech is False
    assert res1.rms == 0.0

    # 2. Voice frame -> is_speech = True, hangover set to 3
    res2 = vad.process_frame(voice_frame)
    assert res2.is_speech is True
    assert res2.rms >= 0.02

    # 3. Following 3 silence frames should maintain voice state due to hangover
    assert vad.process_frame(silence_frame).is_speech is True  # hangover: 2 left
    assert vad.process_frame(silence_frame).is_speech is True  # hangover: 1 left
    assert vad.process_frame(silence_frame).is_speech is True  # hangover: 0 left

    # 4. 4th silence frame drops back to False
    assert vad.process_frame(silence_frame).is_speech is False


def test_utterance_collector_ignores_short_transient_noise() -> None:
    vad = EnergyVad(threshold_rms=0.02, hangover_frames=0)
    # min_speech_ms=60ms -> requires 3 consecutive voice frames (20ms each)
    collector = UtteranceCollector(
        vad=vad,
        frame_ms=20.0,
        min_speech_ms=60.0,
        silence_timeout_ms=100.0,
    )

    silence_frame = generate_silence_pcm(duration_ms=20.0)
    voice_frame = generate_tone_pcm(freq_hz=440.0, duration_ms=20.0, amplitude=0.1)

    # 1 transient voice frame (click/pop)
    collector.process_frame(voice_frame)
    assert collector.is_in_utterance is False

    # Immediate silence
    seg, is_active = collector.process_frame(silence_frame)
    assert seg is None
    assert is_active is False
    assert collector.is_in_utterance is False


def test_energy_vad_hangover_does_not_confirm_a_new_utterance() -> None:
    vad = EnergyVad(threshold_rms=0.02, hangover_frames=6)
    collector = UtteranceCollector(
        vad=vad,
        frame_ms=20.0,
        min_speech_ms=160.0,
        silence_timeout_ms=100.0,
    )
    voice = generate_tone_pcm(freq_hz=440.0, duration_ms=20.0, amplitude=0.1)
    silence = generate_silence_pcm(duration_ms=20.0)

    collector.process_frame(voice)
    collector.process_frame(voice)
    for _ in range(6):
        collector.process_frame(silence)

    assert collector.is_in_utterance is False


def test_energy_vad_start_evidence_resets_across_a_real_gap() -> None:
    vad = EnergyVad(threshold_rms=0.02, hangover_frames=2)
    collector = UtteranceCollector(
        vad=vad,
        frame_ms=20.0,
        min_speech_ms=80.0,
        silence_timeout_ms=100.0,
    )
    voice = generate_tone_pcm(freq_hz=440.0, duration_ms=20.0, amplitude=0.1)
    silence = generate_silence_pcm(duration_ms=20.0)

    collector.process_frame(voice)
    collector.process_frame(voice)
    collector.process_frame(silence)
    collector.process_frame(voice)
    _segment, is_active = collector.process_frame(voice)

    assert is_active is False
    assert collector.is_in_utterance is False

    collector.process_frame(voice)
    _segment, is_active = collector.process_frame(voice)
    assert is_active is True


def test_utterance_collector_completes_utterance_on_silence_timeout() -> None:
    vad = EnergyVad(threshold_rms=0.02, hangover_frames=0)
    # min_speech=40ms (2 frames), silence_timeout=60ms (3 frames)
    collector = UtteranceCollector(
        vad=vad,
        frame_ms=20.0,
        min_speech_ms=40.0,
        silence_timeout_ms=60.0,
        pre_roll_ms=60.0,
    )

    silence = generate_silence_pcm(duration_ms=20.0)
    voice = generate_tone_pcm(freq_hz=440.0, duration_ms=20.0, amplitude=0.1)

    # 1. Feed silence (fills pre-roll)
    collector.process_frame(silence)
    collector.process_frame(silence)
    assert collector.is_in_utterance is False

    # 2. Feed 2 speech frames (meets min_speech_ms)
    collector.process_frame(voice)
    seg1, is_act1 = collector.process_frame(voice)
    assert seg1 is None
    assert is_act1 is True
    assert collector.is_in_utterance is True

    # 3. Feed 2 more voice frames
    collector.process_frame(voice)
    collector.process_frame(voice)

    # 4. Feed silence frames until silence_timeout (3 frames)
    collector.process_frame(silence)  # silence frame 1
    collector.process_frame(silence)  # silence frame 2
    final_seg, is_act_final = collector.process_frame(silence)  # silence frame 3 -> triggers completion

    assert final_seg is not None
    assert is_act_final is False
    assert collector.is_in_utterance is False
    assert final_seg.duration_ms > 100.0


def test_utterance_collector_maximum_utterance_limit() -> None:
    vad = EnergyVad(threshold_rms=0.02, hangover_frames=0)
    # max_utterance_seconds = 0.1s (5 frames max)
    collector = UtteranceCollector(
        vad=vad,
        frame_ms=20.0,
        min_speech_ms=20.0,
        silence_timeout_ms=100.0,
        max_utterance_seconds=0.1,
    )

    voice = generate_tone_pcm(freq_hz=440.0, duration_ms=20.0, amplitude=0.1)

    # Feed 5 consecutive voice frames
    seg = None
    for _ in range(5):
        seg, _ = collector.process_frame(voice)

    assert seg is not None
    assert collector.is_in_utterance is False


def test_webrtc_vad_applies_rms_floor_after_classifier(monkeypatch) -> None:
    from ailen.audio.vad import WebRtcVad

    vad = WebRtcVad(sample_rate=16000, frame_ms=20.0, mode=2, hangover_frames=0, min_rms=0.05)
    monkeypatch.setattr(vad._vad, "is_speech", lambda _frame, _rate: True)
    quiet = generate_tone_pcm(freq_hz=440.0, duration_ms=20.0, amplitude=0.02, sample_rate=16000)
    loud = generate_tone_pcm(freq_hz=440.0, duration_ms=20.0, amplitude=0.2, sample_rate=16000)

    assert vad.process_frame(quiet).is_trigger is False
    assert vad.process_frame(loud).is_trigger is True
