"""Truthfulness and side-effect boundaries for update service construction."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from ailen.core.config import AILENConfig
from ailen.updates.activation import AppliancePaths
from ailen.updates.service import DisabledUpdateService, LocalUpdateService


def _configured(tmp_path: Path) -> AILENConfig:
    config = AILENConfig()
    config.updates.manifest_url = "https://updates.example.invalid/beta/manifest.json"
    config.updates.manifest_signature_url = (
        "https://updates.example.invalid/beta/manifest.json.sig"
    )
    config.updates.trust_public_key_path = str(tmp_path / "trust" / "release.pub")
    return config


def _paths(tmp_path: Path) -> AppliancePaths:
    return AppliancePaths(
        install_root=(tmp_path / "simulation" / "install").resolve(),
        state_root=(tmp_path / "simulation" / "state").resolve(),
    )


def test_incomplete_source_builds_honest_disabled_service(tmp_path: Path) -> None:
    from ailen.updates.factory import build_update_service

    config = AILENConfig()
    config.updates.manifest_url = "https://updates.example.invalid/manifest.json"

    service = build_update_service(config, mode="lab", paths=_paths(tmp_path))

    assert isinstance(service, DisabledUpdateService)
    snapshot = service.snapshot()
    assert snapshot.availability == "UNAVAILABLE"
    assert snapshot.mode == "DISABLED"
    assert "source" in snapshot.detail
    assert not (tmp_path / "simulation").exists()


def test_lab_factory_is_side_effect_free_and_labels_simulation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ailen.updates import signatures, source
    from ailen.updates.factory import build_update_service

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("factory performed external work")

    monkeypatch.setattr(source.HttpsByteFetcher, "fetch", forbidden)
    monkeypatch.setattr(signatures.OpenSslEd25519Verifier, "verify", forbidden)
    before_threads = tuple(thread.ident for thread in threading.enumerate())
    paths = _paths(tmp_path)

    service = build_update_service(_configured(tmp_path), mode="lab", paths=paths)

    assert isinstance(service, LocalUpdateService)
    assert service.snapshot().mode == "LAB_SIMULATION"
    assert tuple(thread.ident for thread in threading.enumerate()) == before_threads
    assert not paths.install_root.exists()
    assert not paths.state_root.exists()
    service.close()


def test_appliance_mode_refuses_activation_until_updater_daemon_exists(
    tmp_path: Path,
) -> None:
    from ailen.updates.factory import build_update_service

    service = build_update_service(
        _configured(tmp_path),
        mode="appliance",
        paths=_paths(tmp_path),
    )

    assert isinstance(service, DisabledUpdateService)
    assert "updater daemon" in service.snapshot().detail
    assert service.activate("operation").code == "UNAVAILABLE"
    assert not (tmp_path / "simulation").exists()


@pytest.mark.parametrize("mode", ["", "production", "unknown"])
def test_unknown_mode_never_falls_back_to_lab(tmp_path: Path, mode: str) -> None:
    from ailen.updates.factory import build_update_service

    service = build_update_service(_configured(tmp_path), mode=mode, paths=_paths(tmp_path))

    assert isinstance(service, DisabledUpdateService)
    assert service.snapshot().mode == "DISABLED"


@pytest.mark.parametrize(
    "paths",
    [
        AppliancePaths(Path("/"), Path("/var/lib/ailen-test-state")),
        AppliancePaths(Path.home(), Path("/var/lib/ailen-test-state")),
        AppliancePaths(Path.cwd().resolve(), Path("/var/lib/ailen-test-state")),
    ],
)
def test_broad_or_repository_update_roots_are_rejected(
    tmp_path: Path,
    paths: AppliancePaths,
) -> None:
    from ailen.updates.factory import build_update_service

    service = build_update_service(_configured(tmp_path), mode="lab", paths=paths)

    assert isinstance(service, DisabledUpdateService)
    assert "path" in service.snapshot().detail


def test_trust_key_path_must_be_absolute_and_not_a_broad_directory(
    tmp_path: Path,
) -> None:
    from ailen.updates.factory import build_update_service

    config = _configured(tmp_path)
    config.updates.trust_public_key_path = "relative/release.pub"
    relative = build_update_service(config, mode="lab", paths=_paths(tmp_path))
    config.updates.trust_public_key_path = "/"
    broad = build_update_service(config, mode="lab", paths=_paths(tmp_path))

    assert isinstance(relative, DisabledUpdateService)
    assert isinstance(broad, DisabledUpdateService)
    assert "trust" in relative.snapshot().detail
    assert "trust" in broad.snapshot().detail
