"""Context builder for the /vision administration view."""

from ailen.core.config import AILENConfig


def vision_context(cfg: AILENConfig) -> dict[str, str]:
    """Build template variables for vision.html strictly from real AILENConfig values."""
    source = cfg.vision.camera_source.strip().lower()
    detector = cfg.vision.detector.strip().lower()
    threshold = max(0.1, min(1.0, float(cfg.vision.detector_score_threshold)))
    fps = max(1, min(30, int(cfg.vision.fps)))

    return {
        "csrf": "",
        "vision_status": "Habilitada" if cfg.vision.enabled else "Deshabilitada",
        "detector_label": detector,
        "chk_vision_enabled": " checked" if cfg.vision.enabled else "",
        "sel_cam_auto": " selected" if source == "auto" else "",
        "sel_cam_usb": " selected" if source == "usb" else "",
        "sel_cam_rtsp": " selected" if source == "rtsp" else "",
        "camera_device": cfg.vision.camera_device,
        "sel_det_yunet": " selected" if detector == "yunet" else "",
        "sel_det_haar": " selected" if detector == "haar" else "",
        "val_fps": str(fps),
        "val_face_conf": f"{threshold:.2f}",
        "entry_debounce": f"{cfg.vision.presence_confirm_seconds:g}",
        "exit_debounce": f"{cfg.vision.absence_confirm_seconds:g}",
        "chk_auto_greet": " checked" if cfg.social.auto_greeting_enabled else "",
        "vision_metrics": "Sin medición",
        "sensor_status": "No disponible",
    }
