"""Verify that Home Assistant CI is using the released Controlel core."""

from __future__ import annotations

import importlib.metadata
import json
import sys
import tomllib
from pathlib import Path

import controlel

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORE_VERSION = "0.2.0"
CORE_REQUIREMENT = f"controlel=={CORE_VERSION}"


def main() -> int:
    package_path = Path(controlel.__file__).resolve()
    source_root = (REPOSITORY_ROOT / "src").resolve()
    manifest_path = REPOSITORY_ROOT / "custom_components" / "controlel" / "manifest.json"

    with manifest_path.open(encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        project = tomllib.load(pyproject_file)["project"]

    assert importlib.metadata.version("controlel") == CORE_VERSION
    assert controlel.__version__ == CORE_VERSION
    assert "site-packages" in package_path.as_posix()
    assert not package_path.is_relative_to(REPOSITORY_ROOT)
    assert source_root not in {Path(entry or ".").resolve() for entry in sys.path}
    assert importlib.metadata.requires("controlel") == ["pydantic>=2.0"]
    assert project["dependencies"] == ["pydantic>=2.0"]
    assert not any("homeassistant" in dependency.casefold() for dependency in project["dependencies"])
    assert manifest["requirements"] == [CORE_REQUIREMENT]

    print(f"Verified public controlel {CORE_VERSION} at {package_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
