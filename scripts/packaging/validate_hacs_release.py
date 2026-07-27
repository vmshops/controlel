"""Validate the source and release archive for the Controlel HACS integration."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import stat
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).parents[2]
DOMAIN = "controlel"
ARCHIVE_FILENAME = "controlel.zip"
CORE_REQUIREMENT = "controlel==0.1.0"
ISSUE_TRACKER = "https://github.com/vmshops/controlel/issues"
DOCUMENTATION_URL = "https://github.com/vmshops/controlel"
HOME_ASSISTANT_VERSION = "2026.7.3"
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
FIXED_ZIP_MODE = stat.S_IFREG | 0o644

EXPECTED_ARCHIVE_FILES = frozenset(
    {
        "__init__.py",
        "config.py",
        "config_flow.py",
        "const.py",
        "event_loop_bridge.py",
        "failure_sink.py",
        "heat_source.py",
        "host.py",
        "manifest.json",
        "measurement_ingestion.py",
        "runtime_executor.py",
        "scheduler.py",
        "strings.json",
        "translations/en.json",
    }
)
EXPECTED_HACS_MANIFEST = {
    "name": "Controlel",
    "zip_release": True,
    "filename": ARCHIVE_FILENAME,
    "hide_default_branch": True,
    "homeassistant": HOME_ASSISTANT_VERSION,
}
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
)


class HacsReleaseValidationError(ValueError):
    """Raised when HACS source or release content violates its contract."""


def _load_json_bytes(content: bytes, *, source: str) -> dict[str, object]:
    try:
        data = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HacsReleaseValidationError(f"{source} is not valid UTF-8 JSON") from error
    if not isinstance(data, dict):
        raise HacsReleaseValidationError(f"{source} must contain one JSON object")
    return data


def _load_json_file(path: Path) -> dict[str, object]:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise HacsReleaseValidationError(f"cannot read required file {path}") from error
    return _load_json_bytes(content, source=str(path))


def _integration_version(source: str, *, origin: str) -> str:
    try:
        tree = ast.parse(source, filename=origin)
    except SyntaxError as error:
        raise HacsReleaseValidationError(f"{origin} is not valid Python") from error
    versions = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "INTEGRATION_VERSION" for target in node.targets)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ]
    if len(versions) != 1:
        raise HacsReleaseValidationError(f"{origin} must declare exactly one literal INTEGRATION_VERSION")
    return versions[0]


def _validate_manifest(
    manifest: Mapping[str, object],
    *,
    version: str,
    source: str,
) -> None:
    expected = {
        "domain": DOMAIN,
        "documentation": DOCUMENTATION_URL,
        "issue_tracker": ISSUE_TRACKER,
        "requirements": [CORE_REQUIREMENT],
        "version": version,
    }
    mismatches = {
        key: {"actual": manifest.get(key), "expected": value}
        for key, value in expected.items()
        if manifest.get(key) != value
    }
    if mismatches:
        raise HacsReleaseValidationError(f"{source} release metadata mismatch: {mismatches}")


def _validate_translations(
    strings: Mapping[str, object],
    english: Mapping[str, object],
    *,
    source: str,
) -> None:
    if english != strings:
        raise HacsReleaseValidationError(f"{source} translations/en.json must exactly match strings.json")
    for required_section in ("title", "config", "issues"):
        if required_section not in strings:
            raise HacsReleaseValidationError(f"{source} strings are missing {required_section!r}")


def _scan_for_secrets(files: Mapping[str, bytes], *, source: str) -> None:
    for name, content in files.items():
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                raise HacsReleaseValidationError(f"{source} contains secret-like content in {name}")


def _source_file_map(component: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in component.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(component)
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        name = relative.as_posix()
        try:
            files[name] = path.read_bytes()
        except OSError as error:
            raise HacsReleaseValidationError(f"cannot read integration source {path}") from error
    return files


def validate_source(root: Path, *, version: str) -> dict[str, bytes]:
    """Validate tracked release inputs and return normalized archive content."""
    custom_components = root / "custom_components"
    integration_directories = sorted(
        path.name for path in custom_components.iterdir() if path.is_dir() and path.name != "__pycache__"
    )
    if integration_directories != [DOMAIN]:
        raise HacsReleaseValidationError(
            f"expected exactly custom_components/{DOMAIN}, found {integration_directories}"
        )

    hacs_manifest = _load_json_file(root / "hacs.json")
    if hacs_manifest != EXPECTED_HACS_MANIFEST:
        raise HacsReleaseValidationError(f"hacs.json is {hacs_manifest}, expected {EXPECTED_HACS_MANIFEST}")

    files = _source_file_map(custom_components / DOMAIN)
    actual_files = set(files)
    if actual_files != EXPECTED_ARCHIVE_FILES:
        missing = sorted(EXPECTED_ARCHIVE_FILES - actual_files)
        unexpected = sorted(actual_files - EXPECTED_ARCHIVE_FILES)
        raise HacsReleaseValidationError(
            f"integration source file set mismatch; missing={missing}, unexpected={unexpected}"
        )

    manifest = _load_json_bytes(files["manifest.json"], source="custom_components/controlel/manifest.json")
    _validate_manifest(manifest, version=version, source="custom_components/controlel/manifest.json")
    declared_version = _integration_version(
        files["const.py"].decode("utf-8"),
        origin="custom_components/controlel/const.py",
    )
    if declared_version != version:
        raise HacsReleaseValidationError(f"INTEGRATION_VERSION is {declared_version!r}, expected {version!r}")
    strings = _load_json_bytes(files["strings.json"], source="custom_components/controlel/strings.json")
    english = _load_json_bytes(
        files["translations/en.json"],
        source="custom_components/controlel/translations/en.json",
    )
    _validate_translations(strings, english, source="custom_components/controlel")
    _scan_for_secrets(files, source="integration source")
    return files


def _validate_member_name(name: str) -> None:
    path = PurePosixPath(name)
    if not name or "\\" in name or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise HacsReleaseValidationError(f"unsafe or non-normalized archive path: {name!r}")


def validate_archive(archive: Path, *, version: str) -> str:
    """Validate a built HACS ZIP and return its SHA-256."""
    if archive.name != ARCHIVE_FILENAME:
        raise HacsReleaseValidationError(f"release archive must be named {ARCHIVE_FILENAME}, found {archive.name}")
    try:
        with zipfile.ZipFile(archive, "r") as release:
            infos = release.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise HacsReleaseValidationError("release archive contains duplicate paths")
            files: dict[str, bytes] = {}
            for info in infos:
                _validate_member_name(info.filename)
                if info.is_dir():
                    raise HacsReleaseValidationError(
                        f"release archive must not contain directory entries: {info.filename}"
                    )
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise HacsReleaseValidationError(f"release archive contains symlink: {info.filename}")
                if info.date_time != FIXED_ZIP_TIMESTAMP:
                    raise HacsReleaseValidationError(
                        f"release archive has non-deterministic timestamp for {info.filename}"
                    )
                if mode != FIXED_ZIP_MODE:
                    raise HacsReleaseValidationError(
                        f"release archive has unexpected mode for {info.filename}: {oct(mode)}"
                    )
                if info.compress_type != zipfile.ZIP_DEFLATED:
                    raise HacsReleaseValidationError(f"release archive has unexpected compression for {info.filename}")
                files[info.filename] = release.read(info)
    except (OSError, zipfile.BadZipFile) as error:
        raise HacsReleaseValidationError(f"cannot read release archive {archive}") from error

    actual_files = set(files)
    if actual_files != EXPECTED_ARCHIVE_FILES:
        missing = sorted(EXPECTED_ARCHIVE_FILES - actual_files)
        unexpected = sorted(actual_files - EXPECTED_ARCHIVE_FILES)
        raise HacsReleaseValidationError(
            f"release archive file set mismatch; missing={missing}, unexpected={unexpected}"
        )
    manifest = _load_json_bytes(files["manifest.json"], source=f"{archive.name}:manifest.json")
    _validate_manifest(manifest, version=version, source=f"{archive.name}:manifest.json")
    declared_version = _integration_version(
        files["const.py"].decode("utf-8"),
        origin=f"{archive.name}:const.py",
    )
    if declared_version != version:
        raise HacsReleaseValidationError(f"archive INTEGRATION_VERSION is {declared_version!r}, expected {version!r}")
    strings = _load_json_bytes(files["strings.json"], source=f"{archive.name}:strings.json")
    english = _load_json_bytes(
        files["translations/en.json"],
        source=f"{archive.name}:translations/en.json",
    )
    _validate_translations(strings, english, source=archive.name)
    _scan_for_secrets(files, source=archive.name)
    return hashlib.sha256(archive.read_bytes()).hexdigest()


def write_checksum(checksum_path: Path, *, archive: Path, digest: str) -> None:
    checksum_path.write_text(f"{digest}  {archive.name}\n", encoding="ascii", newline="\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--checksum", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    digest = validate_archive(arguments.archive, version=arguments.version)
    if arguments.checksum is not None:
        write_checksum(
            arguments.checksum,
            archive=arguments.archive,
            digest=digest,
        )
    print(f"{arguments.archive.name} SHA-256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
