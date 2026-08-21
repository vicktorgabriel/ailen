"""Secure model downloader with pre-flight disk validation, size capping, and SHA-256 verification."""

import hashlib
import logging
import shutil
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path

from ailen.models.catalog import ModelDescriptor
from ailen.models.store import ModelStore

logger = logging.getLogger(__name__)


class ModelDownloadError(Exception):
    """Raised when model download, verification or size validation fails."""


class ModelDownloader:
    """Safely streams remote model artifacts into the ModelStore with strict verification."""

    def __init__(self, store: ModelStore | None = None) -> None:
        self.store = store or ModelStore()

    def download(
        self,
        descriptor: ModelDescriptor,
        progress_callback: Callable[[int, int], None] | None = None,
        chunk_size: int = 65536,
        timeout: float = 30.0,
    ) -> Path:
        """Download model artifact into ModelStore with preflight check and SHA-256 verification."""
        if chunk_size <= 0:
            raise ValueError(f"chunk_size must be positive, got {chunk_size}")
        if timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        if not descriptor.downloadable:
            raise ModelDownloadError(f"Model '{descriptor.model_id}' is not configured as downloadable")
        if not descriptor.source_url:
            raise ModelDownloadError(f"Model '{descriptor.model_id}' has no source_url")
        if not descriptor.source_url.startswith("https://"):
            raise ModelDownloadError(f"Model '{descriptor.model_id}' source_url must use HTTPS: {descriptor.source_url}")
        if not descriptor.sha256:
            raise ModelDownloadError(f"Model '{descriptor.model_id}' has no SHA-256 checksum defined")

        self.store.ensure_directory()
        target_path = self.store.get_model_path(descriptor.model_id)
        if target_path.exists():
            if self.store.verify(descriptor.model_id, descriptor.sha256):
                return target_path
            raise ModelDownloadError(
                f"Existing artifact for '{descriptor.model_id}' failed checksum verification; remove it before re-downloading"
            )

        # 1. Preflight disk space verification
        free_bytes = shutil.disk_usage(self.store.base_dir).free
        required_bytes = descriptor.disk_size_bytes + (100 * 1024 * 1024)  # 100 MB safety buffer
        if free_bytes < required_bytes:
            raise ModelDownloadError(
                f"Insufficient disk space in '{self.store.base_dir}'. "
                f"Required: {required_bytes // (1024 * 1024)} MB, Free: {free_bytes // (1024 * 1024)} MB"
            )

        # 2. Setup temporary download file
        tmp_id = uuid.uuid4().hex[:8]
        tmp_path = target_path.with_name(f"{target_path.name}.tmp.{tmp_id}")

        hasher = hashlib.sha256()
        bytes_downloaded = 0
        total_bytes = descriptor.disk_size_bytes
        max_allowed_bytes = int(descriptor.disk_size_bytes * 1.10) if descriptor.disk_size_bytes > 0 else 50_000_000_000

        req = urllib.request.Request(
            descriptor.source_url,
            headers={"User-Agent": "AILEN-ModelDownloader/0.1.0"},
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                # Validate redirect didn't downgrade to insecure HTTP
                final_url = response.geturl()
                if not final_url.startswith("https://"):
                    raise ModelDownloadError(f"Redirected to insecure non-HTTPS URL: {final_url}")

                content_length = response.headers.get("Content-Length")
                if content_length and content_length.isdigit():
                    cl_val = int(content_length)
                    total_bytes = cl_val
                    if cl_val > max_allowed_bytes:
                        raise ModelDownloadError(
                            f"Content-Length ({cl_val} bytes) exceeds maximum allowed size ({max_allowed_bytes} bytes)"
                        )

                with tmp_path.open("wb") as out_file:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        hasher.update(chunk)
                        bytes_downloaded += len(chunk)

                        if bytes_downloaded > max_allowed_bytes:
                            raise ModelDownloadError(
                                f"Downloaded bytes ({bytes_downloaded}) exceeded maximum allowed limit ({max_allowed_bytes})"
                            )

                        if progress_callback:
                            try:
                                progress_callback(bytes_downloaded, total_bytes)
                            except Exception:  # noqa: BLE001, S110
                                pass

            # 3. Exact Size Validation
            if descriptor.disk_size_bytes > 0 and bytes_downloaded != descriptor.disk_size_bytes:
                raise ModelDownloadError(
                    f"Size mismatch for '{descriptor.model_id}': expected {descriptor.disk_size_bytes} bytes, got {bytes_downloaded} bytes"
                )

            # 4. Verify SHA-256 Checksum (Fail-closed)
            computed_sha = hasher.hexdigest().lower()
            expected_sha = descriptor.sha256.lower()

            if computed_sha != expected_sha:
                logger.error(
                    "SHA-256 mismatch for '%s'! Computed: %s, Expected: %s",
                    descriptor.model_id,
                    computed_sha,
                    expected_sha,
                )
                raise ModelDownloadError(
                    f"Integrity check failed for '{descriptor.model_id}'. "
                    f"Checksum mismatch (expected {expected_sha}, got {computed_sha})"
                )

            # 5. Atomic rename upon successful size and checksum verification
            tmp_path.replace(target_path)
            logger.info("Successfully downloaded and verified '%s' at %s", descriptor.model_id, target_path)
            return target_path

        except Exception as e:
            # Clean up temporary artifact (fail-closed)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            if isinstance(e, (ModelDownloadError, ValueError)):
                raise
            raise ModelDownloadError(f"Download failed for '{descriptor.model_id}': {e}") from e
