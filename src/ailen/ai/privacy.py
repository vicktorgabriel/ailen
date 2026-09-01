"""Deterministic outbound privacy policy for local, LAN and remote destinations.

Controls what information is authorized to leave the local node.
Ensures that RESTRICTED or PRIVATE data is never sent to Cloud/Internet,
and only sent to LAN Brain if the LAN node is explicitly marked as trusted.
"""

import re
from dataclasses import replace
from typing import ClassVar

from ailen.ai.contracts import AiRequest
from ailen.domain.enums import PrivacyLevel


class OutboundPrivacyPolicy:
    """Evaluate and enforce data boundaries for local, LAN and remote destinations."""

    _REMOTE_PREFIX: ClassVar[str] = "remote:"
    _SAFE_REMOTE_METADATA: ClassVar[frozenset[str]] = frozenset({
        "input_modality",
        "reasoning_effort",
        "voice_output",
    })
    _SAFE_EXPRESSION_ID: ClassVar[re.Pattern[str]] = re.compile(
        r"^[a-z][a-z0-9_]{0,63}$"
    )

    @classmethod
    def _sanitize_remote_request(cls, request: AiRequest) -> AiRequest:
        """Reduce an outbound request to current-turn public protocol data.

        This is the final enforcement boundary used even when a caller already
        claims to have built a ``SANITIZED_REMOTE`` request. It deliberately
        rebuilds the system prompt instead of trying to redact arbitrary prose.
        """
        source_metadata = dict(request.metadata)
        safe_metadata = {
            key: source_metadata[key]
            for key in cls._SAFE_REMOTE_METADATA
            if key in source_metadata
            and isinstance(source_metadata[key], (str, bool, int, float))
        }
        safe_metadata["outbound_sanitized_private"] = (
            request.privacy_level is PrivacyLevel.PRIVATE
        )

        system_parts = [
            (
                "Respondé al turno actual en español rioplatense natural, de forma breve y directa. "
                "No inventes acciones, herramientas, recuerdos ni datos actuales sin evidencia incluida en este turno."
            )
        ]
        if safe_metadata.get("voice_output"):
            system_parts.append(
                "La salida será oral: usá frases completas, sin Markdown, listas, emojis ni cierres de soporte rutinarios."
            )
        if safe_metadata.get("input_modality") == "voice":
            system_parts.append(
                "La entrada proviene de STT: corregí sólo errores obvios y pedí repetir si no se entiende."
            )

        raw_expressions = source_metadata.get("conversational_expressions")
        if safe_metadata.get("voice_output") and isinstance(raw_expressions, list):
            expressions = [
                item
                for item in raw_expressions
                if isinstance(item, str) and cls._SAFE_EXPRESSION_ID.fullmatch(item)
            ][:64]
            if expressions:
                system_parts.append(
                    "Podés anteponer un único marcador no pronunciable [[face:id]]; IDs permitidos: "
                    + ", ".join(expressions)
                    + ". Omitilo si no corresponde."
                )
                safe_metadata["conversational_expressions"] = expressions

        current_user_message = next(
            (message for message in reversed(request.messages) if message.role == "user"),
            None,
        )
        return replace(
            request,
            system_context=" ".join(system_parts),
            messages=[current_user_message] if current_user_message is not None else [],
            retrieved_memory=[],
            allowed_tools=[],
            metadata=safe_metadata,
        )

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

        # Named remote provider execution (Internet)
        if dest.startswith(cls._REMOTE_PREFIX) and len(dest) > len(cls._REMOTE_PREFIX):
            if privacy_level is PrivacyLevel.PUBLIC:
                return True, "REMOTE_PUBLIC_ALLOWED"
            if privacy_level is PrivacyLevel.RESTRICTED:
                return False, "RESTRICTED_REMOTE_BLOCKED"
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
        allow_sanitized_private: bool = False,
    ) -> AiRequest:
        """Validate outbound privacy for a destination and fail closed if blocked.

        A request is never silently downgraded from PRIVATE/RESTRICTED to PUBLIC.
        The router should normally prevent these routes; this guard protects direct
        callers and future integrations from leaking message content accidentally.
        """
        dest = destination.lower().strip()
        if (
            allow_sanitized_private
            and request.privacy_level is PrivacyLevel.PRIVATE
            and dest.startswith(cls._REMOTE_PREFIX)
            and len(dest) > len(cls._REMOTE_PREFIX)
        ):
            return cls._sanitize_remote_request(request)
        is_allowed, reason = cls.is_destination_allowed(
            request.privacy_level,
            dest,
            lan_trusted=lan_trusted,
        )
        if not is_allowed:
            raise PermissionError(f"Outbound AI request blocked: {reason}")
        if dest.startswith(cls._REMOTE_PREFIX) and len(dest) > len(cls._REMOTE_PREFIX):
            return cls._sanitize_remote_request(request)
        return request
