"""Canonical Home Assistant integration runtime file discovery.

Discovery is the source of truth for which files exist under
``custom_components/controlel`` and belong in a runtime package.

Public HACS release packaging keeps a separate explicit allowlist and must
still match discovery exactly. Development / HA test packaging consumes
discovery directly so newly added runtime modules cannot be silently omitted.
"""

from __future__ import annotations

from pathlib import Path

DOMAIN = "controlel"

# Development-only frontend files that must not ship in any runtime package.
# The runtime panel loads only discovered runtime assets; demo pages,
# documentation, and the Node test harness are tooling.
DEV_ONLY_ARCHIVE_FILES = frozenset(
    {
        "frontend/index.html",
        "frontend/wizard.html",
        "frontend/water-wizard.html",
        "frontend/README.md",
        "frontend/mock-data.js",
        "frontend/mock-app-data.js",
    }
)


def is_dev_only_archive_file(name: str) -> bool:
    """Return True for development-only files that must not ship at runtime."""
    return name in DEV_ONLY_ARCHIVE_FILES or name.startswith("frontend/tests/")


def discover_integration_runtime_files(component: Path) -> dict[str, bytes]:
    """Return the runtime file map for one integration source tree.

    Skips ``__pycache__``, bytecode, and development-only frontend tooling.
    Raises ``OSError`` subclasses when a file cannot be read.
    """
    files: dict[str, bytes] = {}
    for path in component.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(component)
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        name = relative.as_posix()
        if is_dev_only_archive_file(name):
            continue
        files[name] = path.read_bytes()
    return files


def discover_repository_integration_runtime_files(root: Path) -> dict[str, bytes]:
    """Discover runtime files from ``root/custom_components/controlel``."""
    return discover_integration_runtime_files(root / "custom_components" / DOMAIN)
