"""AILEN version management."""

import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path


def _semver_display(value: str) -> str:
    """Normalize PEP 440 dev versions (0.4.0.dev0) to project display form."""
    match = re.fullmatch(r"(\d+\.\d+\.\d+)\.dev(\d+)", value.strip())
    if match:
        return f"{match.group(1)}-dev.{match.group(2)}"
    return value.strip()


def get_version() -> str:
    """Resolve the current AILEN version from repo VERSION or installed metadata."""
    current_path = Path(__file__).resolve()
    candidates = [
        current_path.parent.parent.parent / "VERSION",
        Path("VERSION"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            try:
                version_str = candidate.read_text(encoding="utf-8").strip()
                if version_str:
                    return version_str
            except OSError:
                pass

    try:
        return _semver_display(package_version("ailen"))
    except PackageNotFoundError:
        return "0.0.0-dev.0"


__version__ = get_version()
