"""Runtime model inventory for querying models loaded in decoupled runtimes."""

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


class RuntimeModelInventory:
    """Queries and verifies model artifacts installed in decoupled runtimes (Ollama, llama.cpp)."""

    def __init__(self, timeout: float = 1.0) -> None:
        self.timeout = timeout

    def list_models(self, endpoint: str) -> list[str]:
        """Fetch list of model identifiers loaded/installed in the runtime endpoint."""
        clean_endpoint = endpoint.rstrip("/")
        models: list[str] = []

        # 1. Try standard OpenAI-compatible /models endpoint
        models_url = f"{clean_endpoint}/models"
        try:
            req = urllib.request.Request(models_url, headers={"User-Agent": "AILEN-RuntimeInventory/0.1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    items = data.get("data", [])
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict) and "id" in item:
                                models.append(item["id"])
                            elif isinstance(item, str):
                                models.append(item)
        except Exception as exc:  # noqa: BLE001
            logger.debug("OpenAI /models endpoint probe failed on %s: %s", models_url, exc)

        # 2. If no models found, try Ollama native /api/tags endpoint
        if not models:
            # Handle both http://127.0.0.1:11434 and http://127.0.0.1:11434/v1
            base_url = clean_endpoint.removesuffix("/v1")
            ollama_url = f"{base_url}/api/tags"
            try:
                req = urllib.request.Request(ollama_url, headers={"User-Agent": "AILEN-RuntimeInventory/0.1.0"})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        items = data.get("models", [])
                        if isinstance(items, list):
                            for item in items:
                                if isinstance(item, dict) and "name" in item:
                                    models.append(item["name"])
                                elif isinstance(item, str):
                                    models.append(item)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Ollama /api/tags endpoint probe failed on %s: %s", ollama_url, exc)

        return models


    def is_ollama_endpoint(self, endpoint: str) -> bool:
        """Return True only when the native Ollama tags endpoint responds successfully."""
        base_url = endpoint.rstrip("/").removesuffix("/v1")
        req = urllib.request.Request(
            f"{base_url}/api/tags",
            headers={"User-Agent": "AILEN-RuntimeInventory/0.1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    return False
                data = json.loads(resp.read().decode("utf-8"))
                return isinstance(data.get("models"), list)
        except Exception:  # noqa: BLE001
            return False

    def resolve_model(
        self,
        endpoint: str,
        target_model_id: str,
        aliases: list[str] | None = None,
    ) -> str | None:
        """Return the concrete runtime model ID matching an explicit catalog/config ID.

        Matching is intentionally exact and case-insensitive. Runtime inventories
        must never select a different model merely because it shares a family
        prefix; that would make readiness claims and benchmark results ambiguous.
        """
        installed = self.list_models(endpoint)
        if not installed:
            return None

        by_lower = {model.lower(): model for model in installed}
        candidates = [target_model_id, *(aliases or [])]
        for candidate in candidates:
            normalized = candidate.strip().lower()
            if normalized and normalized in by_lower:
                return by_lower[normalized]
        return None

    def has_model(
        self,
        endpoint: str,
        target_model_id: str,
        aliases: list[str] | None = None,
    ) -> bool:
        """Check whether an explicit model ID/alias exists in the runtime."""
        return self.resolve_model(endpoint, target_model_id, aliases=aliases) is not None
