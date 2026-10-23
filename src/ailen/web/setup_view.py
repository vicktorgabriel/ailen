"""Context for the setup page built only from measured hardware and config."""

import html

from ailen.core.config import AILENConfig
from ailen.domain.enums import DeviceProfile
from ailen.domain.models import AudioDeviceInfo, HardwareReport

NO_MEASUREMENT = "Sin medición"
NO_AVAILABLE = "No disponible"


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _text(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "unknown"}:
        return NO_AVAILABLE
    return text


def _ram_mb(hw: HardwareReport) -> float:
    if hw.memory.total_mb > 0:
        return hw.memory.total_mb
    return hw.memory.total_bytes / (1024 * 1024)


def _available_ram_mb(hw: HardwareReport) -> float:
    if hw.memory.available_mb > 0:
        return hw.memory.available_mb
    return hw.memory.available_bytes / (1024 * 1024)


def _disk_total_gb(hw: HardwareReport) -> float:
    if hw.disk.total_gb > 0:
        return hw.disk.total_gb
    return hw.disk.total_bytes / (1024**3)


def _disk_free_gb(hw: HardwareReport) -> float:
    if hw.disk.free_gb > 0:
        return hw.disk.free_gb
    return hw.disk.free_bytes / (1024**3)


def _format_mb(value: float) -> str:
    if value <= 0:
        return NO_MEASUREMENT
    if value >= 1024:
        return f"{value / 1024:.1f} GiB ({value:.0f} MiB)"
    return f"{value:.0f} MiB"


def _format_gb(value: float) -> str:
    if value <= 0:
        return NO_MEASUREMENT
    return f"{value:.1f} GB"


def _audio_summary(devices: list[AudioDeviceInfo]) -> str:
    if not devices:
        return NO_MEASUREMENT
    return " · ".join(
        f"{device.name} (índice {device.index}"
        f"{', predeterminado' if device.is_default else ''})"
        for device in devices
    )


def _camera_summary(hw: HardwareReport) -> str:
    if not hw.cameras:
        return NO_MEASUREMENT
    return " · ".join(
        f"{camera.name} ({camera.device_path}, "
        f"{'accesible' if camera.accessible else 'sin acceso'})"
        for camera in hw.cameras
    )


def _rows(pairs: list[tuple[str, str]]) -> str:
    return "".join(
        f'<li class="kv-item"><span class="kv-key">{_esc(key)}</span>'
        f'<span class="kv-val">{_esc(value)}</span></li>'
        for key, value in pairs
    )


def _hardware_html(hw: HardwareReport) -> str:
    cpu_frequency = (
        f"{hw.cpu.frequency_mhz:.0f} MHz"
        if hw.cpu.frequency_mhz and hw.cpu.frequency_mhz > 0
        else NO_MEASUREMENT
    )
    gpu = _text(hw.gpu.name) if hw.gpu.detected else "No detectada"
    gpu_detail = (
        f"{gpu} ({_text(hw.gpu.driver)})" if hw.gpu.detected else gpu
    )
    os_summary = (
        f"{_text(hw.os.distribution)} "
        f"({_text(hw.os.system)} {_text(hw.os.release)})"
    )
    pairs = [
        ("Procesador (CPU)", _text(hw.cpu.model)),
        ("Arquitectura", _text(hw.cpu.arch)),
        (
            "Núcleos",
            f"{hw.cpu.cores_physical} físicos / {hw.cpu.cores_logical} lógicos",
        ),
        ("Frecuencia", cpu_frequency),
        (
            "Memoria RAM",
            (
                f"{_format_mb(_ram_mb(hw))} total / "
                f"{_format_mb(_available_ram_mb(hw))} disponible"
            ),
        ),
        ("GPU / acelerador", gpu_detail),
        (
            f"Disco ({hw.disk.mount_point})",
            (
                f"{_format_gb(_disk_total_gb(hw))} total / "
                f"{_format_gb(_disk_free_gb(hw))} libres"
            ),
        ),
        ("Cámaras", _camera_summary(hw)),
        ("Audio de entrada", _audio_summary(hw.audio_inputs)),
        ("Audio de salida", _audio_summary(hw.audio_outputs)),
        ("Sistema operativo", os_summary),
        ("Kernel", _text(hw.os.kernel_version)),
    ]
    return f'<ul class="kv-list">{"".join(_rows(pairs))}</ul>'


def _profile_options(current: DeviceProfile) -> str:
    return "".join(
        f'<option value="{_esc(profile.value)}"'
        f'{" selected" if profile == current else ""}>'
        f"{_esc(profile.value)}</option>"
        for profile in DeviceProfile
    )


def _bool_label(value: bool, yes: str, no: str) -> str:
    return yes if value else no


def setup_context(hw: HardwareReport | None, cfg: AILENConfig) -> dict[str, str]:
    """Build every value rendered by ``setup.html`` from real sources only.

    ``hw`` is ``None`` when ``StatusService`` could not produce a report; the
    page must say so instead of presenting fallback capacities as measurements.
    CSRF is intentionally left empty here because it belongs to the request
    session; the web handler overrides it when rendering.
    """
    context: dict[str, str] = {
        "csrf": "",
        "hw_status": "Hardware no detectado" if hw is None else "Hardware detectado",
        "hw_timestamp": (
            _text(hw.timestamp) if hw is not None else NO_MEASUREMENT
        ),
        "rec_profile": (
            hw.recommended_profile.value if hw is not None else NO_MEASUREMENT
        ),
        "node_name": _text(cfg.node.name),
        "node_profile": cfg.node.profile.value,
        "identity_name": _text(cfg.identity.display_name),
        "audio_input_device": _text(cfg.audio.input_device),
        "audio_output_device": _text(cfg.audio.output_device),
        "audio_capture_gain": f"{cfg.audio.capture_gain_db:g} dB",
        "audio_agc": _bool_label(cfg.audio.auto_gain_enabled, "Habilitado", "Deshabilitado"),
        "vision_enabled": _bool_label(cfg.vision.enabled, "Habilitada", "Deshabilitada"),
        "vision_camera_device": _text(cfg.vision.camera_device),
        "speech_stt_engine": _text(cfg.speech.stt_engine),
        "speech_tts_engine": _text(cfg.speech.tts_engine),
        "speech_tts_voice": _text(cfg.speech.tts_voice),
        "ai_provider": _text(cfg.ai.provider),
        "ai_remote": _bool_label(cfg.ai.allow_remote, "Permitidos", "Bloqueados"),
        "profile_options": _profile_options(cfg.node.profile),
    }
    if hw is None:
        context.update(
            {
                "hardware_html": (
                    '<p class="notice warn">Hardware no detectado. '
                    "No se muestran valores de CPU, RAM, GPU, disco, cámaras, "
                    "audio ni sistema operativo.</p>"
                ),
                "cpu_name": "Hardware no detectado",
                "cpu_cores": NO_MEASUREMENT,
                "ram_total_mb": NO_MEASUREMENT,
                "ram_total": NO_MEASUREMENT,
                "ram_available": NO_MEASUREMENT,
                "gpu_name": NO_MEASUREMENT,
                "disk_total": NO_MEASUREMENT,
                "disk_free": NO_MEASUREMENT,
                "cameras_summary": NO_MEASUREMENT,
                "audio_inputs_summary": NO_MEASUREMENT,
                "audio_outputs_summary": NO_MEASUREMENT,
                "os_summary": NO_MEASUREMENT,
            }
        )
        return context

    ram_mb = _ram_mb(hw)
    context.update(
        {
            "hardware_html": _hardware_html(hw),
            "cpu_name": _text(hw.cpu.model),
            "cpu_cores": str(hw.cpu.cores_logical),
            "ram_total_mb": f"{ram_mb:.0f}" if ram_mb > 0 else NO_MEASUREMENT,
            "ram_total": _format_mb(ram_mb),
            "ram_available": _format_mb(_available_ram_mb(hw)),
            "gpu_name": _text(hw.gpu.name) if hw.gpu.detected else "No detectada",
            "disk_total": _format_gb(_disk_total_gb(hw)),
            "disk_free": _format_gb(_disk_free_gb(hw)),
            "cameras_summary": _camera_summary(hw),
            "audio_inputs_summary": _audio_summary(hw.audio_inputs),
            "audio_outputs_summary": _audio_summary(hw.audio_outputs),
            "os_summary": (
                f"{_text(hw.os.distribution)} "
                f"({_text(hw.os.system)} {_text(hw.os.release)})"
            ),
        }
    )
    return context
