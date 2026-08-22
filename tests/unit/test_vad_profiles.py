"""Unit tests for VAD profiles and timing configurations."""

from ailen.audio.vad import UtteranceCollector, VadProfile, get_vad_profile_timings


def test_vad_profile_timings() -> None:
    sil_fast, min_fast, pre_fast = get_vad_profile_timings(VadProfile.FAST)
    assert sil_fast == 350.0
    assert min_fast == 150.0
    assert pre_fast == 150.0

    sil_norm, min_norm, pre_norm = get_vad_profile_timings(VadProfile.NORMAL)
    assert sil_norm == 500.0
    assert min_norm == 200.0
    assert pre_norm == 200.0

    sil_cons, min_cons, pre_cons = get_vad_profile_timings(VadProfile.CONSERVATIVE)
    assert sil_cons == 700.0
    assert min_cons == 250.0
    assert pre_cons == 200.0


def test_utterance_collector_with_profile() -> None:
    collector = UtteranceCollector(profile=VadProfile.FAST)
    assert collector.silence_timeout_ms == 350.0
    assert collector.min_speech_ms == 150.0

    collector_cons = UtteranceCollector(profile="conservative")
    assert collector_cons.silence_timeout_ms == 700.0
    assert collector_cons.min_speech_ms == 250.0
