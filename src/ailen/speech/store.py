"""Managed filesystem storage for local speech assets (STT models and TTS voices)."""

import hashlib
import os
import re
import sys
from pathlib import Path

from ailen.speech.catalog import SpeechAssetDescriptor, SpeechAssetType


class SpeechAssetStore:
    """Manages local speech assets in ~/.local/share/ailen/speech/{stt,tts}/ with path security."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        if base_dir is not None:
            self._base_dir = Path(base_dir).resolve()
        elif sys.platform == "win32":
            local_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))
            self._base_dir = (Path(local_appdata) / "AILEN" / "speech").resolve()
        else:
            xdg_data = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
            self._base_dir = (Path(xdg_data) / "ailen" / "speech").resolve()

        self._stt_dir = (self._base_dir / "stt").resolve()
        self._tts_dir = (self._base_dir / "tts").resolve()

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    @property
    def stt_dir(self) -> Path:
        return self._stt_dir

    @property
    def tts_dir(self) -> Path:
        return self._tts_dir

    def ensure_directories(self) -> None:
        """Create storage directories if they do not exist."""
        self._stt_dir.mkdir(parents=True, exist_ok=True)
        self._tts_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_asset_id(self, asset_id: str) -> str:
        """Validate asset_id against path traversal attacks."""
        if not asset_id or not asset_id.strip():
            raise ValueError("asset_id cannot be empty")
        clean = asset_id.strip()
        if (
            "/" in clean
            or "\\" in clean
            or ".." in clean
            or "\x00" in clean
            or ":" in clean
            or not re.match(r"^[a-zA-Z0-9_.-]+$", clean)
        ):
            raise ValueError(f"Invalid asset_id containing path separators or invalid chars: {asset_id!r}")
        return clean

    def get_asset_path(self, descriptor: SpeechAssetDescriptor) -> Path:
        """Resolve absolute filesystem path for speech asset."""
        clean_id = self._sanitize_asset_id(descriptor.asset_id)

        if descriptor.engine == "vosk":
            # For Vosk, the extracted model directory or archive
            target = (self._stt_dir / clean_id).resolve()
            if not target.is_relative_to(self._stt_dir):
                raise ValueError(f"Resolved path escapes stt_dir: {target}")
            return target

        if descriptor.engine == "whisper_cpp":
            filename = clean_id if clean_id.endswith(".bin") else f"{clean_id}.bin"
            target = (self._stt_dir / filename).resolve()
            if not target.is_relative_to(self._stt_dir):
                raise ValueError(f"Resolved path escapes stt_dir: {target}")
            return target

        if descriptor.engine == "piper":
            if descriptor.asset_type == SpeechAssetType.TTS_CONFIG:
                filename = clean_id if clean_id.endswith((".onnx.json", ".json")) else f"{clean_id}.onnx.json"
                if not filename.endswith(".json"):
                    filename = f"{filename}.json"
            else:
                filename = clean_id if clean_id.endswith(".onnx") else f"{clean_id}.onnx"
            target = (self._tts_dir / filename).resolve()
            if not target.is_relative_to(self._tts_dir):
                raise ValueError(f"Resolved path escapes tts_dir: {target}")
            return target

        # Default fallback
        target = (self._base_dir / clean_id).resolve()
        if not target.is_relative_to(self._base_dir):
            raise ValueError(f"Resolved path escapes base_dir: {target}")
        return target

    def get_archive_path(self, descriptor: SpeechAssetDescriptor) -> Path:
        """Resolve path for downloaded zip archives before extraction (e.g. Vosk)."""
        clean_id = self._sanitize_asset_id(descriptor.asset_id)
        target = (self._stt_dir / f"{clean_id}.zip").resolve()
        if not target.is_relative_to(self._stt_dir):
            raise ValueError(f"Resolved path escapes stt_dir: {target}")
        return target

    def exists(self, descriptor: SpeechAssetDescriptor) -> bool:
        """Check if asset exists on disk (file or non-empty directory)."""
        try:
            path = self.get_asset_path(descriptor)
            if path.is_dir():
                # Directory exists and has files inside
                return any(path.iterdir())
            return path.is_file()
        except (OSError, ValueError):
            return False

    def verify(self, descriptor: SpeechAssetDescriptor) -> bool:
        """Verify checksum of asset."""
        if descriptor.engine == "vosk":
            # The downloaded archive is the integrity authority for extracted Vosk
            # directories. A directory alone cannot prove it still matches the
            # catalog artifact, so verification fails closed when the archive is
            # missing or corrupt.
            archive = self.get_archive_path(descriptor)
            if not archive.is_file():
                return False
            h = hashlib.sha256()
            with archive.open("rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest().lower() == descriptor.sha256.lower()

        path = self.get_asset_path(descriptor)
        if not path.is_file():
            return False

        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest().lower() == descriptor.sha256.lower()
