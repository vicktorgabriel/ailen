"""Context builder for AI requests.

Constructs minimal, privacy-compliant prompts for AI inference from SQLite repositories
and session history. Applies SocialPrivacyPolicy and OutboundPrivacyPolicy deterministically.
"""

import uuid
from typing import Any

from ailen.ai.contracts import AiRequest, ChatMessage
from ailen.ai.privacy import OutboundPrivacyPolicy
from ailen.core.privacy import SocialPrivacyPolicy
from ailen.domain.enums import PrivacyLevel, SocialMode
from ailen.memory.repository import MemoryRepository


class AiContextBuilder:
    """Builds clean, privacy-bounded AiRequest payloads."""

    def __init__(
        self,
        repository: MemoryRepository | None = None,
        default_identity_name: str = "Asistente",
        max_recent_messages: int = 6,
        max_memories: int = 5,
        max_facts: int = 5,
        max_char_budget: int = 4000,
        request_timeout_seconds: float = 10.0,
        max_output_tokens: int = 512,
    ) -> None:
        self.repository = repository
        self.default_identity_name = default_identity_name
        self.max_recent_messages = max_recent_messages
        self.max_memories = max_memories
        self.max_facts = max_facts
        self.max_char_budget = max_char_budget
        self.request_timeout_seconds = max(0.1, request_timeout_seconds)
        self.max_output_tokens = max(1, max_output_tokens)

    def build_request(
        self,
        user_message: str,
        session_id: str | None = None,
        mode: SocialMode = SocialMode.WORKSHOP,
        privacy_level: PrivacyLevel = PrivacyLevel.PRIVATE,
        identity_name: str | None = None,
        destination: str = "local",
        lan_trusted: bool = True,
        allowed_tools: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AiRequest:
        """Construct a bounded, privacy-filtered AiRequest."""
        name = identity_name or self.default_identity_name
        system_context = (
            f"Eres {name}, un asistente inteligente físico y local. "
            f"Modo actual: {mode.value}. Sé conciso, claro y directo en español."
        )
        request_metadata = metadata or {}
        if request_metadata.get("voice_output"):
            system_context += (
                " La respuesta se reproducirá por voz: usa frases breves, sin Markdown, "
                "sin emojis, sin bloques de código y sin símbolos decorativos salvo que te los pidan."
            )

        messages: list[ChatMessage] = []
        retrieved_memories: list[str] = []

        # 1. Load conversation history from session
        if self.repository and session_id:
            try:
                db_msgs = self.repository.get_session_messages(session_id, limit=self.max_recent_messages)
                for msg in db_msgs:
                    messages.append(ChatMessage(role=msg.role, content=msg.content))
            except Exception:  # noqa: BLE001, S110
                pass

        # 2. Append current user message
        messages.append(ChatMessage(role="user", content=user_message))

        # 3. Retrieve and sanitize domain memories according to SocialPrivacyPolicy
        if self.repository:
            try:
                raw_memories = self.repository.get_recent_memories(limit=self.max_memories)
                safe_memories = SocialPrivacyPolicy.filter_memories(raw_memories, mode)
                retrieved_memories.extend([m.content for m in safe_memories])
            except Exception:  # noqa: BLE001, S110
                pass

            # 4. Retrieve and sanitize business facts
            try:
                raw_facts = self.repository.get_business_facts()
                safe_facts = SocialPrivacyPolicy.filter_business_facts(raw_facts, mode)
                retrieved_memories.extend(
                    [f"Dato de negocio: {f.key}: {f.value}" for f in safe_facts[: self.max_facts]]
                )
            except Exception:  # noqa: BLE001, S110
                pass

        # 5. Build initial raw AiRequest
        request_id = f"req-{uuid.uuid4().hex[:12]}"
        req = AiRequest(
            request_id=request_id,
            system_context=system_context,
            messages=messages,
            retrieved_memory=retrieved_memories,
            mode=mode,
            allowed_tools=allowed_tools or [],
            max_output_tokens=self.max_output_tokens,
            timeout_seconds=self.request_timeout_seconds,
            privacy_level=privacy_level,
            metadata=request_metadata,
        )

        # 6. Apply Outbound Privacy Policy for destination (e.g. Cloud or untrusted LAN)
        sanitized_req = OutboundPrivacyPolicy.sanitize_request_for_destination(
            req,
            destination=destination,
            lan_trusted=lan_trusted,
        )

        # 7. Truncate context if budget exceeded
        self._enforce_character_budget(sanitized_req)

        return sanitized_req

    def _enforce_character_budget(self, request: AiRequest) -> None:
        """Bound system, conversation and retrieved context without dropping current input."""
        if self.max_char_budget <= 0:
            request.messages = request.messages[-1:]
            request.retrieved_memory = []
            return

        def total_chars() -> int:
            return (
                len(request.system_context)
                + sum(len(m.content) for m in request.messages)
                + sum(len(item) for item in request.retrieved_memory)
            )

        # Drop oldest history first, always preserving the current/final message.
        while total_chars() > self.max_char_budget and len(request.messages) > 1:
            request.messages.pop(0)

        # Then drop lowest-priority retrieved items from the tail.
        while total_chars() > self.max_char_budget and request.retrieved_memory:
            request.retrieved_memory.pop()

        # As a last resort truncate system context; never truncate the user's current message here.
        remaining_for_system = self.max_char_budget - sum(len(m.content) for m in request.messages)
        if remaining_for_system < len(request.system_context):
            request.system_context = request.system_context[: max(0, remaining_for_system)]
