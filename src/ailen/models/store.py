"""Managed filesystem storage for local model artifacts."""

import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any


class ModelStore:
    """Manages local model artifact files, sidecar metadata and integrity verification."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        if base_dir is not None:
            self._base_dir = Path(base_dir).resolve()
        elif sys.platform == "win32":
            local_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))
            self._base_dir = (Path(local_appdata) / "AILEN" / "models").resolve()
        else:
            xdg_data = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
            self._base_dir = (Path(xdg_data) / "ailen" / "models").resolve()

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def ensure_directory(self) -> None:
        """Create storage directory if not present."""
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_model_id(self, model_id: str) -> str:
        """Validate model_id against path traversal attacks."""
        if not model_id or not model_id.strip():
            raise ValueError("model_id cannot be empty")
        clean = model_id.strip()
        if (
            "/" in clean
            or "\\" in clean
            or ".." in clean
            or "\x00" in clean
            or ":" in clean
            or not re.match(r"^[a-zA-Z0-9_.-]+$", clean)
        ):
            raise ValueError(f"Invalid model_id containing path separators, traversal or invalid chars: {model_id!r}")
        return clean

    def get_model_path(self, model_id: str) -> Path:
        """Resolve absolute path to model artifact file."""
        clean_id = self._sanitize_model_id(model_id)
        path = (self._base_dir / f"{clean_id}.gguf").resolve()
        # Security boundary check
        if not path.is_relative_to(self._base_dir):
            raise ValueError(f"Resolved path escapes base_dir: {path}")
        return path

    def exists(self, model_id: str) -> bool:
        """Check if model artifact exists on disk."""
        try:
            return self.get_model_path(model_id).is_file()
        except ValueError:
            return False

    def get_size(self, model_id: str) -> int:
        """Return size of model artifact in bytes, or 0 if absent."""
        try:
            path = self.get_model_path(model_id)
            return path.stat().st_size if path.is_file() else 0
        except (ValueError, OSError):
            return 0

    def verify(self, model_id: str, expected_sha256: str) -> bool:
        """Compute SHA-256 hash of artifact and compare with expected checksum."""
        try:
            path = self.get_model_path(model_id)
            if not path.is_file():
                return False

            hasher = hashlib.sha256()
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)

            calculated = hasher.hexdigest().lower()
            return calculated == expected_sha256.lower()
        except (ValueError, OSError):
            return False

    def remove(self, model_id: str) -> bool:
        """Remove model artifact and sidecar files."""
        try:
            path = self.get_model_path(model_id)
            if path.is_file():
                path.unlink()
                return True
        except (ValueError, OSError):
            pass
        return False

    def list_installed(self) -> list[dict[str, Any]]:
        """List all model artifacts present in the store."""
        if not self._base_dir.is_dir():
            return []

        installed = []
        for f in sorted(self._base_dir.glob("*.gguf")):
            model_id = f.stem
            installed.append({
                "model_id": model_id,
                "path": str(f),
                "size_bytes": f.stat().st_size,
                "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
            })
        return installed
