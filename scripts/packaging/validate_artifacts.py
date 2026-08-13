"""Validate Controlel wheel and source-distribution contents."""

from __future__ import annotations

import argparse
import tarfile
import tomllib
import zipfile
from email.message import Message
from email.parser import Parser
from pathlib import Path, PurePosixPath

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_PARTS = {
    ".git",
    ".github",
    ".venv",
    ".venv-ha",
    ".venv-package",
    ".venv-wheel",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "custom_components",
    "docs",
    "requirements",
    "tests",
}
FORBIDDEN_FILENAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "py.typed",
    "secrets.yaml",
    "secrets.yml",
}
FORBIDDEN_SUFFIXES = {".key", ".pem", ".pyc", ".pyo"}


class ArtifactValidationError(RuntimeError):
    """Raised when a built artifact violates the release contract."""


def _project_identity() -> tuple[str, str]:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        project = tomllib.load(pyproject_file)["project"]
    return project["name"], project["version"]


def _assert_safe_archive_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ArtifactValidationError(f"unsafe archive path: {name}")
    return path


def _assert_no_forbidden_content(names: list[str], *, artifact: str) -> None:
    for name in names:
        path = _assert_safe_archive_path(name)
        lowered_parts = {part.casefold() for part in path.parts}
        if forbidden := lowered_parts & FORBIDDEN_PARTS:
            raise ArtifactValidationError(f"{artifact} contains forbidden path {name!r}: {sorted(forbidden)}")
        if any(part.startswith(".venv") for part in lowered_parts):
            raise ArtifactValidationError(f"{artifact} contains a virtual environment path: {name}")
        if path.name.casefold() in FORBIDDEN_FILENAMES:
            raise ArtifactValidationError(f"{artifact} contains forbidden file: {name}")
        if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
            raise ArtifactValidationError(f"{artifact} contains forbidden file type: {name}")


def _parse_metadata(content: bytes, *, source: str) -> Message:
    try:
        return Parser().parsestr(content.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise ArtifactValidationError(f"{source} metadata is not UTF-8") from error


def _validate_metadata(metadata: Message, *, source: str, distribution: str, version: str) -> None:
    if metadata["Name"] != distribution or metadata["Version"] != version:
        raise ArtifactValidationError(
            f"{source} metadata identity is {metadata['Name']}=={metadata['Version']}, "
            f"expected {distribution}=={version}"
        )
    if metadata["Requires-Python"] != ">=3.13":
        raise ArtifactValidationError(f"{source} has unexpected Requires-Python: {metadata['Requires-Python']}")
    requirements = metadata.get_all("Requires-Dist") or []
    if requirements != ["pydantic>=2.0"]:
        raise ArtifactValidationError(f"{source} has unexpected runtime dependencies: {requirements}")


def validate_wheel(wheel: Path, *, distribution: str, version: str) -> None:
    """Validate wheel identity, metadata, and strict inclusion policy."""
    normalized_distribution = distribution.replace("-", "_")
    dist_info = f"{normalized_distribution}-{version}.dist-info"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        _assert_no_forbidden_content(names, artifact=wheel.name)

        allowed_roots = {"controlel", dist_info}
        unexpected_roots = {
            path.parts[0]
            for name in names
            if (path := _assert_safe_archive_path(name)).parts and path.parts[0] not in allowed_roots
        }
        if unexpected_roots:
            raise ArtifactValidationError(
                f"{wheel.name} contains unexpected top-level paths: {sorted(unexpected_roots)}"
            )

        required = {
            "controlel/__init__.py",
            "controlel/application/runtime/failsafe_runtime.py",
            "controlel/application/runtime/runtime_supervisor.py",
            "controlel/application/services/operational_event_recorder.py",
            "controlel/application/services/operational_event_stream.py",
            "controlel/application/services/source_reconciliation_policy.py",
            "controlel/application/services/source_recovery_policy.py",
            "controlel/application/services/zone_heat_demand_confirmation_policy.py",
            "controlel/application/state/runtime_supervision_state.py",
            "controlel/application/state/source_resilience_diagnostics.py",
            "controlel/application/state/zone_heat_demand_confirmation_state.py",
            "controlel/domain/operating_mode/__init__.py",
            "controlel/domain/operational_events/__init__.py",
            "controlel/domain/runtime_supervision/__init__.py",
            "controlel/domain/source_control/__init__.py",
            f"{dist_info}/METADATA",
            f"{dist_info}/RECORD",
            f"{dist_info}/WHEEL",
        }
        if missing := required - set(names):
            raise ArtifactValidationError(f"{wheel.name} is missing required files: {sorted(missing)}")

        metadata = _parse_metadata(archive.read(f"{dist_info}/METADATA"), source=wheel.name)

    _validate_metadata(metadata, source=wheel.name, distribution=distribution, version=version)


def validate_sdist(sdist: Path, *, distribution: str, version: str) -> None:
    """Validate sdist identity, metadata, and narrow rebuild contents."""
    archive_root = f"{distribution}-{version}"
    with tarfile.open(sdist, mode="r:gz") as archive:
        names = archive.getnames()
        _assert_no_forbidden_content(names, artifact=sdist.name)
        relative_names: set[str] = set()
        for archive_member in archive.getmembers():
            path = _assert_safe_archive_path(archive_member.name)
            if not path.parts or path.parts[0] != archive_root:
                raise ArtifactValidationError(
                    f"{sdist.name} contains path outside {archive_root}: {archive_member.name}"
                )
            if not (archive_member.isfile() or archive_member.isdir()):
                raise ArtifactValidationError(
                    f"{sdist.name} contains a link or special archive member: {archive_member.name}"
                )
            if not archive_member.isfile():
                continue
            relative = PurePosixPath(*path.parts[1:])
            if relative.parts:
                relative_names.add(relative.as_posix())

        required = {
            "LICENSE",
            "MANIFEST.in",
            "PKG-INFO",
            "README.md",
            "pyproject.toml",
            "src/controlel/__init__.py",
            "src/controlel/application/runtime/failsafe_runtime.py",
            "src/controlel/application/runtime/runtime_supervisor.py",
            "src/controlel/application/services/operational_event_recorder.py",
            "src/controlel/application/services/operational_event_stream.py",
            "src/controlel/application/services/source_reconciliation_policy.py",
            "src/controlel/application/services/source_recovery_policy.py",
            "src/controlel/application/services/zone_heat_demand_confirmation_policy.py",
            "src/controlel/application/state/runtime_supervision_state.py",
            "src/controlel/application/state/source_resilience_diagnostics.py",
            "src/controlel/application/state/zone_heat_demand_confirmation_state.py",
            "src/controlel/domain/operating_mode/__init__.py",
            "src/controlel/domain/operational_events/__init__.py",
            "src/controlel/domain/runtime_supervision/__init__.py",
            "src/controlel/domain/source_control/__init__.py",
        }
        if missing := required - relative_names:
            raise ArtifactValidationError(f"{sdist.name} is missing required files: {sorted(missing)}")

        allowed_files = {
            "LICENSE",
            "MANIFEST.in",
            "PKG-INFO",
            "README.md",
            "pyproject.toml",
            "setup.cfg",
        }
        unexpected = {
            name
            for name in relative_names
            if name not in allowed_files
            and not name.startswith("src/controlel/")
            and not name.startswith("src/controlel.egg-info/")
        }
        if unexpected:
            raise ArtifactValidationError(f"{sdist.name} contains unexpected files: {sorted(unexpected)}")

        member = archive.getmember(f"{archive_root}/PKG-INFO")
        extracted = archive.extractfile(member)
        if extracted is None:
            raise ArtifactValidationError(f"{sdist.name} PKG-INFO is not a regular file")
        metadata = _parse_metadata(extracted.read(), source=sdist.name)

    _validate_metadata(metadata, source=sdist.name, distribution=distribution, version=version)


def validate_artifacts(dist_directory: Path) -> tuple[Path, Path]:
    """Validate exactly one wheel and one sdist in a distribution directory."""
    distribution, version = _project_identity()
    wheels = sorted(dist_directory.glob("*.whl"))
    sdists = sorted(dist_directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ArtifactValidationError(
            f"expected one wheel and one sdist in {dist_directory}, found {len(wheels)} wheel(s) "
            f"and {len(sdists)} sdist(s)"
        )
    validate_wheel(wheels[0], distribution=distribution, version=version)
    validate_sdist(sdists[0], distribution=distribution, version=version)
    return wheels[0], sdists[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist_directory", nargs="?", type=Path, default=REPOSITORY_ROOT / "dist")
    arguments = parser.parse_args()
    wheel, sdist = validate_artifacts(arguments.dist_directory.resolve())
    print(f"Validated wheel: {wheel}")
    print(f"Validated sdist: {sdist}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
