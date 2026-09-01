"""Pure contracts for signed release updates.

This module deliberately owns no filesystem, network, subprocess, or service
behavior.  Those boundaries consume these immutable values in later layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ArtifactKind(StrEnum):
    """Kinds of independently downloadable AILEN artifacts."""

    RELEASE = "release"
    MODEL = "model"
    VOICE = "voice"
    FACEPACK = "facepack"


class UpdateChannel(StrEnum):
    """Release channels understood by the updater."""

    NIGHTLY = "nightly"
    BETA = "beta"
    STABLE = "stable"


class UpdateErrorKind(StrEnum):
    """Stable, redacted failure classifications exposed across boundaries."""

    INVALID_MANIFEST = "invalid_manifest"
    SIGNATURE_INVALID = "signature_invalid"
    SIGNATURE_UNAVAILABLE = "signature_unavailable"
    INCOMPATIBLE = "incompatible"
    NETWORK = "network"
    INTEGRITY = "integrity"
    INSUFFICIENT_DISK = "insufficient_disk"
    CANCELLED = "cancelled"
    ACTIVATION = "activation"
    ROLLBACK_FAILED = "rollback_failed"
    RECOVERY_REQUIRED = "recovery_required"
    UNAVAILABLE = "unavailable"
    INTERNAL = "internal"


class UpdatePhase(StrEnum):
    """Persistable phases of an update operation."""

    IDLE = "idle"
    CHECKING = "checking"
    PLANNED = "planned"
    DOWNLOADING = "downloading"
    VERIFIED = "verified"
    PREPARED = "prepared"
    ACTIVATING = "activating"
    PROBATION = "probation"
    ACTIVE = "active"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True)
class ArtifactSpec:
    artifact_id: str
    kind: ArtifactKind
    url: str
    sha256: str
    size_bytes: int
    expanded_size_bytes: int
    platform: str
    media_type: str


@dataclass(frozen=True)
class ReleaseManifest:
    schema_version: int
    release_id: str
    version: str
    sequence: int
    channel: UpdateChannel
    platforms: tuple[str, ...]
    config_schema_min: int
    config_schema_max: int
    migration_from_db_schema_min: int
    migration_from_db_schema_max: int
    db_schema_after: int
    rollback_db_schema_min: int
    rollback_db_schema_max: int
    artifacts: tuple[ArtifactSpec, ...]
    release_notes: str


@dataclass(frozen=True)
class UpdatePlan:
    release_id: str
    version: str
    sequence: int
    artifacts: tuple[ArtifactSpec, ...]
    total_bytes: int
    reason_codes: tuple[str, ...]
    approval_required: bool = True


@dataclass(frozen=True)
class OperationRecord:
    schema_version: int
    operation_id: str
    phase: UpdatePhase
    release_id: str
    version: str
    sequence: int
    artifact_hashes: tuple[str, ...]
    downloaded_bytes: int
    total_bytes: int
    error_kind: UpdateErrorKind | None
    error_message: str
    started_at: str
    updated_at: str


@dataclass(frozen=True)
class OperationStatus:
    operation_id: str
    phase: UpdatePhase
    release_id: str
    downloaded_bytes: int
    total_bytes: int
    error_kind: UpdateErrorKind | None
    error_message: str
    started_at: str
    updated_at: str


@dataclass(frozen=True)
class UpdateCommandResult:
    ok: bool
    code: str
    message: str
    operation_id: str = ""
    approval_token: str = ""


@dataclass(frozen=True)
class UpdateAdminSnapshot:
    availability: str
    mode: str
    channel: UpdateChannel
    installed_version: str
    effective_version: str
    candidate_version: str
    release_notes: str
    operation: OperationStatus | None
    rollback_available: bool
    detail: str
    candidate_release_id: str = ""


class UpdateFailure(RuntimeError):
    """Base typed update failure safe to project through admin boundaries."""

    def __init__(
        self,
        kind: UpdateErrorKind,
        message: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.public_message = message
        self.retry_after_seconds = retry_after_seconds


class UpdateManifestError(UpdateFailure):
    """A bounded manifest failed structural or semantic validation."""

    def __init__(self, message: str) -> None:
        super().__init__(UpdateErrorKind.INVALID_MANIFEST, message)
