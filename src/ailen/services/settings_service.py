"""SettingsService: contrato explícito entre la Web y la configuración.

Sólo campos de una allowlist declarativa son consultables/modificables. Los
handlers Web nunca editan TOML directamente ni aceptan claves arbitrarias
(MODULE_CONTRACTS.md §16). Toda escritura pasa por ``validate_config`` y se
persiste de forma atómica; una configuración inválida se rechaza sin tocar el
archivo actual.

Notas de seguridad:

- ``web.host``/``web.port`` NO son editables desde la Web: cambiar el bind en
  caliente podría exponer el panel fuera de lo previsto o dejar afuera al
  operador. Se administran por archivo/CLI y toman efecto al reiniciar.
- Ningún campo expone secretos (la configuración no contiene API keys).
"""

import copy
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ailen.core.config import AILENConfig, validate_config
from ailen.domain.enums import DeviceProfile, SocialMode
from ailen.services.config_service import ConfigService
from ailen.web.services import SettingField, SettingsUpdateResult

logger = logging.getLogger("ailen.services.settings")


@dataclass(frozen=True)
class _FieldSpec:
    """Descriptor interno de un campo administrable."""

    key: str  # "seccion.atributo", p.ej. "audio.output_volume"
    group: str
    label: str
    kind: str  # "text" | "bool" | "int" | "float" | "select"
    help_text: str = ""
    options: tuple[tuple[str, str], ...] = ()
    min_value: float | None = None
    max_value: float | None = None
    max_length: int = 200
    allow_empty: bool = False


_PROFILE_OPTIONS = tuple((p.value, p.value) for p in DeviceProfile)
_SOCIAL_OPTIONS = tuple((m.value, m.value) for m in SocialMode)

# Allowlist única de campos administrables vía Web (R5).
FIELD_SPECS: tuple[_FieldSpec, ...] = (
    # Personaje (identidad configurable; la marca de plataforma es AILEN)
    _FieldSpec(
        "identity.display_name", "Personaje", "Nombre visible del personaje", "text",
        help_text="Nombre con el que se presenta este asistente. No es la marca AILEN.",
        max_length=60,
    ),
    _FieldSpec(
        "speech.tts_voice", "Personaje", "Voz configurada", "text",
        help_text="Identificador de voz del motor TTS activo.",
        max_length=120,
    ),
    # Nodo
    _FieldSpec("node.name", "Nodo", "Nombre del nodo", "text", max_length=60),
    _FieldSpec(
        "node.profile", "Nodo", "Perfil de hardware", "select",
        options=_PROFILE_OPTIONS,
        help_text="El detector sugiere; el administrador puede forzar uno compatible.",
    ),
    # Pantalla
    _FieldSpec("display.enabled", "Pantalla", "Rostro en pantalla habilitado", "bool"),
    _FieldSpec("display.fullscreen", "Pantalla", "Pantalla completa", "bool"),
    _FieldSpec("display.face_style", "Pantalla", "Estilo de rostro", "select", options=(("facepack", "FacePack nativo"), ("portrait", "Retrato animado"), ("pixel", "Pixel mesh"), ("vector", "Vectorial"))),
    _FieldSpec("display.fps_limit", "Pantalla", "Límite de cuadros por segundo", "int", min_value=1, max_value=120),
    # Audio
    _FieldSpec(
        "audio.input_device",
        "Audio",
        "Fuente de captura",
        "text",
        help_text="Use default, plughw:CARD=...,DEV=... o pipewire:<nombre-estable>.",
        max_length=240,
    ),
    _FieldSpec(
        "audio.input_processing_mode",
        "Audio",
        "Procesamiento de entrada",
        "select",
        options=(
            ("auto", "Automático"),
            ("raw", "Sin DSP interno"),
            ("easyeffects", "Fuente ya procesada externamente"),
        ),
        help_text="Evita aplicar AGC/preamp dos veces sobre una fuente Easy Effects.",
    ),
    _FieldSpec("audio.output_device", "Audio", "Dispositivo de parlantes", "select", options=(("default", "Default del Sistema"), ("hw:0,0", "Parlantes Integrados ALC")), allow_empty=True),
    _FieldSpec(
        "audio.capture_gain_db", "Audio", "Pre-ganancia digital (dB)", "float",
        min_value=-24.0, max_value=30.0,
        help_text="Ganancia digital explícita; calibrar antes de aumentarla.",
    ),
    _FieldSpec("audio.auto_gain_enabled", "Audio", "AGC de captura", "bool"),
    _FieldSpec(
        "audio.auto_gain_target_rms", "Audio", "RMS objetivo del AGC", "float",
        min_value=0.01, max_value=0.5,
    ),
    _FieldSpec(
        "audio.max_auto_gain_db", "Audio", "Ganancia automática máxima (dB)", "float",
        min_value=0.0, max_value=30.0,
    ),
    _FieldSpec(
        "audio.auto_gain_noise_gate_rms",
        "Audio",
        "Piso de ruido del AGC (RMS)",
        "float",
        min_value=0.0,
        max_value=0.5,
        help_text="Por debajo de este nivel el AGC no aumenta ganancia.",
    ),
    _FieldSpec(
        "audio.auto_gain_gate_hold_ms",
        "Audio",
        "Retención del AGC bajo el piso (ms)",
        "float",
        min_value=0.0,
        max_value=5000.0,
    ),
    _FieldSpec("audio.output_volume", "Audio", "Volumen de salida", "int",
               min_value=0, max_value=100),
    _FieldSpec("audio.music_volume", "Audio", "Volumen de música", "int",
               min_value=0, max_value=100),
    # Visión
    _FieldSpec("vision.enabled", "Visión", "Detección de presencia habilitada", "bool"),
    _FieldSpec(
        "vision.camera_source", "Visión", "Fuente de cámara", "select",
        options=(("auto", "auto"), ("usb", "usb"), ("rtsp", "rtsp")),
    ),
    _FieldSpec("vision.detector", "Visión", "Detector facial", "select", options=(("yunet", "yunet"), ("haar", "haar"))),
    _FieldSpec("vision.fps", "Visión", "Cuadros por segundo", "int", min_value=1, max_value=30),
    _FieldSpec("vision.detector_score_threshold", "Visión", "Umbral detector facial", "float", min_value=0.1, max_value=1.0),
    _FieldSpec("vision.presence_confirm_seconds", "Visión", "Confirmación de presencia (seg)", "float", min_value=0.1, max_value=10.0),
    _FieldSpec("vision.absence_confirm_seconds", "Visión", "Confirmación de ausencia (seg)", "float", min_value=0.1, max_value=10.0),
    _FieldSpec(
        "vision.camera_device", "Visión", "Cámara seleccionada", "text",
        help_text='Dispositivo actual, p.ej. "/dev/video0".',
        max_length=120,
    ),
    # Voz
    _FieldSpec(
        "speech.stt_engine", "Voz", "Motor STT", "select",
        options=(
            ("mock", "mock (pruebas)"),
            ("whisper_cpp", "whisper.cpp"),
            ("vosk", "Vosk"),
            ("cloud", "cloud"),
        ),
    ),
    _FieldSpec(
        "speech.tts_engine", "Voz", "Motor TTS", "select",
        options=(
            ("mock", "mock (pruebas)"),
            ("piper", "Piper"),
            ("coqui", "Coqui"),
            ("cloud", "cloud"),
        ),
    ),
    # Comportamiento social
    _FieldSpec("social.default_mode", "Comportamiento", "Modo social por defecto",
               "select", options=_SOCIAL_OPTIONS),
    _FieldSpec("social.auto_greeting_enabled", "Comportamiento",
               "Saludo automático al detectar presencia", "bool"),
    _FieldSpec("social.greeting_cooldown_seconds", "Comportamiento",
               "Cooldown de saludo (segundos)", "float", min_value=0),
    # IA híbrida. Los proveedores remotos nombrados agregan sus specs en
    # ``SettingsService._specs``; ningún secreto forma parte de esta allowlist.
    _FieldSpec(
        "ai.provider", "IA híbrida", "Backend conversacional preferido", "text",
        help_text="Si el preferido no está disponible, el router usa los backends permitidos como fallback.",
        max_length=40,
    ),
    _FieldSpec("ai.max_tokens", "IA híbrida", "Máximo de tokens por respuesta", "int", min_value=32, max_value=2048),
    _FieldSpec(
        "ai.temperature", "IA híbrida", "Espontaneidad / temperatura", "float",
        min_value=0, max_value=2,
        help_text="Más alto = respuestas más variadas; no cambia permisos ni herramientas.",
    ),
    _FieldSpec(
        "ai.context_recent_messages", "IA híbrida", "Mensajes recientes en contexto", "int",
        min_value=1, max_value=32,
        help_text="La memoria persiste en SQLite; esto sólo limita el historial enviado en cada inferencia.",
    ),
    _FieldSpec(
        "ai.context_char_budget", "IA híbrida", "Presupuesto de contexto (caracteres)", "int",
        min_value=512, max_value=20000,
    ),
    _FieldSpec("ai.allow_remote", "IA híbrida", "Permitir proveedores IA remotos", "bool"),
    _FieldSpec("ai.remote.enabled", "IA híbrida", "Provider Manager remoto habilitado", "bool"),
    _FieldSpec(
        "ai.allow_sanitized_external_prompts", "IA híbrida",
        "Permitir consulta externa sin memoria privada", "bool",
        help_text=(
            "Envía sólo el turno actual y contexto público del personaje. "
            "No adjunta historial de sesión ni memorias privadas."
        ),
    ),
    # Ollama Local
    _FieldSpec("ai.local.enabled", "IA híbrida", "LLM local habilitado", "bool"),
    _FieldSpec("ai.local.endpoint", "IA híbrida", "Endpoint del LLM local", "text", max_length=240),
    _FieldSpec("ai.local.model", "IA híbrida", "Modelo local cuantizado", "text", max_length=160),
    _FieldSpec("ai.local.intent_model", "IA híbrida", "Modelo de intención local", "text", max_length=160, allow_empty=True),
    _FieldSpec(
        "ai.local.context_tokens", "IA híbrida", "Contexto local Ollama (tokens)", "int",
        min_value=512, max_value=32768,
        help_text="Un contexto menor reduce RAM en equipos limitados; la memoria completa sigue en SQLite.",
    ),
    _FieldSpec("ai.local.priority", "IA híbrida", "Prioridad LLM Local", "int", min_value=1, max_value=100),
    # LAN Brain
    _FieldSpec(
        "ai.lan.provider", "IA híbrida", "Transporte LAN Brain (laboratorio)", "select",
        options=(("openai_compatible", "OpenAI-compatible"), ("ollama_native", "Ollama nativo")),
        help_text="Sólo para laboratorios o nodos LAN confiables; no es requisito del producto final.",
    ),
    _FieldSpec("ai.lan.priority", "IA híbrida", "Prioridad LAN Brain", "int", min_value=1, max_value=100),
    # Escucha y voz avanzada.
    _FieldSpec(
        "speech.stt_fallback_engine", "Escucha y voz", "STT de rescate", "select",
        options=(("none", "Sin rescate"), ("whisper_cpp", "Whisper.cpp local")),
        help_text="Se usa sólo cuando el STT primario devuelve baja confianza o vacío.",
    ),
    _FieldSpec(
        "speech.stt_fallback_confidence_threshold", "Escucha y voz",
        "Umbral de confianza para STT de rescate", "float", min_value=0, max_value=1,
    ),
    _FieldSpec("speech.tts_rate", "Escucha y voz", "Velocidad de voz", "float", min_value=0.5, max_value=1.8),
    _FieldSpec("speech.chatterbox_rate_scale", "Escucha y voz", "Escala de velocidad expresiva", "float", min_value=0.85, max_value=1.15),
    _FieldSpec("speech.chatterbox_pitch_semitones", "Escucha y voz", "Tono base Chatterbox (semitonos)", "float", min_value=-2.0, max_value=2.0),
    _FieldSpec("speech.tts_threads", "Escucha y voz", "Hilos CPU para TTS (0=auto)", "int", min_value=0, max_value=32),
    _FieldSpec(
        "speech.noise_suppression_engine", "Escucha y voz", "Supresión de ruido", "select",
        options=(("none", "Desactivada"), ("webrtc", "WebRTC")),
    ),
    _FieldSpec("speech.noise_suppression_level", "Escucha y voz", "Nivel de supresión de ruido", "int", min_value=0, max_value=3),
    _FieldSpec(
        "speech.vad_engine", "Escucha y voz", "Detector de voz", "select",
        options=(("energy", "Energía"), ("webrtc", "WebRTC")),
    ),
    _FieldSpec("speech.vad_threshold", "Escucha y voz", "Piso de energía de voz", "float", min_value=0, max_value=1),
    _FieldSpec("speech.vad_webrtc_mode", "Escucha y voz", "Agresividad WebRTC VAD", "int", min_value=0, max_value=3),
    _FieldSpec("speech.min_speech_ms", "Escucha y voz", "Voz continua para abrir turno (ms)", "int", min_value=20, max_value=2000),
    _FieldSpec("speech.silence_timeout_ms", "Escucha y voz", "Silencio para cerrar turno (ms)", "int", min_value=100, max_value=5000),
    _FieldSpec("speech.interruption_enabled", "Escucha y voz", "Permitir interrumpir a Ailén mientras habla", "bool"),
    _FieldSpec("speech.interruption_threshold_rms", "Escucha y voz", "Piso de energía para interrupción", "float", min_value=0.001, max_value=1),
    _FieldSpec("speech.interruption_min_ms", "Escucha y voz", "Voz continua para interrumpir (ms)", "int", min_value=40, max_value=3000),

    # Personalidad: parámetros acotados de estilo, nunca permisos.
    _FieldSpec(
        "personality.description", "Personalidad", "Descripción del personaje", "text",
        help_text="Rasgos narrativos y forma de reaccionar. No concede permisos ni capacidades.",
        max_length=1000, allow_empty=True,
    ),
    _FieldSpec("personality.base_curiosity", "Personalidad", "Curiosidad", "float", min_value=0, max_value=1),
    _FieldSpec("personality.base_sociability", "Personalidad", "Sociabilidad / iniciativa", "float", min_value=0, max_value=1),
    _FieldSpec("personality.base_formality", "Personalidad", "Formalidad", "float", min_value=0, max_value=1),
    _FieldSpec("personality.base_humor", "Personalidad", "Humor", "float", min_value=0, max_value=1),
    _FieldSpec("personality.base_verbosity", "Personalidad", "Verbosity", "float", min_value=0, max_value=1),
    _FieldSpec("personality.base_patience", "Personalidad", "Paciencia", "float", min_value=0, max_value=1),
    _FieldSpec("personality.base_expressiveness", "Personalidad", "Expresividad", "float", min_value=0, max_value=1),

    # Herramientas y Red
    _FieldSpec("network.outbound_web_enabled", "Herramientas", "Búsqueda web en vivo habilitada", "bool"),
    _FieldSpec(
        "network.web_search_provider", "Herramientas", "Proveedor de búsqueda web", "select",
        options=(("none", "Desactivada"), ("ddgs", "DuckDuckGo Scraper (DDGS - Privado)")),
    ),
    _FieldSpec(
        "network.web_search_region", "Herramientas", "Región de búsqueda web", "select",
        options=(("ar-es", "Argentina (ar-es)"), ("es-es", "España (es-es)"), ("wt-wt", "Global (wt-wt)")),
    ),

    _FieldSpec(
        "agent.max_autonomy_level", "Agente", "Nivel máximo de autonomía (ADR-014)", "int",
        min_value=1, max_value=3,
    ),

    # Actualizaciones
    _FieldSpec(
        "updates.channel", "Actualizaciones", "Canal de actualización", "select",
        options=(
            ("nightly", "nightly (desarrollo)"),
            ("beta", "beta (prototipos)"),
            ("stable", "stable (clientes)"),
        ),
    ),
)

_TRUE_VALUES = {"true", "1", "on", "yes", "si", "sí"}


class SettingsService:
    """Implementación del contrato ``SettingsService`` sobre ``ConfigService``."""

    def __init__(self, config_service: ConfigService) -> None:
        self._config_service = config_service

    def get_config(self) -> AILENConfig:
        """Devuelve la configuración activa actual."""
        return self._config_service.reload()

    def set_secret(self, secret_name: str, secret_value: str) -> bool:
        """Guarda una clave en el almacén seguro 0600."""
        from ailen.ai.secrets import SecretResolver
        try:
            SecretResolver().save_secret(secret_name, secret_value)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("Error saving secret %s: %s", secret_name, e)
            return False


    @property
    def config_path(self) -> Path | str | None:
        if hasattr(self._config_service, "config_path") and self._config_service.config_path:
            return self._config_service.config_path
        from ailen.core.config import find_config_path
        return find_config_path()

    def get_fields(self) -> list[SettingField]:
        """Devuelve los campos administrables con su valor efectivo actual."""
        cfg = self._config_service.reload()
        specs = self._specs(cfg)
        return [
            SettingField(
                key=spec.key,
                group=spec.group,
                label=spec.label,
                kind=spec.kind,
                value=self._read(cfg, spec),
                options=list(spec.options),
                help_text=spec.help_text,
            )
            for spec in specs
        ]

    # -- escritura ----------------------------------------------------------

    def update(self, changes: dict[str, str]) -> SettingsUpdateResult:
        """Valida y persiste cambios de forma atómica.

        Reglas:

        - clave desconocida -> error (no se guarda nada);
        - sólo se modifican las claves presentes en ``changes``;
        - la capa Web traduce checkboxes ausentes a ``false`` cuando procesa
          un formulario HTML completo;
        - el resultado completo se valida con ``validate_config`` antes de
          escribir; si algo falla, el archivo actual queda intacto.
        """
        errors: dict[str, str] = {}
        cfg = copy.deepcopy(self._config_service.current_config)
        specs = self._specs(cfg)
        specs_by_key = {spec.key: spec for spec in specs}
        for key in sorted(k for k in changes if k not in specs_by_key):
            errors[key] = "Campo no permitido."
        if errors:
            return SettingsUpdateResult(ok=False, errors=errors)

        for spec in specs:
            if spec.key not in changes:
                continue
            raw = changes[spec.key]
            if spec.kind == "bool":
                enabled = raw.strip().lower() in _TRUE_VALUES
                self._apply(cfg, spec, enabled)
                continue
            value = self._convert(spec, raw, errors)
            if spec.key not in errors:
                self._apply(cfg, spec, value)

        if errors:
            return SettingsUpdateResult(ok=False, errors=errors)

        for message in validate_config(cfg):
            errors["_global"] = message
        if errors:
            return SettingsUpdateResult(ok=False, errors=errors)

        self._config_service.save_config(cfg)
        logger.info("Configuración actualizada vía panel (%d campos).", len(changes))
        return SettingsUpdateResult(ok=True)

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _resolve_parent(cfg: AILENConfig, key: str) -> tuple[Any, str]:
        parts = key.split(".")
        if len(parts) < 2 or any(not part for part in parts):
            raise ValueError(f"Invalid setting path: {key!r}")
        target: Any = cfg
        for part in parts[:-1]:
            target = target[part] if isinstance(target, dict) else getattr(target, part)
        return target, parts[-1]

    def _read(self, cfg: AILENConfig, spec: _FieldSpec) -> str:
        target, attr = self._resolve_parent(cfg, spec.key)
        value = getattr(target, attr)
        if value is None:
            return ""
        if spec.kind == "bool":
            return "true" if value else "false"
        if isinstance(value, DeviceProfile | SocialMode):
            return str(value.value)
        return str(value)

    def _apply(self, cfg: AILENConfig, spec: _FieldSpec, value: Any) -> None:
        target, attr = self._resolve_parent(cfg, spec.key)
        current = getattr(target, attr)
        if isinstance(current, DeviceProfile):
            setattr(target, attr, DeviceProfile(value))
        elif isinstance(current, SocialMode):
            setattr(target, attr, SocialMode(value))
        else:
            setattr(target, attr, value)

    def _convert(self, spec: _FieldSpec, raw: str, errors: dict[str, str]) -> Any:
        raw = raw.strip()
        if spec.kind == "text":
            if not raw and not spec.allow_empty:
                errors[spec.key] = "No puede estar vacío."
            elif len(raw) > spec.max_length:
                errors[spec.key] = f"Máximo {spec.max_length} caracteres."
            return raw
        if spec.kind == "select":
            allowed = {value: value for value, _ in spec.options}
            allowed_lower = {value.lower(): value for value, _ in spec.options}
            if raw in allowed:
                return raw
            if raw.lower() in allowed_lower:
                return allowed_lower[raw.lower()]
            errors[spec.key] = "Opción inválida."
            return raw
        if spec.allow_empty and not raw and spec.kind in {"int", "float"}:
            return None
        if spec.kind == "int":
            try:
                value: Any = int(raw)
            except ValueError:
                errors[spec.key] = "Debe ser un número entero."
                return None
        elif spec.kind == "float":
            try:
                value = float(raw)
            except ValueError:
                errors[spec.key] = "Debe ser un número."
                return None
        else:
            errors[spec.key] = "Tipo de campo desconocido."
            return None
        if spec.min_value is not None and value < spec.min_value:
            errors[spec.key] = f"Mínimo {spec.min_value:g}."
        elif spec.max_value is not None and value > spec.max_value:
            errors[spec.key] = f"Máximo {spec.max_value:g}."
        return value
    @staticmethod
    def _specs(cfg: AILENConfig) -> tuple[_FieldSpec, ...]:
        remote_specs: list[_FieldSpec] = []
        for provider_id in sorted(cfg.ai.remote.providers):
            prefix = f"ai.remote.providers.{provider_id}"
            group = f"IA remota · {provider_id}"
            remote_specs.extend(
                (
                    _FieldSpec(f"{prefix}.enabled", group, "Habilitado", "bool"),
                    _FieldSpec(f"{prefix}.preset", group, "Preset", "text", max_length=40),
                    _FieldSpec(
                        f"{prefix}.protocol", group, "Protocolo", "select",
                        options=(("openai_responses", "OpenAI Responses"), ("openai_chat", "OpenAI Chat Completions"), ("anthropic_messages", "Anthropic Messages")),
                    ),
                    _FieldSpec(f"{prefix}.endpoint", group, "Endpoint HTTPS", "text", max_length=300, allow_empty=True),
                    _FieldSpec(f"{prefix}.model", group, "Modelo explícito", "text", max_length=180, allow_empty=True),
                    _FieldSpec(f"{prefix}.priority", group, "Prioridad", "int", min_value=0, max_value=1000),
                    _FieldSpec(f"{prefix}.timeout_seconds", group, "Timeout", "float", min_value=0.1, max_value=120),
                    _FieldSpec(f"{prefix}.daily_budget_usd", group, "Presupuesto diario USD", "float", min_value=0),
                    _FieldSpec(f"{prefix}.monthly_budget_usd", group, "Presupuesto mensual USD", "float", min_value=0),
                    _FieldSpec(f"{prefix}.streaming_enabled", group, "Streaming real habilitado", "bool"),
                    _FieldSpec(
                        f"{prefix}.catalog_mode", group, "Catálogo", "select",
                        options=(("manual", "Manual"), ("live", "Live /models")),
                    ),
                )
            )
        return (*FIELD_SPECS, *remote_specs)
