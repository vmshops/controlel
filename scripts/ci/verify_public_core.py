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
CORE_VERSION = "0.10.0"
CORE_REQUIREMENT = f"controlel=={CORE_VERSION}"
PUBLIC_WHEEL_FILENAME = "controlel-0.10.0-py3-none-any.whl"
PUBLIC_WHEEL_SIZE = 151_194
PUBLIC_WHEEL_SHA256 = "fdc15bf881b173f255bc8f7f0ef7295c13bbc0f9f736c2f79c4b766f583bbfaf"
PUBLIC_SDIST_FILENAME = "controlel-0.10.0.tar.gz"
PUBLIC_SDIST_SIZE = 98_034
PUBLIC_SDIST_SHA256 = "babe73fb5779e49a59b57cabbd17522c0cb2c506e228e1b1c3dc4683d414e4dc"
PYPI_METADATA_URL = f"https://pypi.org/pypi/controlel/{CORE_VERSION}/json"


def verify_public_artifact_metadata() -> None:
    """Verify the immutable public wheel and sdist identities for this composition."""

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
    matching_sdists = [
        file
        for file in metadata["urls"]
        if file["filename"] == PUBLIC_SDIST_FILENAME and file["packagetype"] == "sdist"
    ]
    assert len(matching_sdists) == 1
    sdist = matching_sdists[0]
    assert sdist["size"] == PUBLIC_SDIST_SIZE
    assert sdist["digests"]["sha256"] == PUBLIC_SDIST_SHA256


def main() -> int:
    package_path = Path(controlel.__file__).resolve()
    distribution = importlib.metadata.distribution("controlel")
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
    assert distribution.read_text("direct_url.json") is None
    assert not any(
        path.is_file()
        and ("editable" in path.name.casefold() or ("controlel" in path.name.casefold() and path.suffix == ".pth"))
        for path in package_path.parents[1].iterdir()
    )
    assert importlib.metadata.requires("controlel") == ["pydantic>=2.0"]
    assert project["dependencies"] == ["pydantic>=2.0"]
    assert not any("homeassistant" in dependency.casefold() for dependency in project["dependencies"])
    assert manifest["requirements"] == [CORE_REQUIREMENT]
    verify_public_artifact_metadata()

    print(
        f"Verified public controlel {CORE_VERSION} at {package_path}; "
        f"{PUBLIC_WHEEL_FILENAME} SHA-256 {PUBLIC_WHEEL_SHA256}; "
        f"{PUBLIC_SDIST_FILENAME} SHA-256 {PUBLIC_SDIST_SHA256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
