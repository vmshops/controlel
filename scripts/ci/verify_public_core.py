"""Verify that Home Assistant CI is using the released Controlel core."""

from __future__ import annotations

import importlib.metadata
import json
import sys
import tomllib
from pathlib import Path
from urllib.request import Request, urlopen

import controlel

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORE_VERSION = "0.7.0"
CORE_REQUIREMENT = f"controlel=={CORE_VERSION}"
PUBLIC_WHEEL_FILENAME = "controlel-0.7.0-py3-none-any.whl"
PUBLIC_WHEEL_SIZE = 130_655
PUBLIC_WHEEL_SHA256 = "caf5b68a4045a458958cd60ed004b7660b45340ed44316554d2d4ced81f32bbd"
PYPI_METADATA_URL = f"https://pypi.org/pypi/controlel/{CORE_VERSION}/json"


def verify_public_wheel_metadata() -> None:
    """Verify the immutable public wheel identity recorded for this composition."""

    request = Request(PYPI_METADATA_URL, headers={"User-Agent": "controlel-ci-provenance-check"})
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS PyPI endpoint
        metadata = json.load(response)
    matching_files = [
        file
        for file in metadata["urls"]
        if file["filename"] == PUBLIC_WHEEL_FILENAME and file["packagetype"] == "bdist_wheel"
    ]
    assert len(matching_files) == 1
    wheel = matching_files[0]
    assert wheel["size"] == PUBLIC_WHEEL_SIZE
    assert wheel["digests"]["sha256"] == PUBLIC_WHEEL_SHA256


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
    verify_public_wheel_metadata()

    print(
        f"Verified public controlel {CORE_VERSION} at {package_path}; "
        f"{PUBLIC_WHEEL_FILENAME} SHA-256 {PUBLIC_WHEEL_SHA256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
