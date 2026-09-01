"""Side-effect-free construction of the signed update vertical."""

from __future__ import annotations

import platform as host_platform
import stat
from dataclasses import dataclass
from pathlib import Path

from ailen.core.config import AILENConfig, validate_config
from ailen.updates.activation import (
    AppliancePaths,
    HealthGateResult,
    PreparedRelease,
    ReleaseActivator,
    SafeReleaseExtractor,
)
from ailen.updates.artifact_store import ContentAddressedArtifactStore
from ailen.updates.contracts import ArtifactSpec, ReleaseManifest, UpdateChannel
from ailen.updates.downloader import HttpsArtifactDownloader
from ailen.updates.journal import OperationJournal
from ailen.updates.service import DisabledUpdateService, LocalUpdateService
from ailen.updates.signatures import OpenSslEd25519Verifier, VerifiedManifestLoader
from ailen.updates.source import HttpsByteFetcher, HttpsReleaseSource
from ailen.version import get_version

# Transitional facts for the current Lab image.  The appliance vertical will
# replace these defaults with the signed installation record and live DB schema.
_CURRENT_DB_SCHEMA = 4
_CURRENT_RELEASE_SEQUENCE = 401000


@dataclass(frozen=True)
class UpdateRuntimeFacts:
    """Non-secret installed-state facts used for compatibility decisions."""

    platform: str
    config_schema: int
    db_schema: int
    release_sequence: int
    installed_version: str


class _BoundReleasePreparer:
    def __init__(self, *, extractor: SafeReleaseExtractor, paths: AppliancePaths) -> None:
        self._extractor = extractor
        self._paths = paths

    def prepare(
        self,
        artifact_path: Path,
        manifest: ReleaseManifest,
        spec: ArtifactSpec,
    ) -> PreparedRelease:
        return self._extractor.prepare(artifact_path, manifest, spec, self._paths)


class _LabPreflightGate:
    def check(self, release_dir: Path) -> HealthGateResult:
        marker = release_dir / ".ailen-release.json"
        try:
            release_stat = release_dir.lstat()
            marker_stat = marker.lstat()
        except OSError:
            return HealthGateResult(False, "LAB_PREFLIGHT_MISSING", "lab simulation")
        healthy = stat.S_ISDIR(release_stat.st_mode) and stat.S_ISREG(marker_stat.st_mode)
        return HealthGateResult(
            healthy,
            "LAB_PREFLIGHT_OK" if healthy else "LAB_PREFLIGHT_UNSAFE",
            "lab simulation",
        )


class _LabServiceController:
    """In-memory service boundary; never invokes systemd or another process."""

    def __init__(self) -> None:
        self.active_release: Path | None = None
        self.running = False

    def stop(self) -> None:
        self.running = False

    def start(self, release_dir: Path) -> None:
        try:
            value = release_dir.lstat()
        except OSError as exc:
            raise RuntimeError("lab release unavailable") from exc
        if not stat.S_ISDIR(value.st_mode):
            raise RuntimeError("lab release is unsafe")
        self.active_release = release_dir.resolve(strict=True)
        self.running = True


class _LabHealthGate:
    def __init__(self, controller: _LabServiceController) -> None:
        self._controller = controller

    def wait_healthy(self, timeout_seconds: float) -> HealthGateResult:
        _ = timeout_seconds
        healthy = self._controller.running and self._controller.active_release is not None
        return HealthGateResult(
            healthy,
            "LAB_HEALTHY" if healthy else "LAB_UNHEALTHY",
            "lab simulation",
        )


def _host_platform_id() -> str:
    system = host_platform.system().lower()
    machine = host_platform.machine().lower()
    system_id = {"linux": "linux", "windows": "windows"}.get(system, system)
    machine_id = {
        "amd64": "amd64",
        "x86_64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine, machine)
    return f"{system_id}-{machine_id}"


def _default_runtime_facts(config: AILENConfig) -> UpdateRuntimeFacts:
    return UpdateRuntimeFacts(
        platform=_host_platform_id(),
        config_schema=config.schema_version,
        db_schema=_CURRENT_DB_SCHEMA,
        release_sequence=_CURRENT_RELEASE_SEQUENCE,
        installed_version=get_version(),
    )


def _disabled(config: AILENConfig, reason: str) -> DisabledUpdateService:
    try:
        channel = UpdateChannel(config.updates.channel)
    except (TypeError, ValueError):
        channel = UpdateChannel.BETA
    return DisabledUpdateService(channel=channel, reason=reason)


def _safe_trust_path(raw_path: str) -> Path | None:
    path = Path(raw_path)
    if not path.is_absolute():
        return None
    resolved = path.resolve(strict=False)
    repository_root = Path(__file__).resolve().parents[3]
    if resolved in {
        Path("/"),
        Path.home().resolve(strict=False),
        repository_root,
    }:
        return None
    return resolved


def _paths_are_allowed(paths: AppliancePaths) -> bool:
    try:
        paths.validate()
    except ValueError:
        return False
    repository_root = Path(__file__).resolve().parents[3]
    return paths.install_root.resolve(strict=False) != repository_root and paths.state_root.resolve(
        strict=False
    ) != repository_root


def build_update_service(
    config: AILENConfig,
    mode: str,
    paths: AppliancePaths,
    *,
    runtime_facts: UpdateRuntimeFacts | None = None,
) -> LocalUpdateService | DisabledUpdateService:
    """Build an honest update boundary without network, threads, or mutations."""

    normalized_mode = mode.strip().lower()
    if normalized_mode == "appliance":
        return _disabled(config, "appliance updater daemon is not implemented")
    if normalized_mode not in {"lab", "lab_simulation"}:
        return _disabled(config, "update runtime mode is unavailable")

    update_errors = [
        error for error in validate_config(config) if error.startswith("updates")
    ]
    if update_errors:
        return _disabled(config, "signed update source configuration is invalid")
    source_fields = (
        config.updates.manifest_url.strip(),
        config.updates.manifest_signature_url.strip(),
        config.updates.trust_public_key_path.strip(),
    )
    if not all(source_fields):
        return _disabled(config, "signed update source and trust are not configured")
    if not _paths_are_allowed(paths):
        return _disabled(config, "update path policy rejected configuration")
    trust_path = _safe_trust_path(config.updates.trust_public_key_path)
    if trust_path is None:
        return _disabled(config, "update trust path policy rejected configuration")

    facts = runtime_facts or _default_runtime_facts(config)
    channel = UpdateChannel(config.updates.channel)
    store = ContentAddressedArtifactStore(paths.state_root / "artifacts")
    journal = OperationJournal(paths.state_root / "provisioning" / "operations")
    verifier = OpenSslEd25519Verifier()
    source = HttpsReleaseSource(
        manifest_url=config.updates.manifest_url,
        signature_url=config.updates.manifest_signature_url,
        public_key_path=trust_path,
        staging_dir=paths.state_root / "provisioning" / "manifest-staging",
        loader=VerifiedManifestLoader(verifier),
        fetcher=HttpsByteFetcher(),
    )
    downloader = HttpsArtifactDownloader(store=store)
    preparer = _BoundReleasePreparer(extractor=SafeReleaseExtractor(), paths=paths)
    controller = _LabServiceController()
    activator = ReleaseActivator(
        paths=paths,
        journal=journal,
        preflight=_LabPreflightGate(),
        controller=controller,
        health=_LabHealthGate(controller),
        probation_timeout_seconds=10.0,
    )
    return LocalUpdateService(
        source=source,
        downloader=downloader,
        journal=journal,
        channel=channel,
        platform=facts.platform,
        config_schema=facts.config_schema,
        current_db_schema=facts.db_schema,
        current_sequence=facts.release_sequence,
        installed_version=facts.installed_version,
        mode="LAB_SIMULATION",
        preparer=preparer,
        activator=activator,
    )
