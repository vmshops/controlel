"""Build a non-publishable HA development bundle with its exact Core wheel."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import tomllib
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import cast

if __package__:
    from .build_core_release import build_core_release
    from .build_hacs_release import _archive_bytes
    from .validate_hacs_release import (
        EXPECTED_ARCHIVE_FILES,
        FIXED_ZIP_MODE,
        FIXED_ZIP_TIMESTAMP,
        validate_source,
    )
else:
    from build_core_release import build_core_release
    from build_hacs_release import _archive_bytes
    from validate_hacs_release import (
        EXPECTED_ARCHIVE_FILES,
        FIXED_ZIP_MODE,
        FIXED_ZIP_TIMESTAMP,
        validate_source,
    )

ROOT = Path(__file__).parents[2]
COMPOSITION_SCHEMA_VERSION = 1
DEVELOPMENT_CORE_VERSION = "0.18.0"
ARCHIVE_PREFIX = "controlel-dev"


class DevelopmentCompositionError(ValueError):
    """Raised when a development bundle crosses or obscures a version boundary."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _project_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as pyproject_file:
        version = tomllib.load(pyproject_file)["project"]["version"]
    if not isinstance(version, str) or not version:
        raise DevelopmentCompositionError("project version must be a non-empty string")
    return version


def _integration_version(root: Path) -> str:
    source = (root / "custom_components" / "controlel" / "const.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        if line.startswith("INTEGRATION_VERSION = "):
            value = line.partition("=")[2].strip().strip('"')
            if value:
                return value
    raise DevelopmentCompositionError("integration source has no literal INTEGRATION_VERSION")


def _wheel_identity(content: bytes) -> tuple[str, str]:
    with zipfile.ZipFile(io.BytesIO(content), "r") as wheel:
        metadata_names = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise DevelopmentCompositionError("Core wheel must contain exactly one METADATA file")
        metadata = wheel.read(metadata_names[0]).decode("utf-8")
    fields = {
        key: value
        for line in metadata.splitlines()
        if ": " in line
        for key, value in (line.split(": ", 1),)
        if key in {"Name", "Version"}
    }
    try:
        return fields["Name"], fields["Version"]
    except KeyError as error:
        raise DevelopmentCompositionError("Core wheel METADATA has no Name/Version identity") from error


def _development_integration(
    *,
    root: Path,
    integration_version: str,
    core_version: str,
) -> tuple[bytes, str]:
    files = validate_source(root, version=integration_version)
    manifest = json.loads(files["manifest.json"].decode("utf-8"))
    public_requirements = manifest.get("requirements")
    if not isinstance(public_requirements, list) or len(public_requirements) != 1:
        raise DevelopmentCompositionError("release manifest must contain one exact public Core requirement")
    public_requirement = public_requirements[0]
    development_requirement = f"controlel=={core_version}"
    manifest["requirements"] = [development_requirement]
    development_files = {
        **files,
        "manifest.json": (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    }
    return _archive_bytes(development_files), str(public_requirement)


def _install_text(core_version: str, wheel_name: str) -> bytes:
    return f"""# Controlel development composition

This bundle is for local Home Assistant testing only. Do not upload either
artifact to PyPI, GitHub Releases, or HACS.

Install in this order while Home Assistant is stopped:

1. Install `core/{wheel_name}` into the Python environment used by Home Assistant:
   `HA_PYTHON -m pip install --force-reinstall --no-deps core/{wheel_name}`
2. Extract `integration/controlel.zip` directly into
   `HA_CONFIG/custom_components/controlel`.
3. Remove only `HA_CONFIG/custom_components/controlel/__pycache__` if present,
   then restart Home Assistant.
4. Verify Core before startup with:
   `HA_PYTHON -c "import importlib.metadata; print(importlib.metadata.version('controlel'))"`
   The result must be `{core_version}`.

The integration ZIP carries an exact development-only `controlel=={core_version}`
pin. The repository release manifest is not changed.
""".encode()


def _outer_archive(files: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = FIXED_ZIP_MODE << 16
            archive.writestr(info, files[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return buffer.getvalue()


def build_development_composition(
    output: Path,
    *,
    source_ref: str,
    core_wheel: Path | None = None,
    root: Path = ROOT,
) -> dict[str, object]:
    """Build and validate one exact frontend + Core development composition."""

    core_version = _project_version(root)
    if core_version != DEVELOPMENT_CORE_VERSION:
        raise DevelopmentCompositionError(
            f"development composition requires Core {DEVELOPMENT_CORE_VERSION}, found {core_version}"
        )
    if not source_ref.strip():
        raise DevelopmentCompositionError("source_ref must be non-empty")
    if core_wheel is None:
        if root != ROOT:
            raise DevelopmentCompositionError("a non-default source root requires an explicit Core wheel")
        core_wheel, _sdist = build_core_release()
    wheel_content = core_wheel.read_bytes()
    wheel_name, wheel_version = _wheel_identity(wheel_content)
    if (wheel_name.casefold(), wheel_version) != ("controlel", core_version):
        raise DevelopmentCompositionError(
            f"Core wheel identity is {wheel_name} {wheel_version}, expected controlel {core_version}"
        )

    integration_version = _integration_version(root)
    integration_content, public_requirement = _development_integration(
        root=root,
        integration_version=integration_version,
        core_version=core_version,
    )
    composition: dict[str, object] = {
        "schema_version": COMPOSITION_SCHEMA_VERSION,
        "composition": "controlel-home-assistant-development",
        "publishable": False,
        "source_ref": source_ref,
        "core": {
            "version": core_version,
            "requirement": f"controlel=={core_version}",
            "wheel": core_wheel.name,
            "sha256": _sha256(wheel_content),
        },
        "integration": {
            "version": integration_version,
            "archive": "controlel.zip",
            "sha256": _sha256(integration_content),
            "release_source_requirement": public_requirement,
            "development_requirement": f"controlel=={core_version}",
        },
    }
    files = {
        "INSTALL.md": _install_text(core_version, core_wheel.name),
        "composition.json": (json.dumps(composition, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        f"core/{core_wheel.name}": wheel_content,
        "integration/controlel.zip": integration_content,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_outer_archive(files))
    validate_development_composition(output, expected_core_version=core_version)
    return composition


def validate_development_composition(archive_path: Path, *, expected_core_version: str) -> dict[str, object]:
    """Validate the cross-artifact identities in a development composition."""

    with zipfile.ZipFile(archive_path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise DevelopmentCompositionError("development composition contains duplicate paths")
        if "composition.json" not in names or "integration/controlel.zip" not in names:
            raise DevelopmentCompositionError("development composition is missing its manifest or integration")
        core_names = [name for name in names if name.startswith("core/") and name.endswith(".whl")]
        expected_names = {"INSTALL.md", "composition.json", "integration/controlel.zip", *core_names}
        if len(core_names) != 1 or set(names) != expected_names:
            raise DevelopmentCompositionError("development composition must contain one Core wheel and one integration")
        raw_composition = json.loads(archive.read("composition.json"))
        if not isinstance(raw_composition, dict):
            raise DevelopmentCompositionError("development composition manifest must be an object")
        composition = cast(dict[str, object], raw_composition)
        wheel_content = archive.read(core_names[0])
        integration_content = archive.read("integration/controlel.zip")

    if composition.get("publishable") is not False or composition.get("schema_version") != 1:
        raise DevelopmentCompositionError("development composition must be explicitly non-publishable schema v1")
    core = composition.get("core")
    integration = composition.get("integration")
    if not isinstance(core, dict) or not isinstance(integration, dict):
        raise DevelopmentCompositionError("development composition identities are malformed")
    if core.get("version") != expected_core_version or core.get("requirement") != f"controlel=={expected_core_version}":
        raise DevelopmentCompositionError("development Core identity does not match the expected version")
    if core.get("wheel") != Path(core_names[0]).name or core.get("sha256") != _sha256(wheel_content):
        raise DevelopmentCompositionError("development Core wheel identity or hash does not match")
    if integration.get("sha256") != _sha256(integration_content):
        raise DevelopmentCompositionError("development integration hash does not match")
    if integration.get("development_requirement") != f"controlel=={expected_core_version}":
        raise DevelopmentCompositionError("development integration requirement does not match Core")
    if integration.get("release_source_requirement") != "controlel==0.18.0":
        raise DevelopmentCompositionError("published integration requirement history was not preserved")
    wheel_name, wheel_version = _wheel_identity(wheel_content)
    if (wheel_name.casefold(), wheel_version) != ("controlel", expected_core_version):
        raise DevelopmentCompositionError("embedded Core wheel has the wrong distribution identity")

    with zipfile.ZipFile(io.BytesIO(integration_content), "r") as integration_archive:
        if set(integration_archive.namelist()) != EXPECTED_ARCHIVE_FILES:
            raise DevelopmentCompositionError("development integration file set is invalid")
        manifest = json.loads(integration_archive.read("manifest.json"))
        if manifest.get("requirements") != [f"controlel=={expected_core_version}"]:
            raise DevelopmentCompositionError("development integration manifest has the wrong Core pin")
        if any(name.startswith("controlel/") or "/controlel/" in name for name in integration_archive.namelist()):
            raise DevelopmentCompositionError("development integration must not vendor Core")
    return composition


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-ref", required=True, help="Git commit or explicit source identity for the bundle")
    parser.add_argument("--core-wheel", type=Path, help="Use an already-built Core wheel")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "development" / f"{ARCHIVE_PREFIX}-{DEVELOPMENT_CORE_VERSION}.zip",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    composition = build_development_composition(
        arguments.output,
        source_ref=arguments.source_ref,
        core_wheel=arguments.core_wheel,
    )
    print(f"Built non-publishable development composition: {arguments.output}")
    print(json.dumps(composition, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
