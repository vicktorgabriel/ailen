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
        help_text="Identificador de voz del motor TTS activo. La personalidad "
        "evolutiva se administrará acá cuando el Personality Engine la exponga.",
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
    # Audio
    _FieldSpec("audio.input_volume", "Audio", "Volumen de micrófono", "int",
               min_value=0, max_value=100),
    _FieldSpec("audio.output_volume", "Audio", "Volumen de salida", "int",
               min_value=0, max_value=100),
    _FieldSpec("audio.music_volume", "Audio", "Volumen de música", "int",
               min_value=0, max_value=100),
    # Visión
    _FieldSpec("vision.enabled", "Visión", "Detección de presencia habilitada", "bool"),
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

_SPECS_BY_KEY: dict[str, _FieldSpec] = {spec.key: spec for spec in FIELD_SPECS}

_TRUE_VALUES = {"true", "1", "on", "yes", "si", "sí"}


class SettingsService:
    """Implementación del contrato ``SettingsService`` sobre ``ConfigService``."""

    def __init__(self, config_service: ConfigService) -> None:
        self._config_service = config_service

    # -- lectura -----------------------------------------------------------

    def get_fields(self) -> list[SettingField]:
        """Devuelve los campos administrables con su valor efectivo actual."""
        cfg = self._config_service.reload()
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
            for spec in FIELD_SPECS
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
        for key in sorted(k for k in changes if k not in _SPECS_BY_KEY):
            errors[key] = "Campo no permitido."
        if errors:
            return SettingsUpdateResult(ok=False, errors=errors)

        cfg = copy.deepcopy(self._config_service.current_config)
        for spec in FIELD_SPECS:
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
        logger.info("Configuración actualizada vía panel (%d campos).", len(FIELD_SPECS))
        return SettingsUpdateResult(ok=True)

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _split(key: str) -> tuple[str, str]:
        section, _, attr = key.partition(".")
        return section, attr

    def _read(self, cfg: AILENConfig, spec: _FieldSpec) -> str:
        section, attr = self._split(spec.key)
        value = getattr(getattr(cfg, section), attr)
        if spec.kind == "bool":
            return "true" if value else "false"
        if isinstance(value, DeviceProfile | SocialMode):
            return str(value.value)
        return str(value)

    def _apply(self, cfg: AILENConfig, spec: _FieldSpec, value: Any) -> None:
        section, attr = self._split(spec.key)
        target = getattr(cfg, section)
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
            if not raw:
                errors[spec.key] = "No puede estar vacío."
            elif len(raw) > spec.max_length:
                errors[spec.key] = f"Máximo {spec.max_length} caracteres."
            return raw
        if spec.kind == "select":
            allowed = {value for value, _ in spec.options}
            if raw not in allowed:
                errors[spec.key] = "Opción inválida."
            return raw
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
