"""Unit tests for the SocialEngine baseline."""

from ailen.core.social import SocialEngine
from ailen.domain.enums import SocialMode
from ailen.domain.social import SocialAction, SocialContext


def test_no_presence_results_in_stay_silent() -> None:
    engine = SocialEngine()
    ctx = SocialContext(presence_state=False, mode=SocialMode.WORKSHOP)
    decision = engine.evaluate(ctx)

    assert decision.action == SocialAction.STAY_SILENT
    assert decision.reason_code == "PRESENCE_ABSENT"


def test_sleep_mode_without_presence_preserves_sleep() -> None:
    engine = SocialEngine()
    ctx = SocialContext(presence_state=False, sleep_state=True)
    decision = engine.evaluate(ctx)

    assert decision.action == SocialAction.SLEEP
    assert decision.reason_code == "SLEEP_PRESERVED"


def test_presence_in_sleep_triggers_wake() -> None:
    engine = SocialEngine()
    ctx = SocialContext(presence_state=True, sleep_state=True, gaze_x=0.1, gaze_y=-0.2)
    decision = engine.evaluate(ctx)

    assert decision.action == SocialAction.WAKE
    assert decision.reason_code == "PRESENCE_WAKE"
    assert decision.gaze_target == (0.1, -0.2)


def test_active_conversation_prevents_interruption() -> None:
    engine = SocialEngine()
    ctx = SocialContext(
        presence_state=True,
        conversation_active=True,
        mode=SocialMode.SHOP,
        is_new_presence=True,
    )
    decision = engine.evaluate(ctx)

    assert decision.action == SocialAction.LOOK_AT
    assert decision.reason_code == "CONVERSATION_ACTIVE"


def test_continuous_presence_does_not_repeat_greeting() -> None:
    engine = SocialEngine()
    ctx = SocialContext(
        presence_state=True,
        is_new_presence=False,
        mode=SocialMode.SHOP,
    )
    decision = engine.evaluate(ctx)

    assert decision.action == SocialAction.LOOK_AT
    assert decision.reason_code == "ALREADY_GREETED_PRESENCE"


def test_greeting_cooldown_prevents_immediate_subsequent_greeting() -> None:
    engine = SocialEngine(default_cooldown_seconds=60.0)
    ctx = SocialContext(
        presence_state=True,
        is_new_presence=True,
        last_greeting_at=100.0,
        current_time=120.0,  # Only 20s elapsed (< 60s)
        greeting_cooldown_seconds=60.0,
        mode=SocialMode.SHOP,
    )
    decision = engine.evaluate(ctx)

    assert decision.action == SocialAction.LOOK_AT
    assert decision.reason_code == "COOLDOWN_ACTIVE"


def test_greeting_allowed_after_cooldown_expires() -> None:
    engine = SocialEngine(default_cooldown_seconds=60.0)
    ctx = SocialContext(
        presence_state=True,
        is_new_presence=True,
        last_greeting_at=100.0,
        current_time=170.0,  # 70s elapsed (> 60s)
        greeting_cooldown_seconds=60.0,
        mode=SocialMode.SHOP,
    )
    decision = engine.evaluate(ctx)

    assert decision.action == SocialAction.GREET
    assert decision.reason_code == "SHOP_GREETING_ALLOWED"
    assert decision.greeting_intent == "customer_welcome"


def test_mode_specific_greeting_intents() -> None:
    engine = SocialEngine()

    # Public mode
    d_pub = engine.evaluate(SocialContext(presence_state=True, is_new_presence=True, mode=SocialMode.PUBLIC))
    assert d_pub.action == SocialAction.GREET
    assert d_pub.reason_code == "PUBLIC_GREETING_ALLOWED"
    assert d_pub.greeting_intent == "formal_welcome"

    # Workshop mode
    d_work = engine.evaluate(SocialContext(presence_state=True, is_new_presence=True, mode=SocialMode.WORKSHOP))
    assert d_work.action == SocialAction.GREET
    assert d_work.reason_code == "WORKSHOP_GREETING_ALLOWED"
    assert d_work.greeting_intent == "workshop_ack"

    # Home mode
    d_home = engine.evaluate(SocialContext(presence_state=True, is_new_presence=True, mode=SocialMode.HOME))
    assert d_home.action == SocialAction.GREET
    assert d_home.reason_code == "HOME_GREETING_ALLOWED"
    assert d_home.greeting_intent == "casual_greeting"

    # Private mode
    d_priv = engine.evaluate(SocialContext(presence_state=True, is_new_presence=True, mode=SocialMode.PRIVATE))
    assert d_priv.action == SocialAction.GREET
    assert d_priv.reason_code == "PRIVATE_GREETING_ALLOWED"
    assert d_priv.greeting_intent == "personal_greeting"


def test_greetings_disabled_globally() -> None:
    engine = SocialEngine(allow_greetings=False)
    ctx = SocialContext(presence_state=True, is_new_presence=True, mode=SocialMode.HOME)
    decision = engine.evaluate(ctx)

    assert decision.action == SocialAction.LOOK_AT
    assert decision.reason_code == "GREETING_DISABLED"
