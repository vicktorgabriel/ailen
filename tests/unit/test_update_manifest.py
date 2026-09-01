"""Behavioral tests for the signed release-manifest contract."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from ailen.updates.contracts import UpdateChannel, UpdateErrorKind, UpdateManifestError
from ailen.updates.manifest import parse_release_manifest, validate_release_compatibility


def _valid_manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "release_id": "ailen-0.4.1-beta.1",
        "version": "0.4.1-beta.1",
        "sequence": 401001,
        "channel": "beta",
        "platforms": ["linux-amd64"],
        "config_schema_min": 1,
        "config_schema_max": 1,
        "migration_from_db_schema_min": 4,
        "migration_from_db_schema_max": 4,
        "db_schema_after": 4,
        "rollback_db_schema_min": 4,
        "rollback_db_schema_max": 4,
        "release_notes": "Synthetic beta fixture for updater tests.",
        "artifacts": [
            {
                "artifact_id": "ailen-core-linux-amd64-0.4.1-beta.1",
                "kind": "release",
                "url": "https://updates.example.invalid/artifacts/core.tar.gz",
                "sha256": "a" * 64,
                "size_bytes": 1024,
                "expanded_size_bytes": 4096,
                "platform": "linux-amd64",
                "media_type": "application/gzip",
            }
        ],
    }


def _raw(document: object) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _assert_invalid(raw: bytes, message: str | None = None) -> UpdateManifestError:
    match = message if message is not None else None
    with pytest.raises(UpdateManifestError, match=match) as caught:
        parse_release_manifest(raw)
    assert caught.value.kind is UpdateErrorKind.INVALID_MANIFEST
    return caught.value


def test_parses_exact_valid_manifest_into_immutable_values() -> None:
    manifest = parse_release_manifest(_raw(_valid_manifest()))

    assert manifest.schema_version == 1
    assert manifest.release_id == "ailen-0.4.1-beta.1"
    assert manifest.channel is UpdateChannel.BETA
    assert manifest.platforms == ("linux-amd64",)
    assert manifest.release_notes == "Synthetic beta fixture for updater tests."
    assert len(manifest.artifacts) == 1
    assert manifest.artifacts[0].sha256 == "a" * 64
    assert manifest.artifacts[0].expanded_size_bytes == 4096

    with pytest.raises(AttributeError):
        manifest.sequence = 1  # type: ignore[misc]


def test_rejects_manifest_over_one_mib_before_decoding() -> None:
    _assert_invalid(b" " * (1024 * 1024 + 1), "size limit")


def test_rejects_duplicate_json_keys() -> None:
    _assert_invalid(b'{"schema_version":1,"schema_version":1}', "duplicate key")


@pytest.mark.parametrize(
    "raw",
    [
        b"not-json",
        b"[]",
        b'{"schema_version":NaN}',
        b"\xff",
    ],
)
def test_rejects_noncanonical_json_documents(raw: bytes) -> None:
    _assert_invalid(raw)


def test_rejects_unknown_schema_and_unknown_keys() -> None:
    document = _valid_manifest()
    document["schema_version"] = 2
    _assert_invalid(_raw(document), "schema_version")

    document = _valid_manifest()
    document["unexpected"] = True
    _assert_invalid(_raw(document), "unknown manifest field")

    document = _valid_manifest()
    artifact = deepcopy(document["artifacts"])[0]  # type: ignore[index]
    artifact["unexpected"] = True
    document["artifacts"] = [artifact]
    _assert_invalid(_raw(document), "unknown artifact field")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sequence", 0),
        ("sequence", -1),
        ("sequence", True),
        ("config_schema_min", -1),
        ("db_schema_after", -1),
    ],
)
def test_rejects_invalid_manifest_integer_fields(field: str, value: object) -> None:
    document = _valid_manifest()
    document[field] = value
    _assert_invalid(_raw(document), field)


@pytest.mark.parametrize("field", ["size_bytes", "expanded_size_bytes"])
@pytest.mark.parametrize("value", [0, -1, True])
def test_rejects_nonpositive_artifact_sizes(field: str, value: object) -> None:
    document = _valid_manifest()
    artifact = deepcopy(document["artifacts"])[0]  # type: ignore[index]
    artifact[field] = value
    document["artifacts"] = [artifact]
    _assert_invalid(_raw(document), field)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("release_id", "../release"),
        ("version", "bad version"),
        ("channel", "preview"),
        ("platforms", ["linux/amd64"]),
    ],
)
def test_rejects_invalid_manifest_identifiers(field: str, value: object) -> None:
    document = _valid_manifest()
    document[field] = value
    _assert_invalid(_raw(document), field)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("artifact_id", "../artifact"),
        ("kind", "script"),
        ("sha256", "A" * 64),
        ("sha256", "a" * 63),
        ("platform", "linux/amd64"),
        ("media_type", "not a media type"),
    ],
)
def test_rejects_invalid_artifact_metadata(field: str, value: object) -> None:
    document = _valid_manifest()
    artifact = deepcopy(document["artifacts"])[0]  # type: ignore[index]
    artifact[field] = value
    document["artifacts"] = [artifact]
    _assert_invalid(_raw(document), field)


@pytest.mark.parametrize(
    "url",
    [
        "http://updates.example.invalid/core.tar.gz",
        "https://user:password@updates.example.invalid/core.tar.gz",
        "https://updates.example.invalid/core.tar.gz#fragment",
        "https:///missing-host.tar.gz",
        "not-a-url",
    ],
)
def test_rejects_unsafe_artifact_urls_without_echoing_them(url: str) -> None:
    document = _valid_manifest()
    artifact = deepcopy(document["artifacts"])[0]  # type: ignore[index]
    artifact["url"] = url
    document["artifacts"] = [artifact]

    error = _assert_invalid(_raw(document), "url")

    assert url not in str(error)
    assert "password" not in str(error)


@pytest.mark.parametrize(
    "notes",
    [
        "a" * 8193,
        "contains\x00nul",
        "contains\x01control",
    ],
)
def test_rejects_unbounded_or_controlled_release_notes(notes: str) -> None:
    document = _valid_manifest()
    document["release_notes"] = notes
    _assert_invalid(_raw(document), "release_notes")


def test_accepts_release_notes_with_newlines_and_tabs() -> None:
    document = _valid_manifest()
    document["release_notes"] = "Changes:\n\t- safer updates"

    manifest = parse_release_manifest(_raw(document))

    assert manifest.release_notes == "Changes:\n\t- safer updates"


def test_rejects_empty_or_duplicate_manifest_collections() -> None:
    document = _valid_manifest()
    document["platforms"] = []
    _assert_invalid(_raw(document), "platforms")

    document = _valid_manifest()
    document["platforms"] = ["linux-amd64", "linux-amd64"]
    _assert_invalid(_raw(document), "duplicate platform")

    document = _valid_manifest()
    document["artifacts"] = []
    _assert_invalid(_raw(document), "artifacts")

    document = _valid_manifest()
    first = deepcopy(document["artifacts"])[0]  # type: ignore[index]
    second = dict(first)
    document["artifacts"] = [first, second]
    _assert_invalid(_raw(document), "duplicate artifact_id")


def test_rejects_same_digest_with_conflicting_metadata() -> None:
    document = _valid_manifest()
    first = deepcopy(document["artifacts"])[0]  # type: ignore[index]
    second = dict(first)
    second["artifact_id"] = "ailen-core-linux-arm64-0.4.1-beta.1"
    second["platform"] = "linux-arm64"
    document["artifacts"] = [first, second]

    _assert_invalid(_raw(document), "conflicting artifact metadata")


@pytest.mark.parametrize(
    ("minimum", "maximum", "expected_message"),
    [
        (5, 4, "rollback_db_schema"),
        (4, 3, "rollback_db_schema"),
    ],
)
def test_rejects_rollback_bounds_that_exclude_result_schema(
    minimum: int,
    maximum: int,
    expected_message: str,
) -> None:
    document = _valid_manifest()
    document["rollback_db_schema_min"] = minimum
    document["rollback_db_schema_max"] = maximum
    _assert_invalid(_raw(document), expected_message)


def test_rejects_inverted_schema_ranges() -> None:
    for minimum_field, maximum_field in (
        ("config_schema_min", "config_schema_max"),
        ("migration_from_db_schema_min", "migration_from_db_schema_max"),
        ("rollback_db_schema_min", "rollback_db_schema_max"),
    ):
        document = _valid_manifest()
        document[minimum_field] = 5
        document[maximum_field] = 4
        _assert_invalid(_raw(document), minimum_field)


def test_reports_all_compatibility_reasons_in_stable_order() -> None:
    manifest = parse_release_manifest(_raw(_valid_manifest()))

    reasons = validate_release_compatibility(
        manifest,
        platform="linux-arm64",
        config_schema=2,
        current_db_schema=3,
        current_sequence=401001,
    )

    assert reasons == [
        "PLATFORM_UNSUPPORTED",
        "CONFIG_SCHEMA_UNSUPPORTED",
        "DB_MIGRATION_SOURCE_UNSUPPORTED",
        "ROLLBACK_DB_SCHEMA_UNSUPPORTED",
        "RELEASE_NOT_NEWER",
    ]


def test_reports_no_compatibility_reason_for_supported_upgrade() -> None:
    manifest = parse_release_manifest(_raw(_valid_manifest()))

    reasons = validate_release_compatibility(
        manifest,
        platform="linux-amd64",
        config_schema=1,
        current_db_schema=4,
        current_sequence=401000,
    )

    assert reasons == []
