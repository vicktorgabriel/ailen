"""Social domain models and actions for AILEN."""

from dataclasses import dataclass, field
from enum import Enum

from ailen.domain.enums import SocialMode


class SocialAction(str, Enum):
    """Actions decided by the social engine."""
    LOOK_AT = "LOOK_AT"
    GREET = "GREET"
    WAKE = "WAKE"
    SLEEP = "SLEEP"
    STAY_SILENT = "STAY_SILENT"
    CHANGE_EXPRESSION = "CHANGE_EXPRESSION"
    ACKNOWLEDGE = "ACKNOWLEDGE"


@dataclass
class SocialContext:
    """Contextual state provided to the SocialEngine for evaluation."""
    mode: SocialMode = SocialMode.WORKSHOP
    presence_state: bool = False
    conversation_active: bool = False
    last_greeting_at: float | None = None
    current_time: float = 0.0
    people_count_estimate: int = 1
    is_new_presence: bool = True
    sleep_state: bool = False
    greeting_cooldown_seconds: float = 60.0
    gaze_x: float | None = None
    gaze_y: float | None = None


@dataclass
class SocialDecision:
    """Deterministic decision emitted by the SocialEngine."""
    action: SocialAction
    reason_code: str
    gaze_target: tuple[float, float] | None = None
    greeting_intent: str | None = None
    expression_hint: str | None = None
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)
