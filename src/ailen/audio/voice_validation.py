"""Guided, RAM-only physical VAD/STT validation for AILEN Lab.

This module deliberately stores recognized text and scalar measurements only.
Captured PCM is handed directly to STT, then references are released; it is
never written to an artifact or event payload.
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from ailen.audio.calibration import recommend_auto_gain_gate_rms
from ailen.audio.contracts import (
    AudioDevice,
    AudioFrameProcessor,
    AudioInputBackend,
    SttBackend,
)
from ailen.audio.level import (
    AudioProcessorChain,
    CaptureLevelProcessor,
    pcm_s16le_levels,
    resolve_effective_capture_source,
)
from ailen.audio.pcm import compute_pcm_rms
from ailen.audio.stt_benchmark import normalize_text_es, word_error_rate
from ailen.audio.stt_quality import SttQualityEvaluator
from ailen.audio.vad import UtteranceCollector
from ailen.core.events import EventBus
from ailen.domain.enums import EventType, ServiceStatus
from ailen.domain.models import CoreEvent

BARGE_IN_PLAYBACK_TEXT = (
    "Esta es una respuesta deliberadamente larga para medir una interrupción real. "
    "Voy a seguir hablando durante varias oraciones, con un ritmo natural y sin apurarme. "
    "Cuando veas la indicación en la terminal, decí la frase objetivo completa. "
    "El objetivo es comprobar que el audio se detenga, que tus primeras palabras no se pierdan "
    "y que Vosk entregue la nueva transcripción."
)


class _BargeInCoordinator(Protocol):
    event_bus: EventBus | None

    def speak(self, text: str, *, turn_id: str) -> Any:
        """Speak one controlled test response."""
        ...

    def cancel_active_speech(self, *, reason: str) -> bool:
        """Cancel active playback/logical speech."""
        ...


@dataclass(frozen=True)
class VoiceValidationCase:
    """Expected public phrase and operator instruction."""

    case_id: str
    expected_text: str
    instruction: str


@dataclass(frozen=True)
class BargeInValidationCase:
    """One guided interruption phase using only public synthetic text."""

    phase: str
    expected_text: str
    cue_delay_seconds: float


@dataclass
class VoiceSampleResult:
    """Persistable sample result; intentionally has no PCM field."""

    case_id: str
    expected_text: str
    recognized_text: str
    device: str
    vad_mode: int
    silence_timeout_ms: int
    status: str
    processing_profile: str = "configured"
    engine: str = "unknown"
    confidence: float | None = None
    confidence_band: str = "unknown"
    wer: float | None = None
    cer: float | None = None
    frame_count: int = 0
    pcm_duration_ms: float = 0.0
    vad_onset_ms: float | None = None
    vad_offset_ms: float | None = None
    capture_elapsed_ms: float = 0.0
    stt_latency_ms: float | None = None
    truncated: bool = False
    noise_rms_p50: float | None = None
    effective_source: str = ""
    distance_cm: int | None = None
    capture_gain_db: float = 0.0
    auto_gain_enabled: bool = False
    raw_noise_rms: float | None = None
    recommended_auto_gain_gate_rms: float | None = None
    gained_noise_rms: float | None = None
    processed_noise_rms: float | None = None
    raw_noise_peak: float | None = None
    gained_noise_peak: float | None = None
    processed_noise_peak: float | None = None
    raw_voice_rms: float | None = None
    gained_voice_rms: float | None = None
    processed_voice_rms: float | None = None
    raw_voice_peak: float | None = None
    gained_voice_peak: float | None = None
    processed_voice_peak: float | None = None
    snr_raw_db: float | None = None
    snr_gained_db: float | None = None
    snr_processed_db: float | None = None
    clipping_ratio: float = 0.0
    applied_gain_db: float = 0.0
    silence_false_trigger_frames: int = 0
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        for key, value in tuple(raw.items()):
            if isinstance(value, float):
                raw[key] = round(value, 4)
        return raw


@dataclass
class BargeInTrialResult:
    """Persistable physical interruption result; never contains PCM."""

    phase: str
    expected_text: str
    recognized_text: str
    status: str
    engine: str = "unknown"
    confidence: float | None = None
    wer: float | None = None
    cer: float | None = None
    interruption_detected: bool = False
    playback_stop_ms: float | None = None
    buffered_frames: int = 0
    frames_preserved: bool = False
    transcript_interrupted: bool = False
    generation_cancelled: bool = False
    synthesizer_draining_at_stop: bool = False
    synthesis_drain_observed: bool = False
    synthesis_drain_stale: bool | None = None
    speech_finished_interrupted: bool = False
    speech_thread_alive: bool = False
    no_aec: bool = True

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        for key, value in tuple(raw.items()):
            if isinstance(value, float):
                raw[key] = round(value, 4)
        return raw


def default_voice_validation_cases() -> list[VoiceValidationCase]:
    """Return the fixed public corpus used to compare VAD configurations."""
    return [
        VoiceValidationCase("short_greeting", "hola AILÉN", "voz normal"),
        VoiceValidationCase("short_casual", "todo bien", "voz normal"),
        VoiceValidationCase(
            "daily_comment",
            "recién terminé de comer",
            "voz normal y ritmo cotidiano",
        ),
        VoiceValidationCase(
            "long_sentence",
            "mañana quiero ordenar algunas cosas antes de salir temprano",
            "frase larga, sin apurarte",
        ),
        VoiceValidationCase(
            "internal_pause_one",
            "estaba pensando que podríamos probarlo de nuevo",
            "hacé una pausa natural después de 'pensando'",
        ),
        VoiceValidationCase(
            "internal_pause_two",
            "si termina de llover salgo a caminar un rato",
            "hacé una pausa natural después de 'llover'",
        ),
        VoiceValidationCase(
            "quiet_voice",
            "te estoy hablando un poco más bajo",
            "voz algo baja o a mayor distancia, pero inteligible",
        ),
        VoiceValidationCase("yes", "sí", "respuesta corta normal"),
        VoiceValidationCase("no", "no", "respuesta corta normal"),
        VoiceValidationCase(
            "volume_command",
            "subí el volumen al treinta por ciento",
            "comando claro, sin ejecutarlo en este harness",
        ),
        VoiceValidationCase(
            "joke_request",
            "contame un chiste corto",
            "pedido conversacional natural",
        ),
        VoiceValidationCase(
            "temporal_concept",
            "hoy está bastante fresco pero no quiero buscar el clima",
            "comentario cotidiano, ritmo natural",
        ),
    ]


def default_barge_in_validation_cases() -> list[BargeInValidationCase]:
    """Return early/middle/late physical trials over the same audio pipeline."""
    return [
        BargeInValidationCase("early", "pará un momento", 0.15),
        BargeInValidationCase("middle", "cambiemos de tema", 2.0),
        BargeInValidationCase("late", "ahora escuchame a mí", 4.5),
    ]


def select_voice_calibration_devices(
    *,
    explicit_devices: list[str],
    configured_device: str,
    pipewire_sources: list[AudioDevice],
    max_devices: int = 12,
) -> list[str]:
    """Choose bounded capture routes; explicit operator routes always win."""

    explicit = list(
        dict.fromkeys(device.strip() for device in explicit_devices if device.strip())
    )
    if explicit:
        return explicit
    if max_devices < 1:
        raise ValueError("max_devices must be positive")

    selected: list[str] = []

    def add(device: str) -> None:
        normalized = device.strip()
        if normalized and normalized not in selected and len(selected) < max_devices:
            selected.append(normalized)

    # Exercise the route an unconfigured installation would actually call.
    # The currently observed default PipeWire node is metadata for that route,
    # not a second physical source to capture again.
    add("default")
    default_equivalents = {"default", "auto", "pipewire"}
    default_equivalents.update(
        source.id.strip() for source in pipewire_sources if source.is_default
    )
    if configured_device not in default_equivalents:
        add(configured_device)

    for source in pipewire_sources:
        route = source.id.strip()
        route_name = route.removeprefix("pipewire:").casefold()
        is_physical = route_name.startswith("alsa_input.")
        is_lab_dsp = "easyeffects_source" in route_name
        if source.is_monitor or source.is_default:
            continue
        if not (is_physical or is_lab_dsp):
            continue
        add(route)
    return selected


def recommend_voice_configuration(
    results: list[VoiceSampleResult],
) -> dict[str, Any] | None:
    """Rank observed configurations without persisting a config change."""
    groups: dict[
        tuple[str, int, int, float, bool, str], list[VoiceSampleResult]
    ] = defaultdict(list)
    for result in results:
        if result.status == "skipped":
            continue
        groups[
            (
                result.device,
                result.vad_mode,
                result.silence_timeout_ms,
                result.capture_gain_db,
                result.auto_gain_enabled,
                result.processing_profile,
            )
        ].append(result)
    if not groups:
        return None

    ranked: list[
        tuple[
            float,
            int,
            tuple[str, int, int, float, bool, str],
            list[VoiceSampleResult],
        ]
    ] = []
    for key, samples in groups.items():
        wers = [sample.wer if sample.wer is not None else 1.0 for sample in samples]
        cers = [sample.cer if sample.cer is not None else 1.0 for sample in samples]
        failures = sum(sample.status != "ok" for sample in samples)
        truncations = sum(sample.truncated for sample in samples)
        clipping = sum(min(1.0, sample.clipping_ratio * 20.0) for sample in samples)
        false_triggers = sum(sample.silence_false_trigger_frames for sample in samples)
        weak_snr = sum(
            max(0.0, (10.0 - sample.snr_processed_db) / 10.0)
            for sample in samples
            if sample.snr_processed_db is not None
        )
        score = (
            (sum(wers) / len(wers))
            + (sum(cers) / len(cers))
            + failures
            + truncations
            + clipping
            + false_triggers * 0.1
            + weak_snr
        )
        ranked.append((score, -len(samples), key, samples))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    score, _negative_count, key, samples = ranked[0]
    (
        device,
        vad_mode,
        silence_timeout_ms,
        capture_gain_db,
        auto_gain_enabled,
        processing_profile,
    ) = key
    gate = _median(
        [
            sample.recommended_auto_gain_gate_rms
            for sample in samples
            if sample.recommended_auto_gain_gate_rms is not None
        ]
    )
    return {
        "device": device,
        "vad_mode": vad_mode,
        "silence_timeout_ms": silence_timeout_ms,
        "capture_gain_db": capture_gain_db,
        "auto_gain_enabled": auto_gain_enabled,
        "processing_profile": processing_profile,
        "auto_gain_noise_gate_rms": round(gate, 6) if gate is not None else None,
        "samples": len(samples),
        "score": round(score, 4),
        "wer_avg": round(
            sum(sample.wer if sample.wer is not None else 1.0 for sample in samples)
            / len(samples),
            4,
        ),
        "cer_avg": round(
            sum(sample.cer if sample.cer is not None else 1.0 for sample in samples)
            / len(samples),
            4,
        ),
        "empty_or_failed": sum(sample.status != "ok" for sample in samples),
        "truncated": sum(sample.truncated for sample in samples),
        "clipping_ratio_avg": round(
            sum(sample.clipping_ratio for sample in samples) / len(samples), 6
        ),
        "silence_false_trigger_frames": sum(
            sample.silence_false_trigger_frames for sample in samples
        ),
        "snr_processed_db_avg": (
            round(
                sum(
                    sample.snr_processed_db
                    for sample in samples
                    if sample.snr_processed_db is not None
                )
                / sum(sample.snr_processed_db is not None for sample in samples),
                3,
            )
            if any(sample.snr_processed_db is not None for sample in samples)
            else None
        ),
        "requires_human_confirmation": True,
    }


def _edit_distance(reference: str, hypothesis: str) -> int:
    previous = list(range(len(hypothesis) + 1))
    for row, ref_char in enumerate(reference, start=1):
        current = [row]
        for column, hyp_char in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (ref_char != hyp_char),
                )
            )
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Return normalized Spanish character error rate, excluding spaces."""
    ref = normalize_text_es(reference).replace(" ", "")
    hyp = normalize_text_es(hypothesis).replace(" ", "")
    if not ref:
        return 0.0 if not hyp else 1.0
    return _edit_distance(ref, hyp) / len(ref)


def summarize_barge_in_trial(
    *,
    phase: str,
    expected_text: str,
    interruption: dict[str, Any] | None,
    transcript: dict[str, Any] | None,
    synthesis_drained: dict[str, Any] | None,
    speech_finished: dict[str, Any] | None,
    speech_thread_alive: bool,
) -> BargeInTrialResult:
    """Classify one trial from redacted Core events, not playback assumptions."""
    interrupted_payload = interruption or {}
    transcript_payload = transcript or {}
    recognized = str(transcript_payload.get("text", "") or "").strip()
    buffered_frames_raw = interrupted_payload.get("buffered_frames", 0)
    buffered_frames = (
        int(buffered_frames_raw)
        if isinstance(buffered_frames_raw, (int, float))
        else 0
    )
    transcript_interrupted = bool(transcript_payload.get("interrupted", False))
    frames_preserved = bool(buffered_frames > 0 and transcript_interrupted)
    wer = word_error_rate(expected_text, recognized).wer if recognized else None
    cer = character_error_rate(expected_text, recognized) if recognized else None

    if speech_thread_alive:
        status = "speech_thread_stuck"
    elif not interruption:
        status = "barge_in_not_detected"
    elif not transcript:
        status = "transcript_missing"
    elif not transcript_interrupted:
        status = "transcript_not_linked_to_interruption"
    elif buffered_frames <= 0:
        status = "frames_not_preserved"
    elif not recognized:
        status = "empty_transcript"
    elif wer is not None and wer > 0.5:
        status = "transcript_mismatch"
    else:
        status = "passed"

    confidence_raw = transcript_payload.get("confidence")
    playback_stop_raw = interrupted_payload.get("playback_stop_ms")
    return BargeInTrialResult(
        phase=phase,
        expected_text=expected_text,
        recognized_text=recognized,
        status=status,
        engine=str(transcript_payload.get("engine", "unknown") or "unknown"),
        confidence=(
            float(confidence_raw)
            if isinstance(confidence_raw, (int, float))
            else None
        ),
        wer=wer,
        cer=cer,
        interruption_detected=bool(interruption),
        playback_stop_ms=(
            float(playback_stop_raw)
            if isinstance(playback_stop_raw, (int, float))
            else None
        ),
        buffered_frames=buffered_frames,
        frames_preserved=frames_preserved,
        transcript_interrupted=transcript_interrupted,
        generation_cancelled=bool(
            interrupted_payload.get("logical_generation_cancelled", False)
        ),
        synthesizer_draining_at_stop=bool(
            interrupted_payload.get("synthesizer_draining", False)
        ),
        synthesis_drain_observed=bool(synthesis_drained),
        synthesis_drain_stale=(
            bool(synthesis_drained.get("stale")) if synthesis_drained else None
        ),
        speech_finished_interrupted=bool(
            (speech_finished or {}).get("interrupted", False)
        ),
        speech_thread_alive=speech_thread_alive,
    )


def run_physical_barge_in_trial(
    *,
    coordinator: _BargeInCoordinator,
    phase: str,
    expected_text: str,
    cue_delay_seconds: float,
    timeout_seconds: float,
    turn_id: str,
    on_cue: Callable[[str, str], None],
    playback_text: str = BARGE_IN_PLAYBACK_TEXT,
) -> BargeInTrialResult:
    """Run one real coordinator trial and wait for the preserved STT result."""
    event_bus = coordinator.event_bus
    if event_bus is None:
        raise ValueError("barge-in validation requires the coordinator EventBus")

    started_event = threading.Event()
    transcript_event = threading.Event()
    finished_event = threading.Event()
    drained_event = threading.Event()
    observed: dict[str, dict[str, Any]] = {}
    observed_lock = threading.Lock()

    def observe(event: CoreEvent) -> None:
        payload = event.payload
        event_turn_id = str(payload.get("turn_id", "") or "")
        if event.event_type is EventType.TRANSCRIPT_READY:
            if not started_event.is_set() or not bool(payload.get("interrupted", False)):
                return
            with observed_lock:
                observed["transcript"] = dict(payload)
            transcript_event.set()
            return
        if event_turn_id != turn_id:
            return
        if event.event_type is EventType.SPEECH_STARTED:
            started_event.set()
        elif event.event_type is EventType.SPEECH_INTERRUPTED:
            with observed_lock:
                observed["interruption"] = dict(payload)
        elif event.event_type is EventType.SPEECH_FINISHED:
            with observed_lock:
                observed["speech_finished"] = dict(payload)
            finished_event.set()
        elif event.event_type is EventType.SPEECH_SYNTHESIS_DRAINED:
            with observed_lock:
                observed["synthesis_drained"] = dict(payload)
            drained_event.set()

    unsubscribe = event_bus.subscribe(None, observe)
    speech_thread = threading.Thread(
        target=coordinator.speak,
        args=(playback_text,),
        kwargs={"turn_id": turn_id},
        name=f"ailen-barge-validation-{phase}",
        daemon=True,
    )
    try:
        speech_thread.start()
        bounded_timeout = max(1.0, timeout_seconds)
        if not started_event.wait(timeout=min(15.0, bounded_timeout)):
            coordinator.cancel_active_speech(reason="validation_no_playback")
            speech_thread.join(timeout=0.5)
            return BargeInTrialResult(
                phase=phase,
                expected_text=expected_text,
                recognized_text="",
                status="playback_not_started",
                speech_thread_alive=speech_thread.is_alive(),
            )

        cue_deadline = time.monotonic() + max(0.0, cue_delay_seconds)
        while time.monotonic() < cue_deadline and not finished_event.is_set():
            time.sleep(min(0.05, cue_deadline - time.monotonic()))
        if finished_event.is_set():
            return BargeInTrialResult(
                phase=phase,
                expected_text=expected_text,
                recognized_text="",
                status="playback_ended_before_cue",
                speech_thread_alive=speech_thread.is_alive(),
            )

        on_cue(phase, expected_text)
        transcript_event.wait(timeout=bounded_timeout)
        speech_thread.join(timeout=0.75)
        if speech_thread.is_alive():
            coordinator.cancel_active_speech(reason="validation_timeout")
            speech_thread.join(timeout=0.5)

        with observed_lock:
            interruption = observed.get("interruption")
        if interruption and bool(interruption.get("synthesizer_draining", False)):
            drained_event.wait(timeout=min(2.0, bounded_timeout))

        with observed_lock:
            return summarize_barge_in_trial(
                phase=phase,
                expected_text=expected_text,
                interruption=observed.get("interruption"),
                transcript=observed.get("transcript"),
                synthesis_drained=observed.get("synthesis_drained"),
                speech_finished=observed.get("speech_finished"),
                speech_thread_alive=speech_thread.is_alive(),
            )
    finally:
        unsubscribe()


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _snr_db(voice_rms: float | None, noise_rms: float | None) -> float | None:
    if voice_rms is None or noise_rms is None or voice_rms <= 0.0:
        return None
    return 20.0 * math.log10(voice_rms / max(noise_rms, 1e-6))


def format_voice_sample_result(result: VoiceSampleResult) -> str:
    """Render complete scalar capture stages for an operator; never includes PCM."""

    return " ".join(
        (
            f"status={result.status}",
            f"profile={result.processing_profile}",
            f"source={result.effective_source or result.device}",
            f"text={result.recognized_text!r}",
            f"confidence={result.confidence}",
            f"wer={result.wer}",
            f"cer={result.cer}",
            (
                "noise_rms(raw/gained/processed)="
                f"{result.raw_noise_rms}/{result.gained_noise_rms}/"
                f"{result.processed_noise_rms}"
            ),
            (
                "voice_rms(raw/gained/processed)="
                f"{result.raw_voice_rms}/{result.gained_voice_rms}/"
                f"{result.processed_voice_rms}"
            ),
            (
                "noise_peak(raw/gained/processed)="
                f"{result.raw_noise_peak}/{result.gained_noise_peak}/"
                f"{result.processed_noise_peak}"
            ),
            (
                "voice_peak(raw/gained/processed)="
                f"{result.raw_voice_peak}/{result.gained_voice_peak}/"
                f"{result.processed_voice_peak}"
            ),
            (
                "snr_db(raw/gained/processed)="
                f"{result.snr_raw_db}/{result.snr_gained_db}/"
                f"{result.snr_processed_db}"
            ),
            f"clipping_ratio={result.clipping_ratio}",
            f"applied_gain_db={result.applied_gain_db}",
            f"false_vad={result.silence_false_trigger_frames}",
        )
    )


def _process_capture_frame(
    frame: bytes,
    processor: AudioFrameProcessor | None,
) -> tuple[bytes, dict[str, tuple[float, float]], float, float]:
    stages: list[tuple[str, bytes]]
    level: CaptureLevelProcessor | None = None
    if isinstance(processor, AudioProcessorChain):
        stages = processor.process_with_stages(frame)
        level = next(
            (
                item
                for item in processor.processors
                if isinstance(item, CaptureLevelProcessor)
            ),
            None,
        )
    elif processor is not None:
        stages = [("raw", frame), (type(processor).__name__, processor.process(frame))]
        if isinstance(processor, CaptureLevelProcessor):
            level = processor
    else:
        stages = [("raw", frame)]
    stage_levels = {name: pcm_s16le_levels(data) for name, data in stages}
    output = stages[-1][1]
    clipping = level.metrics.clipping_ratio if level is not None else 0.0
    gain = level.metrics.applied_gain_db if level is not None else 0.0
    return output, stage_levels, clipping, gain


def capture_voice_sample(
    *,
    case: VoiceValidationCase,
    device: str,
    vad_mode: int,
    silence_timeout_ms: int,
    audio_input: AudioInputBackend,
    collector: UtteranceCollector,
    stt: SttBackend,
    quality: SttQualityEvaluator,
    frame_processor: AudioFrameProcessor | None = None,
    max_wait_seconds: float = 18.0,
    silence_seconds: float = 0.0,
    distance_cm: int | None = None,
    on_speech_ready: Callable[[], None] | None = None,
    capture_gain_db: float = 0.0,
    auto_gain_enabled: bool = False,
    processing_profile: str = "configured",
    effective_source_hint: str = "",
) -> VoiceSampleResult:
    """Capture one finalized utterance in RAM and immediately transcribe it."""
    started = time.monotonic()
    onset_ms: float | None = None
    offset_ms: float | None = None
    idle_rms: list[float] = []
    noise_stages: dict[str, list[float]] = defaultdict(list)
    noise_peaks: dict[str, list[float]] = defaultdict(list)
    voice_stages: dict[str, list[float]] = defaultdict(list)
    voice_peaks: dict[str, list[float]] = defaultdict(list)
    clipping_ratios: list[float] = []
    applied_gains: list[float] = []
    silence_false_trigger_frames = 0
    segment = None
    try:
        audio_input.start()
        health = audio_input.health()
        if health.status is not ServiceStatus.HEALTHY:
            return VoiceSampleResult(
                case_id=case.case_id,
                expected_text=case.expected_text,
                recognized_text="",
                device=device,
                vad_mode=vad_mode,
                silence_timeout_ms=silence_timeout_ms,
                status="input_unavailable",
                processing_profile=processing_profile,
                detail=health.detail,
            )

        effective_source = resolve_effective_capture_source(
            str(getattr(audio_input, "effective_device", device) or device),
            effective_source_hint,
        )
        silence_frames = max(0, round(silence_seconds * 1000.0 / collector.frame_ms))
        silence_attempts = 0
        silence_collected = 0
        while silence_collected < silence_frames:
            if silence_attempts >= max(silence_frames * 3, silence_frames + 1):
                break
            silence_attempts += 1
            raw_frame = audio_input.read_frame(timeout_seconds=0.1)
            if raw_frame is None:
                continue
            silence_collected += 1
            processed_frame, stage_levels, clipping, gain = _process_capture_frame(
                raw_frame, frame_processor
            )
            for stage_name, (rms, peak) in stage_levels.items():
                noise_stages[stage_name].append(rms)
                noise_peaks[stage_name].append(peak)
            clipping_ratios.append(clipping)
            applied_gains.append(gain)
            if collector.vad.process_frame(processed_frame).is_speech:
                silence_false_trigger_frames += 1
        collector.reset()
        if on_speech_ready is not None:
            on_speech_ready()

        deadline = time.monotonic() + max(0.01, max_wait_seconds)
        while time.monotonic() < deadline:
            raw_frame = audio_input.read_frame(timeout_seconds=0.1)
            if raw_frame is None:
                time.sleep(0.002)
                continue
            frame, stage_levels, clipping, gain = _process_capture_frame(
                raw_frame, frame_processor
            )
            was_active = collector.is_in_utterance
            completed, _active = collector.process_frame(frame)
            if not was_active and collector.is_in_utterance and onset_ms is None:
                onset_ms = (time.monotonic() - started) * 1000.0
            if onset_ms is None:
                idle_rms.append(compute_pcm_rms(frame))
            if collector.is_in_utterance or was_active:
                for stage_name, (rms, peak) in stage_levels.items():
                    voice_stages[stage_name].append(rms)
                    voice_peaks[stage_name].append(peak)
                clipping_ratios.append(clipping)
                applied_gains.append(gain)
            if completed is not None:
                segment = completed
                offset_ms = (time.monotonic() - started) * 1000.0
                break

        if segment is None:
            last_noise_stage = next(reversed(noise_stages), "raw")
            gained_stage = "CaptureLevelProcessor"
            return VoiceSampleResult(
                case_id=case.case_id,
                expected_text=case.expected_text,
                recognized_text="",
                device=device,
                vad_mode=vad_mode,
                silence_timeout_ms=silence_timeout_ms,
                status="timeout",
                processing_profile=processing_profile,
                vad_onset_ms=onset_ms,
                capture_elapsed_ms=(time.monotonic() - started) * 1000.0,
                noise_rms_p50=_median(idle_rms),
                detail="No finalized utterance before the bounded capture deadline",
                effective_source=effective_source,
                distance_cm=distance_cm,
                capture_gain_db=capture_gain_db,
                auto_gain_enabled=auto_gain_enabled,
                raw_noise_rms=_median(noise_stages.get("raw", [])),
                recommended_auto_gain_gate_rms=recommend_auto_gain_gate_rms(
                    noise_stages.get("raw", [])
                ),
                gained_noise_rms=_median(noise_stages.get(gained_stage, [])),
                processed_noise_rms=_median(noise_stages.get(last_noise_stage, [])),
                raw_noise_peak=max(noise_peaks.get("raw", []), default=0.0),
                gained_noise_peak=max(
                    noise_peaks.get(gained_stage, []), default=0.0
                ),
                processed_noise_peak=max(
                    noise_peaks.get(last_noise_stage, []), default=0.0
                ),
                clipping_ratio=(
                    sum(clipping_ratios) / len(clipping_ratios)
                    if clipping_ratios
                    else 0.0
                ),
                applied_gain_db=_median(applied_gains) or 0.0,
                silence_false_trigger_frames=silence_false_trigger_frames,
            )

        transcript = stt.transcribe(segment)
        assessment = quality.evaluate(
            transcript.text,
            confidence=transcript.confidence,
            alternatives=transcript.alternatives,
        )
        recognized = assessment.cleaned_text
        wer = word_error_rate(case.expected_text, recognized).wer
        last_noise_stage = next(reversed(noise_stages), "raw")
        last_voice_stage = next(reversed(voice_stages), "raw")
        gained_stage = "CaptureLevelProcessor"
        raw_noise = _median(noise_stages.get("raw", []))
        processed_noise = _median(noise_stages.get(last_noise_stage, []))
        raw_voice = _median(voice_stages.get("raw", []))
        gained_noise = _median(noise_stages.get(gained_stage, []))
        gained_voice = _median(voice_stages.get(gained_stage, []))
        processed_voice = _median(voice_stages.get(last_voice_stage, []))
        return VoiceSampleResult(
            case_id=case.case_id,
            expected_text=case.expected_text,
            recognized_text=recognized,
            device=device,
            vad_mode=vad_mode,
            silence_timeout_ms=silence_timeout_ms,
            status="ok" if recognized else "empty_transcript",
            processing_profile=processing_profile,
            engine=transcript.engine,
            confidence=assessment.acoustic_confidence,
            confidence_band=assessment.confidence_band.value,
            wer=wer,
            cer=character_error_rate(case.expected_text, recognized),
            frame_count=round(segment.duration_ms / collector.frame_ms),
            pcm_duration_ms=segment.duration_ms,
            vad_onset_ms=onset_ms,
            vad_offset_ms=offset_ms,
            capture_elapsed_ms=(time.monotonic() - started) * 1000.0,
            stt_latency_ms=transcript.latency_ms,
            truncated=segment.truncated,
            noise_rms_p50=_median(idle_rms),
            effective_source=effective_source,
            distance_cm=distance_cm,
            capture_gain_db=capture_gain_db,
            auto_gain_enabled=auto_gain_enabled,
            raw_noise_rms=raw_noise,
            recommended_auto_gain_gate_rms=recommend_auto_gain_gate_rms(
                noise_stages.get("raw", [])
            ),
            gained_noise_rms=gained_noise,
            processed_noise_rms=processed_noise,
            raw_noise_peak=max(noise_peaks.get("raw", []), default=0.0),
            gained_noise_peak=max(
                noise_peaks.get(gained_stage, []), default=0.0
            ),
            processed_noise_peak=max(
                noise_peaks.get(last_noise_stage, []), default=0.0
            ),
            raw_voice_rms=raw_voice,
            gained_voice_rms=gained_voice,
            processed_voice_rms=processed_voice,
            raw_voice_peak=max(voice_peaks.get("raw", []), default=0.0),
            gained_voice_peak=max(
                voice_peaks.get(gained_stage, []), default=0.0
            ),
            processed_voice_peak=max(
                voice_peaks.get(last_voice_stage, []), default=0.0
            ),
            snr_raw_db=_snr_db(raw_voice, raw_noise),
            snr_gained_db=_snr_db(gained_voice, gained_noise),
            snr_processed_db=_snr_db(processed_voice, processed_noise),
            clipping_ratio=(
                sum(clipping_ratios) / len(clipping_ratios)
                if clipping_ratios
                else 0.0
            ),
            applied_gain_db=_median(applied_gains) or 0.0,
            silence_false_trigger_frames=silence_false_trigger_frames,
            detail=assessment.reprompt_reason or "",
        )
    finally:
        # PCM remains process-local and is never emitted. Reset drops collector
        # references; stop clears backend buffers before the next sample.
        collector.reset()
        if frame_processor is not None:
            frame_processor.reset()
        audio_input.stop()
        segment = None
