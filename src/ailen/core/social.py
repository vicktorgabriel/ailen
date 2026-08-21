"""Social Engine for AILEN.

Decides presence reactions, gaze orientation, greeting permissions, cooldowns,
and mode-specific social behaviors deterministically without LLM dependency.
"""

import logging

from ailen.domain.enums import SocialMode
from ailen.domain.social import SocialAction, SocialContext, SocialDecision

logger = logging.getLogger("ailen.core.social")


class SocialEngine:
    """Deterministic social interaction and greeting policy engine."""

    def __init__(self, default_cooldown_seconds: float = 60.0, allow_greetings: bool = True):
        self.default_cooldown_seconds = default_cooldown_seconds
        self.allow_greetings = allow_greetings

    def evaluate(self, ctx: SocialContext) -> SocialDecision:
        """Evaluate contextual social state and produce a deterministic SocialDecision."""
        gaze = (ctx.gaze_x, ctx.gaze_y) if ctx.gaze_x is not None and ctx.gaze_y is not None else None

        # 1. No presence detected
        if not ctx.presence_state:
            if ctx.sleep_state or ctx.mode == SocialMode.SLEEP:
                return SocialDecision(
                    action=SocialAction.SLEEP,
                    reason_code="SLEEP_PRESERVED",
                )
            return SocialDecision(
                action=SocialAction.STAY_SILENT,
                reason_code="PRESENCE_ABSENT",
            )

        # 2. Presence detected while sleeping -> WAKE
        if ctx.sleep_state or ctx.mode == SocialMode.SLEEP:
            return SocialDecision(
                action=SocialAction.WAKE,
                reason_code="PRESENCE_WAKE",
                gaze_target=gaze or (0.0, 0.0),
                expression_hint="waking",
            )

        # 3. Active ongoing conversation -> don't interrupt with greeting
        if ctx.conversation_active:
            return SocialDecision(
                action=SocialAction.LOOK_AT,
                reason_code="CONVERSATION_ACTIVE",
                gaze_target=gaze or (0.0, 0.0),
                expression_hint="focused",
            )

        # 4. Greetings globally disabled in config
        if not self.allow_greetings:
            return SocialDecision(
                action=SocialAction.LOOK_AT,
                reason_code="GREETING_DISABLED",
                gaze_target=gaze or (0.0, 0.0),
                expression_hint="neutral",
            )

        # 5. Presence is continuous / already known in current session
        if not ctx.is_new_presence:
            return SocialDecision(
                action=SocialAction.LOOK_AT,
                reason_code="ALREADY_GREETED_PRESENCE",
                gaze_target=gaze or (0.0, 0.0),
                expression_hint="attentive",
            )

        # 6. Cooldown active
        cooldown = ctx.greeting_cooldown_seconds if ctx.greeting_cooldown_seconds > 0 else self.default_cooldown_seconds
        if ctx.last_greeting_at is not None:
            elapsed = ctx.current_time - ctx.last_greeting_at
            if elapsed < cooldown:
                return SocialDecision(
                    action=SocialAction.LOOK_AT,
                    reason_code="COOLDOWN_ACTIVE",
                    gaze_target=gaze or (0.0, 0.0),
                    expression_hint="attentive",
                    metadata={"elapsed": elapsed, "cooldown": cooldown},
                )

        # 7. Mode-specific greeting decisions
        return self._decide_mode_greeting(ctx.mode, gaze)

    def _decide_mode_greeting(
        self,
        mode: SocialMode,
        gaze: tuple[float, float] | None,
    ) -> SocialDecision:
        """Resolve mode-specific greeting intent and expression."""
        gaze_target = gaze or (0.0, 0.0)

        if mode == SocialMode.PUBLIC:
            return SocialDecision(
                action=SocialAction.GREET,
                reason_code="PUBLIC_GREETING_ALLOWED",
                gaze_target=gaze_target,
                greeting_intent="formal_welcome",
                expression_hint="polite",
            )

        if mode == SocialMode.SHOP:
            return SocialDecision(
                action=SocialAction.GREET,
                reason_code="SHOP_GREETING_ALLOWED",
                gaze_target=gaze_target,
                greeting_intent="customer_welcome",
                expression_hint="welcoming",
            )

        if mode == SocialMode.HOME:
            return SocialDecision(
                action=SocialAction.GREET,
                reason_code="HOME_GREETING_ALLOWED",
                gaze_target=gaze_target,
                greeting_intent="casual_greeting",
                expression_hint="friendly",
            )

        if mode == SocialMode.WORKSHOP:
            return SocialDecision(
                action=SocialAction.GREET,
                reason_code="WORKSHOP_GREETING_ALLOWED",
                gaze_target=gaze_target,
                greeting_intent="workshop_ack",
                expression_hint="ready",
            )

        if mode == SocialMode.PRIVATE:
            return SocialDecision(
                action=SocialAction.GREET,
                reason_code="PRIVATE_GREETING_ALLOWED",
                gaze_target=gaze_target,
                greeting_intent="personal_greeting",
                expression_hint="warm",
            )

        return SocialDecision(
            action=SocialAction.STAY_SILENT,
            reason_code="UNKNOWN_MODE_SILENCE",
            gaze_target=gaze_target,
        )
