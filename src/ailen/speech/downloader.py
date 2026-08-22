"""Secure downloader for speech models and voice artifacts."""

import hashlib
import logging
import shutil
import stat
import urllib.request
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path

from ailen.speech.catalog import SpeechAssetCatalog, SpeechAssetDescriptor
from ailen.speech.store import SpeechAssetStore

logger = logging.getLogger(__name__)


class SpeechDownloadError(Exception):
    """Raised when speech asset download or verification fails."""


class SpeechAssetDownloader:
    """Safely streams remote speech assets into SpeechAssetStore with strict checksum verification."""

    def __init__(self, store: SpeechAssetStore | None = None, catalog: SpeechAssetCatalog | None = None) -> None:
        self.store = store or SpeechAssetStore()
        self.catalog = catalog or SpeechAssetCatalog()

    def download(
        self,
        descriptor: SpeechAssetDescriptor,
        progress_callback: Callable[[int, int], None] | None = None,
        chunk_size: int = 65536,
        timeout: float = 30.0,
        download_associated: bool = True,
    ) -> Path:
        """Download and verify speech asset."""
        if chunk_size <= 0:
            raise ValueError(f"chunk_size must be positive, got {chunk_size}")
        if timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        if not descriptor.downloadable:
            raise SpeechDownloadError(f"Asset '{descriptor.asset_id}' is not marked downloadable")
        if not descriptor.source_url.startswith("https://"):
            raise SpeechDownloadError(f"Asset '{descriptor.asset_id}' must use HTTPS: {descriptor.source_url}")
        if not descriptor.sha256 or len(descriptor.sha256) != 64:
            raise SpeechDownloadError(f"Asset '{descriptor.asset_id}' has invalid SHA-256 checksum")

        self.store.ensure_directories()
        target_path = self.store.get_asset_path(descriptor)

        # If already exists and verifies, return
        if self.store.exists(descriptor):
            if self.store.verify(descriptor):
                if download_associated and descriptor.associated_config_id:
                    self._download_associated_config(descriptor.associated_config_id, timeout=timeout)
                return target_path
            # Corrupt existing asset
            logger.warning("Existing asset '%s' failed verification, re-downloading...", descriptor.asset_id)

        # 1. Disk space preflight
        free_bytes = shutil.disk_usage(self.store.base_dir).free
        required_bytes = descriptor.expected_size_bytes + (50 * 1024 * 1024)
        if free_bytes < required_bytes:
            raise SpeechDownloadError(
                f"Insufficient disk space for '{descriptor.asset_id}': requires {required_bytes / (1024 * 1024):.1f} MB, "
                f"available {free_bytes / (1024 * 1024):.1f} MB"
            )

        # 2. Download to temporary file
        is_zip = descriptor.source_url.endswith(".zip")
        parent_dir = self.store.stt_dir if descriptor.engine in ("vosk", "whisper_cpp") else self.store.tts_dir
        tmp_filename = f".download-{uuid.uuid4().hex}.tmp"
        tmp_path = parent_dir / tmp_filename

        max_allowed_bytes = int(descriptor.expected_size_bytes * 1.15) + (1024 * 1024)
        hasher = hashlib.sha256()
        downloaded_bytes = 0

        req = urllib.request.Request(
            descriptor.source_url,
            headers={"User-Agent": "AILEN-SpeechDownloader/0.1.0"},
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp, tmp_path.open("wb") as out_file:
                # Disallow silent redirect from HTTPS to HTTP.
                final_url = resp.geturl() if hasattr(resp, "geturl") else getattr(resp, "url", "")
                if not isinstance(final_url, str):
                    fallback_url = getattr(resp, "url", "")
                    final_url = fallback_url if isinstance(fallback_url, str) else ""
                if final_url and not final_url.startswith("https://"):
                    raise SpeechDownloadError(f"Insecure redirect to non-HTTPS URL: {final_url}")

                # Reject an explicitly reported length that disagrees with the
                # catalog before writing the artifact. Some servers omit the
                # header, so exact byte count is also enforced after streaming.
                content_length: int | None = None
                headers = getattr(resp, "headers", None)
                if headers is not None:
                    raw_length = headers.get("Content-Length")
                    if isinstance(raw_length, str) and raw_length.isdigit():
                        content_length = int(raw_length)
                if content_length is not None and content_length != descriptor.expected_size_bytes:
                    raise SpeechDownloadError(
                        f"Content-Length mismatch for '{descriptor.asset_id}': "
                        f"expected {descriptor.expected_size_bytes}, got {content_length}"
                    )

                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    downloaded_bytes += len(chunk)
                    if downloaded_bytes > max_allowed_bytes:
                        raise SpeechDownloadError(
                            f"Downloaded bytes exceeded maximum allowed ({downloaded_bytes} > {max_allowed_bytes})"
                        )
                    hasher.update(chunk)
                    out_file.write(chunk)

                    if progress_callback:
                        progress_callback(downloaded_bytes, descriptor.expected_size_bytes)

            # 3. Exact size and checksum verification
            if downloaded_bytes != descriptor.expected_size_bytes:
                raise SpeechDownloadError(
                    f"Size mismatch for '{descriptor.asset_id}': expected "
                    f"{descriptor.expected_size_bytes}, got {downloaded_bytes}"
                )

            actual_sha = hasher.hexdigest().lower()
            if actual_sha != descriptor.sha256.lower():
                raise SpeechDownloadError(
                    f"Checksum mismatch for '{descriptor.asset_id}': expected {descriptor.sha256}, got {actual_sha}"
                )

            # 4. Handle ZIP unpack or direct rename
            if is_zip and descriptor.engine == "vosk":
                archive_path = self.store.get_archive_path(descriptor)
                tmp_path.replace(archive_path)
                self._safe_extract_zip(
                    archive_path,
                    target_path,
                    max_uncompressed_bytes=max(
                        descriptor.expected_size_bytes * 10,
                        descriptor.expected_size_bytes + 100 * 1024 * 1024,
                    ),
                )
            else:
                tmp_path.replace(target_path)

            logger.info("Successfully downloaded and verified speech asset: %s", descriptor.asset_id)

            # 5. Download associated config if required (e.g. onnx.json for Piper)
            if download_associated and descriptor.associated_config_id:
                self._download_associated_config(descriptor.associated_config_id, timeout=timeout)

            return target_path

        except Exception:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise

    def _safe_extract_zip(
        self,
        archive_path: Path,
        target_dir: Path,
        max_uncompressed_bytes: int,
    ) -> None:
        """Validate and transactionally extract a ZIP without traversal/bomb surprises."""
        staging = target_dir.with_name(f".{target_dir.name}.extract-{uuid.uuid4().hex}")
        staging.mkdir(parents=True, exist_ok=False)
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                members = zf.infolist()
                total_uncompressed = 0
                for member in members:
                    member_path = Path(member.filename)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        raise SpeechDownloadError(
                            f"Malicious archive member path detected: {member.filename}"
                        )

                    unix_mode = (member.external_attr >> 16) & 0xFFFF
                    if stat.S_ISLNK(unix_mode):
                        raise SpeechDownloadError(
                            f"Symlink archive entries are not allowed: {member.filename}"
                        )

                    total_uncompressed += max(0, member.file_size)
                    if total_uncompressed > max_uncompressed_bytes:
                        raise SpeechDownloadError(
                            "Archive expands beyond the configured safety limit: "
                            f"{total_uncompressed} > {max_uncompressed_bytes}"
                        )

                    extracted_dest = (staging / member.filename).resolve()
                    if not extracted_dest.is_relative_to(staging.resolve()):
                        raise SpeechDownloadError(
                            f"Archive entry escapes target directory: {member.filename}"
                        )

                # Extract only after every member has passed validation.
                for member in members:
                    zf.extract(member, staging)

            # Vosk archives normally contain one top-level folder. Flatten it so
            # the configured model path points directly at the model root.
            children = list(staging.iterdir())
            subdirs = [p for p in children if p.is_dir()]
            files = [p for p in children if p.is_file()]
            if len(subdirs) == 1 and not files:
                nested = subdirs[0]
                flattened = staging.with_name(f"{staging.name}-flat")
                nested.replace(flattened)
                shutil.rmtree(staging)
                staging = flattened

            if target_dir.exists():
                if target_dir.is_dir() and not target_dir.is_symlink():
                    shutil.rmtree(target_dir)
                else:
                    target_dir.unlink()
            staging.replace(target_dir)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise

    def _download_associated_config(self, config_id: str, timeout: float = 30.0) -> None:
        """Download associated TTS config file."""
        desc = self.catalog.get(config_id)
        if desc and not self.store.exists(desc):
            logger.info("Downloading associated config: %s", config_id)
            self.download(desc, download_associated=False, timeout=timeout)
