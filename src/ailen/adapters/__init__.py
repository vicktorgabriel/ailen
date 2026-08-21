"""Adapters package: wiring of external backends behind contracts."""

from ailen.adapters.registry import FakeBackends, build_fake_backends

__all__ = ["FakeBackends", "build_fake_backends"]
