"""Strict parser for exact, signed AILEN release-manifest bytes."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any
from urllib.parse import urlsplit

from ailen.updates.contracts import (
    ArtifactKind,
    ArtifactSpec,
    ReleaseManifest,
    UpdateChannel,
    UpdateManifestError,
)

MAX_MANIFEST_BYTES = 1024 * 1024
MAX_RELEASE_NOTES_BYTES = 8 * 1024

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MEDIA_TYPE = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,127}$"
)

_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "release_id",
        "version",
        "sequence",
        "channel",
        "platforms",
        "config_schema_min",
        "config_schema_max",
        "migration_from_db_schema_min",
        "migration_from_db_schema_max",
        "db_schema_after",
        "rollback_db_schema_min",
        "rollback_db_schema_max",
        "release_notes",
        "artifacts",
    }
)
_ARTIFACT_FIELDS = frozenset(
    {
        "artifact_id",
        "kind",
        "url",
        "sha256",
        "size_bytes",
        "expanded_size_bytes",
        "platform",
        "media_type",
    }
)


class _DuplicateKey(ValueError):
    pass


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(value)


def _invalid(message: str) -> UpdateManifestError:
    return UpdateManifestError(message)


def _require_exact_fields(
    value: dict[str, Any],
    allowed: frozenset[str],
    *,
    label: str,
) -> None:
    unknown = value.keys() - allowed
    if unknown:
        raise _invalid(f"unknown {label} field")
    missing = allowed - value.keys()
    if missing:
        raise _invalid(f"missing {label} field")


def _require_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be a string")
    return value


def _require_identifier(value: Any, *, field: str) -> str:
    text = _require_string(value, field=field)
    if _IDENTIFIER.fullmatch(text) is None:
        raise _invalid(f"invalid {field}")
    return text


def _require_integer(value: Any, *, field: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise _invalid(f"invalid {field}")
    return value


def _require_https_url(value: Any) -> str:
    url = _require_string(value, field="url")
    if url != url.strip():
        raise _invalid("invalid artifact url")
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise _invalid("invalid artifact url") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise _invalid("invalid artifact url")
    return url


def _require_release_notes(value: Any) -> str:
    notes = _require_string(value, field="release_notes")
    if len(notes.encode("utf-8")) > MAX_RELEASE_NOTES_BYTES:
        raise _invalid("release_notes exceeds size limit")
    if any(unicodedata.category(char) == "Cc" and char not in "\n\t" for char in notes):
        raise _invalid("release_notes contains control characters")
    return notes


def _parse_artifact(value: Any) -> ArtifactSpec:
    if not isinstance(value, dict):
        raise _invalid("artifact must be an object")
    _require_exact_fields(value, _ARTIFACT_FIELDS, label="artifact")

    try:
        kind = ArtifactKind(_require_string(value["kind"], field="kind"))
    except ValueError as exc:
        raise _invalid("invalid kind") from exc

    sha256 = _require_string(value["sha256"], field="sha256")
    if _SHA256.fullmatch(sha256) is None:
        raise _invalid("invalid sha256")

    media_type = _require_string(value["media_type"], field="media_type")
    if _MEDIA_TYPE.fullmatch(media_type) is None:
        raise _invalid("invalid media_type")

    return ArtifactSpec(
        artifact_id=_require_identifier(value["artifact_id"], field="artifact_id"),
        kind=kind,
        url=_require_https_url(value["url"]),
        sha256=sha256,
        size_bytes=_require_integer(value["size_bytes"], field="size_bytes", minimum=1),
        expanded_size_bytes=_require_integer(
            value["expanded_size_bytes"], field="expanded_size_bytes", minimum=1
        ),
        platform=_require_identifier(value["platform"], field="platform"),
        media_type=media_type,
    )


def _load_json(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_MANIFEST_BYTES:
        raise _invalid("manifest exceeds size limit")
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_json_constant,
        )
    except _DuplicateKey as exc:
        raise _invalid("duplicate key in manifest") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _invalid("manifest is not strict UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise _invalid("manifest root must be an object")
    return document


def parse_release_manifest(raw: bytes) -> ReleaseManifest:
    """Parse trusted exact bytes into a strict immutable release manifest."""

    document = _load_json(raw)
    _require_exact_fields(document, _MANIFEST_FIELDS, label="manifest")

    schema_version = _require_integer(
        document["schema_version"], field="schema_version", minimum=1
    )
    if schema_version != 1:
        raise _invalid("unsupported schema_version")

    try:
        channel = UpdateChannel(_require_string(document["channel"], field="channel"))
    except ValueError as exc:
        raise _invalid("invalid channel") from exc

    platforms_value = document["platforms"]
    if not isinstance(platforms_value, list) or not platforms_value:
        raise _invalid("platforms must be a non-empty list")
    platforms = tuple(
        _require_identifier(platform, field="platforms") for platform in platforms_value
    )
    if len(set(platforms)) != len(platforms):
        raise _invalid("duplicate platform")

    artifacts_value = document["artifacts"]
    if not isinstance(artifacts_value, list) or not artifacts_value:
        raise _invalid("artifacts must be a non-empty list")
    artifacts = tuple(_parse_artifact(artifact) for artifact in artifacts_value)

    artifact_ids: set[str] = set()
    digest_metadata: dict[str, tuple[object, ...]] = {}
    for artifact in artifacts:
        if artifact.artifact_id in artifact_ids:
            raise _invalid("duplicate artifact_id")
        artifact_ids.add(artifact.artifact_id)
        metadata = (
            artifact.kind,
            artifact.url,
            artifact.size_bytes,
            artifact.expanded_size_bytes,
            artifact.platform,
            artifact.media_type,
        )
        previous = digest_metadata.get(artifact.sha256)
        if previous is not None and previous != metadata:
            raise _invalid("conflicting artifact metadata for duplicate digest")
        digest_metadata[artifact.sha256] = metadata

    config_schema_min = _require_integer(
        document["config_schema_min"], field="config_schema_min", minimum=0
    )
    config_schema_max = _require_integer(
        document["config_schema_max"], field="config_schema_max", minimum=0
    )
    migration_min = _require_integer(
        document["migration_from_db_schema_min"],
        field="migration_from_db_schema_min",
        minimum=0,
    )
    migration_max = _require_integer(
        document["migration_from_db_schema_max"],
        field="migration_from_db_schema_max",
        minimum=0,
    )
    db_schema_after = _require_integer(
        document["db_schema_after"], field="db_schema_after", minimum=0
    )
    rollback_min = _require_integer(
        document["rollback_db_schema_min"], field="rollback_db_schema_min", minimum=0
    )
    rollback_max = _require_integer(
        document["rollback_db_schema_max"], field="rollback_db_schema_max", minimum=0
    )

    for minimum, maximum, field in (
        (config_schema_min, config_schema_max, "config_schema_min"),
        (migration_min, migration_max, "migration_from_db_schema_min"),
        (rollback_min, rollback_max, "rollback_db_schema_min"),
    ):
        if minimum > maximum:
            raise _invalid(f"invalid {field} range")
    if not rollback_min <= db_schema_after <= rollback_max:
        raise _invalid("rollback_db_schema bounds exclude db_schema_after")

    return ReleaseManifest(
        schema_version=schema_version,
        release_id=_require_identifier(document["release_id"], field="release_id"),
        version=_require_identifier(document["version"], field="version"),
        sequence=_require_integer(document["sequence"], field="sequence", minimum=1),
        channel=channel,
        platforms=platforms,
        config_schema_min=config_schema_min,
        config_schema_max=config_schema_max,
        migration_from_db_schema_min=migration_min,
        migration_from_db_schema_max=migration_max,
        db_schema_after=db_schema_after,
        rollback_db_schema_min=rollback_min,
        rollback_db_schema_max=rollback_max,
        artifacts=artifacts,
        release_notes=_require_release_notes(document["release_notes"]),
    )


def validate_release_compatibility(
    manifest: ReleaseManifest,
    *,
    platform: str,
    config_schema: int,
    current_db_schema: int,
    current_sequence: int,
) -> list[str]:
    """Return stable reason codes for every incompatible release property."""

    reasons: list[str] = []
    if platform not in manifest.platforms:
        reasons.append("PLATFORM_UNSUPPORTED")
    if not manifest.config_schema_min <= config_schema <= manifest.config_schema_max:
        reasons.append("CONFIG_SCHEMA_UNSUPPORTED")
    if not (
        manifest.migration_from_db_schema_min
        <= current_db_schema
        <= manifest.migration_from_db_schema_max
    ):
        reasons.append("DB_MIGRATION_SOURCE_UNSUPPORTED")
    if not (
        manifest.rollback_db_schema_min
        <= current_db_schema
        <= manifest.rollback_db_schema_max
    ):
        reasons.append("ROLLBACK_DB_SCHEMA_UNSUPPORTED")
    if manifest.sequence <= current_sequence:
        reasons.append("RELEASE_NOT_NEWER")
    return reasons
