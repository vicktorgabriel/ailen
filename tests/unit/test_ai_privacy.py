"""Unit tests for OutboundPrivacyPolicy."""

import pytest

from ailen.ai.contracts import AiRequest, ChatMessage
from ailen.ai.privacy import OutboundPrivacyPolicy
from ailen.domain.enums import PrivacyLevel, SocialMode


def test_outbound_privacy_local_always_allowed() -> None:
    for pl in (PrivacyLevel.PUBLIC, PrivacyLevel.RESTRICTED, PrivacyLevel.PRIVATE):
        allowed, reason = OutboundPrivacyPolicy.is_destination_allowed(pl, "local")
        assert allowed is True
        assert reason == "LOCAL_EXECUTION_ALLOWED"

        allowed, reason = OutboundPrivacyPolicy.is_destination_allowed(pl, "rule")
        assert allowed is True


def test_outbound_privacy_lan_brain() -> None:
    # Trusted LAN allows all levels
    for pl in (PrivacyLevel.PUBLIC, PrivacyLevel.RESTRICTED, PrivacyLevel.PRIVATE):
        allowed, reason = OutboundPrivacyPolicy.is_destination_allowed(pl, "lan_brain", lan_trusted=True)
        assert allowed is True
        assert reason == "LAN_TRUSTED_ALLOWED"

    # Untrusted LAN allows only PUBLIC
    allowed_pub, _ = OutboundPrivacyPolicy.is_destination_allowed(PrivacyLevel.PUBLIC, "lan_brain", lan_trusted=False)
    assert allowed_pub is True

    allowed_priv, reason_priv = OutboundPrivacyPolicy.is_destination_allowed(
        PrivacyLevel.PRIVATE, "lan_brain", lan_trusted=False
    )
    assert allowed_priv is False
    assert reason_priv == "UNTRUSTED_LAN_BLOCKED"


def test_outbound_privacy_cloud_strict_isolation() -> None:
    # Public is allowed
    allowed_pub, reason_pub = OutboundPrivacyPolicy.is_destination_allowed(PrivacyLevel.PUBLIC, "cloud")
    assert allowed_pub is True
    assert reason_pub == "CLOUD_PUBLIC_ALLOWED"

    # Restricted is blocked
    allowed_res, reason_res = OutboundPrivacyPolicy.is_destination_allowed(PrivacyLevel.RESTRICTED, "cloud")
    assert allowed_res is False
    assert reason_res == "RESTRICTED_CLOUD_BLOCKED"

    # Private is strictly blocked
    allowed_priv, reason_priv = OutboundPrivacyPolicy.is_destination_allowed(PrivacyLevel.PRIVATE, "cloud")
    assert allowed_priv is False
    assert reason_priv == "PRIVATE_REMOTE_BLOCKED"


def test_private_request_to_cloud_fails_closed() -> None:
    req = AiRequest(
        request_id="req-123",
        system_context="Sys context",
        messages=[ChatMessage(role="user", content="Hello")],
        retrieved_memory=["Private address: 123 Street"],
        mode=SocialMode.HOME,
        privacy_level=PrivacyLevel.PRIVATE,
    )

    with pytest.raises(PermissionError, match="PRIVATE_REMOTE_BLOCKED"):
        OutboundPrivacyPolicy.sanitize_request_for_destination(req, "cloud")


def test_restricted_request_to_untrusted_lan_fails_closed() -> None:
    req = AiRequest(
        request_id="req-456",
        messages=[ChatMessage(role="user", content="Dato interno")],
        privacy_level=PrivacyLevel.RESTRICTED,
    )
    with pytest.raises(PermissionError, match="UNTRUSTED_LAN_BLOCKED"):
        OutboundPrivacyPolicy.sanitize_request_for_destination(
            req, "lan_brain", lan_trusted=False
        )
