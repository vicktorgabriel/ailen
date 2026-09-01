"""Tests for explicit capture routing and bounded in-process level control."""

import json
import struct
from unittest.mock import MagicMock, patch

from ailen.audio.alsa_backend import AlsaAudioInputBackend, AlsaDeviceEnumerator
from ailen.audio.coordinator import AudioInteractionCoordinator
from ailen.audio.level import (
    AudioProcessorChain,
    CaptureLevelProcessor,
    build_capture_processor,
    resolve_capture_processing_mode,
)
from ailen.audio.pcm import compute_pcm_rms
from ailen.audio.vad import EnergyVad


def _pcm(value: int, samples: int = 320) -> bytes:
    return struct.pack(f"<{samples}h", *([value] * samples))


def _peak(frame: bytes) -> int:
    values = struct.unpack(f"<{len(frame) // 2}h", frame)
    return max(abs(value) for value in values)


def test_fixed_capture_gain_preserves_format_and_limits_s16le() -> None:
    processor = CaptureLevelProcessor(
        capture_gain_db=6.0,
        auto_gain_enabled=False,
        limiter_peak=0.9,
    )

    quiet = _pcm(4000)
    boosted = processor.process(quiet)
    loud = processor.process(_pcm(30000))

    assert len(boosted) == len(quiet)
    assert _peak(boosted) > _peak(quiet)
    assert _peak(loud) <= round(32767 * 0.9)
    assert processor.metrics.clipping_ratio > 0.0
    assert processor.metrics.applied_gain_db == 6.0


def test_auto_gain_is_bounded_and_smoothed_between_frames() -> None:
    processor = CaptureLevelProcessor(
        auto_gain_enabled=True,
        target_rms=0.15,
        max_auto_gain_db=12.0,
        attack_ms=100.0,
        release_ms=400.0,
        frame_ms=20.0,
    )

    processor.process(_pcm(330))
    first_gain = processor.metrics.auto_gain_db
    processor.process(_pcm(330))
    second_gain = processor.metrics.auto_gain_db

    assert 0.0 < first_gain < second_gain <= 12.0
    assert processor.metrics.output_rms > processor.metrics.input_rms


def test_auto_gain_does_not_raise_noise_below_default_gate_or_trigger_vad() -> None:
    """Removing the AGC noise gate must amplify this floor into false speech."""

    processor = CaptureLevelProcessor(
        auto_gain_enabled=True,
        target_rms=0.12,
        max_auto_gain_db=18.0,
        attack_ms=100.0,
        release_ms=400.0,
        frame_ms=20.0,
    )
    vad = EnergyVad(threshold_rms=0.006, hangover_frames=0)
    quiet_noise = _pcm(100)

    triggers = [vad.process_frame(processor.process(quiet_noise)).is_speech for _ in range(100)]

    assert processor.metrics.auto_gain_db == 0.0
    assert processor.metrics.output_rms == processor.metrics.input_rms
    assert not any(triggers)


def test_auto_gain_gate_holds_short_pause_then_decays_without_pumping() -> None:
    """Removing hold/decay must either pump pauses or retain stale gain forever."""

    processor = CaptureLevelProcessor(
        auto_gain_enabled=True,
        target_rms=0.15,
        max_auto_gain_db=18.0,
        attack_ms=100.0,
        release_ms=200.0,
        frame_ms=20.0,
        noise_gate_rms=0.01,
        gate_hold_ms=40.0,
    )
    processor.process(_pcm(1000))
    speech_gain = processor.metrics.auto_gain_db

    processor.process(_pcm(100))
    processor.process(_pcm(100))
    held_gain = processor.metrics.auto_gain_db
    processor.process(_pcm(100))
    decayed_gain = processor.metrics.auto_gain_db

    assert speech_gain > 0.0
    assert held_gain == speech_gain
    assert 0.0 <= decayed_gain < held_gain


def test_auto_gain_reduces_an_already_strong_signal_instead_of_boosting_it() -> None:
    processor = CaptureLevelProcessor(
        auto_gain_enabled=True,
        target_rms=0.12,
        max_auto_gain_db=18.0,
        attack_ms=100.0,
        release_ms=100.0,
        frame_ms=20.0,
        limiter_peak=0.98,
    )
    strong = _pcm(18000)

    output = strong
    for _ in range(10):
        output = processor.process(strong)

    assert processor.metrics.auto_gain_db < 0.0
    assert compute_pcm_rms(output) < compute_pcm_rms(strong)
    assert processor.metrics.clipping_ratio == 0.0


def test_coordinator_records_raw_then_every_dsp_stage_and_final_clean_rms() -> None:
    """Moving raw observation after DSP must make the raw metric incorrect."""

    class SilenceProcessor:
        def process(self, frame: bytes) -> bytes:
            return bytes(len(frame))

        def reset(self) -> None:
            return None

    raw = _pcm(500)
    coordinator = AudioInteractionCoordinator(
        frame_processor=AudioProcessorChain(
            [
                CaptureLevelProcessor(capture_gain_db=6.0),
                SilenceProcessor(),
            ]
        )
    )

    coordinator.process_frame(raw)

    assert coordinator._rms_samples["mic_raw"][0] == compute_pcm_rms(raw)
    assert coordinator._rms_samples["mic_after_CaptureLevelProcessor"][0] > compute_pcm_rms(raw)
    assert coordinator._rms_samples["mic_after_SilenceProcessor"][0] == 0.0
    assert coordinator._rms_samples["mic_clean"][0] == 0.0


def test_processor_chain_preserves_order_and_reset() -> None:
    calls: list[str] = []

    class Processor:
        def __init__(self, name: str) -> None:
            self.name = name

        def process(self, frame: bytes) -> bytes:
            calls.append(self.name)
            return frame + self.name.encode()

        def reset(self) -> None:
            calls.append(f"reset:{self.name}")

    chain = AudioProcessorChain([Processor("gain"), Processor("noise")])
    assert chain.process(b"x") == b"xgainnoise"
    chain.reset()
    assert calls == ["gain", "noise", "reset:gain", "reset:noise"]


def _build_chain_for_mode(mode: str, device: str) -> AudioProcessorChain:
    return build_capture_processor(
        sample_rate=16000,
        channels=1,
        frame_ms=20.0,
        capture_gain_db=9.0,
        auto_gain_enabled=True,
        auto_gain_target_rms=0.12,
        max_auto_gain_db=18.0,
        auto_gain_attack_ms=120.0,
        auto_gain_release_ms=600.0,
        auto_gain_noise_gate_rms=0.008,
        auto_gain_gate_hold_ms=300.0,
        capture_limiter_peak=0.98,
        noise_suppression_engine="webrtc",
        noise_suppression_level=2,
        input_processing_mode=mode,
        input_device=device,
    )


def test_full_capture_chain_suppresses_noise_before_level_control() -> None:
    noise = MagicMock()
    noise.process.side_effect = lambda frame: frame
    noise.reset.return_value = None
    with patch("ailen.audio.noise.WebRtcNoiseProcessor", return_value=noise):
        chain = _build_chain_for_mode("auto", "pipewire:alsa_input.usb-test")

    assert chain.processors[0] is noise
    assert isinstance(chain.processors[1], CaptureLevelProcessor)


def test_easyeffects_source_does_not_receive_ailen_gain_or_agc_twice() -> None:
    with patch("ailen.audio.noise.WebRtcNoiseProcessor") as noise:
        chain = _build_chain_for_mode("auto", "pipewire:easyeffects_source")

    assert chain.processors == ()
    noise.assert_not_called()


def test_auto_mode_uses_observed_default_route_to_detect_external_dsp() -> None:
    assert (
        resolve_capture_processing_mode(
            "auto",
            input_device="default",
            effective_source="pipewire:easyeffects_source",
        )
        == "easyeffects"
    )


def test_raw_processing_mode_bypasses_internal_capture_dsp() -> None:
    with patch("ailen.audio.noise.WebRtcNoiseProcessor") as noise:
        chain = _build_chain_for_mode("raw", "pipewire:alsa_input.usb-test")

    assert chain.processors == ()
    noise.assert_not_called()


def test_noise_only_profile_does_not_apply_preamp_agc_or_limiter() -> None:
    noise = MagicMock()
    noise.process.side_effect = lambda frame: frame
    noise.reset.return_value = None
    with patch("ailen.audio.noise.WebRtcNoiseProcessor", return_value=noise):
        chain = build_capture_processor(
            sample_rate=16000,
            channels=1,
            frame_ms=20.0,
            capture_gain_db=12.0,
            auto_gain_enabled=True,
            auto_gain_target_rms=0.12,
            max_auto_gain_db=18.0,
            auto_gain_attack_ms=120.0,
            auto_gain_release_ms=600.0,
            auto_gain_noise_gate_rms=0.008,
            auto_gain_gate_hold_ms=300.0,
            capture_limiter_peak=0.98,
            noise_suppression_engine="webrtc",
            noise_suppression_level=2,
            processing_profile="noise_only",
        )

    assert chain.processors == (noise,)


def test_pipewire_sources_have_stable_explicit_ids_and_level_metadata() -> None:
    document = [
        {
            "name": "alsa_input.usb-test.mono-fallback",
            "description": "Test USB Mono",
            "state": "SUSPENDED",
            "volume": {"mono": {"value_percent": "100%", "db": "0.00 dB"}},
        },
        {
            "name": "easyeffects_source",
            "description": "Easy Effects Source",
            "state": "IDLE",
            "volume": {
                "front-left": {"value_percent": "42%", "db": "-22.87 dB"},
                "front-right": {"value_percent": "42%", "db": "-22.87 dB"},
            },
        },
    ]
    completed = MagicMock(returncode=0, stdout=json.dumps(document))
    with (
        patch("ailen.audio.alsa_backend.shutil.which", return_value="/usr/bin/pactl"),
        patch("ailen.audio.alsa_backend.subprocess.run", return_value=completed),
    ):
        devices = AlsaDeviceEnumerator().list_pipewire_devices(is_input=True)

    easy = next(item for item in devices if item.id == "pipewire:easyeffects_source")
    assert easy.name == "Easy Effects Source"
    assert easy.volume_percent == 42.0
    assert easy.volume_db == -22.87
    assert easy.state == "IDLE"


def test_explicit_pipewire_source_is_passed_to_pw_record_target() -> None:
    process = MagicMock()
    process.poll.return_value = None
    process.stdout = MagicMock()
    process.stderr = MagicMock()
    with (
        patch("ailen.audio.alsa_backend.shutil.which", return_value="/usr/bin/pw-record"),
        patch("ailen.audio.alsa_backend.subprocess.Popen", return_value=process) as popen,
        patch("ailen.audio.alsa_backend.time.sleep"),
    ):
        backend = AlsaAudioInputBackend(device="pipewire:easyeffects_source")
        backend.start()

    command = popen.call_args.args[0]
    assert command[command.index("--target") + 1] == "easyeffects_source"
    assert backend.effective_device == "pipewire:easyeffects_source"
