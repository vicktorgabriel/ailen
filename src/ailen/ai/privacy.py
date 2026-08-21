"""Deterministic outbound privacy policy for network and cloud destinations.

Controls what information is authorized to leave the local node.
Ensures that RESTRICTED or PRIVATE data is never sent to Cloud/Internet,
and only sent to LAN Brain if the LAN node is explicitly marked as trusted.
"""

from ailen.ai.contracts import AiRequest
from ailen.domain.enums import PrivacyLevel


class OutboundPrivacyPolicy:
    """Evaluates and enforces data boundaries for network/cloud destinations."""

    @classmethod
    def is_destination_allowed(
        cls,
        privacy_level: PrivacyLevel,
        destination: str,
        lan_trusted: bool = False,
    ) -> tuple[bool, str]:
        """Check if sending data with privacy_level to destination is allowed."""
        dest = destination.lower().strip()

        # Rule and Local execution: always allowed
        if dest in ("rule", "local"):
            return True, "LOCAL_EXECUTION_ALLOWED"

        # LAN Brain execution
        if dest == "lan_brain":
            if lan_trusted:
                return True, "LAN_TRUSTED_ALLOWED"
            # If untrusted LAN, only PUBLIC data may leave
            if privacy_level is PrivacyLevel.PUBLIC:
                return True, "LAN_PUBLIC_ALLOWED"
            return False, "UNTRUSTED_LAN_BLOCKED"

        # Cloud execution (Internet)
        if dest == "cloud":
            if privacy_level is PrivacyLevel.PUBLIC:
                return True, "CLOUD_PUBLIC_ALLOWED"
            if privacy_level is PrivacyLevel.RESTRICTED:
                return False, "RESTRICTED_CLOUD_BLOCKED"
            return False, "PRIVATE_REMOTE_BLOCKED"

        # Degraded / Unknown
        if dest == "degraded":
            return True, "DEGRADED_ALLOWED"

        return False, "UNKNOWN_DESTINATION_BLOCKED"

    @classmethod
    def sanitize_request_for_destination(
        cls,
        request: AiRequest,
        destination: str,
        lan_trusted: bool = False,
    ) -> AiRequest:
        """Validate outbound privacy for a destination and fail closed if blocked.

        A request is never silently downgraded from PRIVATE/RESTRICTED to PUBLIC.
        The router should normally prevent these routes; this guard protects direct
        callers and future integrations from leaking message content accidentally.
        """
        dest = destination.lower().strip()
        is_allowed, reason = cls.is_destination_allowed(
            request.privacy_level,
            dest,
            lan_trusted=lan_trusted,
        )
        if not is_allowed:
            raise PermissionError(f"Outbound AI request blocked: {reason}")
        return request
