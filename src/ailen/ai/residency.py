"""Model residency and single primary model stability policy."""

from typing import Any

from ailen.domain.enums import InferenceProfile


class ModelResidencyPolicy:
    """Enforces stable model residency during an AILEN session, preventing model hopping."""

    ALLOWED_SWITCH_REASONS = frozenset({
        "STARTUP",
        "PROFILE_CHANGE",
        "BACKEND_FAILOVER",
        "ADMIN_OVERRIDE",
        "NEW_SESSION",
    })

    def __init__(
        self,
        primary_model: str | None = None,
        keep_alive: str | None = None,
        inference_profile: InferenceProfile = InferenceProfile.BALANCED,
    ) -> None:
        self._primary_model = primary_model
        self._custom_keep_alive = keep_alive
        self._inference_profile = inference_profile

    @property
    def primary_model(self) -> str | None:
        return self._primary_model

    @property
    def keep_alive(self) -> str:
        if self._custom_keep_alive:
            return self._custom_keep_alive
        return self.get_default_keep_alive(self._inference_profile)

    @staticmethod
    def get_default_keep_alive(profile: InferenceProfile) -> str:
        """Derive standard Ollama keep_alive duration based on inference profile."""
        if profile == InferenceProfile.RULE_ONLY:
            return "0"
        if profile == InferenceProfile.FAST:
            return "5m"
        if profile == InferenceProfile.BALANCED:
            return "15m"
        if profile == InferenceProfile.QUALITY:
            return "30m"
        return "15m"

    def can_switch_model(self, target_model: str, reason: str) -> tuple[bool, str]:
        """Validate whether a model change is allowed under the anti-hopping policy."""
        if not self._primary_model or self._primary_model == target_model:
            return True, "SAME_OR_INITIAL_MODEL"

        clean_reason = reason.strip().upper()
        if clean_reason in self.ALLOWED_SWITCH_REASONS:
            return True, f"ALLOWED_REASON_{clean_reason}"

        return (
            False,
            (
                f"MODEL_HOPPING_PROHIBITED: Switching from '{self._primary_model}' to '{target_model}' "
                f"for reason '{reason}' is blocked to prevent cold-starts and VRAM/RAM churn."
            ),
        )

    def set_primary_model(self, model_id: str, reason: str = "STARTUP") -> None:
        """Assign or switch primary model if allowed by policy."""
        allowed, msg = self.can_switch_model(model_id, reason)
        if not allowed:
            raise PermissionError(msg)
        self._primary_model = model_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_model": self._primary_model,
            "keep_alive": self.keep_alive,
            "inference_profile": self._inference_profile.value,
        }
