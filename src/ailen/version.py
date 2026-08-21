"""AILEN version management."""

from pathlib import Path


def get_version() -> str:
    """Resolve the current AILEN version from VERSION file or fallback."""
    # Try looking for VERSION relative to package root or repo root
    current_path = Path(__file__).resolve()
    # Check parent dirs: src/ailen -> src -> repo root
    candidates = [
        current_path.parent.parent.parent / "VERSION",
        current_path.parent / "VERSION",
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
    return "0.1.0-dev.0"


__version__ = get_version()
