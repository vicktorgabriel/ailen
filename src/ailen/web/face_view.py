"""Context builder for the /rostro administration view."""

from ailen.core.config import AILENConfig

NO_MEASUREMENT = "Sin medición"
NO_AVAILABLE = "No disponible"


def _text(value: object) -> str:
    cleaned = str(value or "").strip()
    return cleaned if cleaned else NO_AVAILABLE


def face_context(cfg: AILENConfig) -> dict[str, str]:
    """Build template variables for face.html strictly from real AILENConfig values."""
    display = cfg.display
    style = str(display.face_style or "").strip().lower()
    fps_limit = max(1, min(120, int(display.fps_limit)))
    width = int(display.width)
    height = int(display.height)
    width_str = str(width) if width > 0 else NO_AVAILABLE
    height_str = str(height) if height > 0 else NO_AVAILABLE
    resolution = f"{width}x{height}" if width > 0 and height > 0 else NO_AVAILABLE

    return {
        "csrf": "",
        "display_status": "Habilitado" if display.enabled else "Deshabilitado",
        "chk_display_enabled": " checked" if display.enabled else "",
        "chk_fullscreen": " checked" if display.fullscreen else "",
        "face_style": _text(display.face_style),
        "sel_style_facepack": " selected" if style == "facepack" else "",
        "sel_style_portrait": " selected" if style == "portrait" else "",
        "sel_style_pixel": " selected" if style == "pixel" else "",
        "sel_style_vector": " selected" if style == "vector" else "",
        "val_fps_limit": str(fps_limit),
        "display_width": width_str,
        "display_height": height_str,
        "display_resolution": resolution,
        "display_backend": _text(display.backend),
        "facepack_path": _text(display.facepack_path),
        "face_metrics": NO_MEASUREMENT,
        "live_expression_state": NO_AVAILABLE,
    }
