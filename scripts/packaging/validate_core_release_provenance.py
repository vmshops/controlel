"""Validate that upload inputs exactly match a core release provenance manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePath
from typing import Any

if __package__:
    from .validate_artifacts import validate_sdist, validate_wheel
else:
    from validate_artifacts import validate_sdist, validate_wheel

PROVENANCE_FILENAME = "core-release-provenance.json"
PROVENANCE_SCHEMA_VERSION = 1
FULL_SHA = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
TOP_LEVEL_KEYS = {
    "schema_version",
    "tool",
    "package",
    "release_version",
    "commit_sha",
    "tag",
    "tag_type",
    "resolved_tag_commit",
    "source_export",
    "build",
    "artifact_directory",
    "artifacts",
    "upload_artifacts",
    "verification_status",
}


class ProvenanceValidationError(RuntimeError):
    """Raised when proposed upload artifacts are not provenance-bound."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProvenanceValidationError(f"could not read provenance manifest: {error}") from error
    if not isinstance(value, dict):
        raise ProvenanceValidationError("provenance manifest must contain a JSON object")
    return value


def _safe_filename(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or PurePath(value).name != value:
        raise ProvenanceValidationError(f"{label} must be one safe filename")
    return value


def _validate_record(
    record: object,
    directory: Path,
    *,
    label: str,
) -> Path:
    if not isinstance(record, dict) or set(record) != {"filename", "size", "sha256"}:
        raise ProvenanceValidationError(f"{label} provenance record has an invalid schema")
    filename = _safe_filename(record["filename"], label=f"{label} filename")
    artifact = directory / filename
    if not artifact.is_file():
        raise ProvenanceValidationError(f"provenance-bound {label} is missing: {filename}")
    if not isinstance(record["size"], int) or artifact.stat().st_size != record["size"]:
        raise ProvenanceValidationError(f"{label} size differs from provenance: {filename}")
    if not isinstance(record["sha256"], str) or _sha256(artifact) != record["sha256"]:
        raise ProvenanceValidationError(f"{label} SHA-256 differs from provenance: {filename}")
    return artifact


def _validate_manifest_identity(value: dict[str, Any]) -> tuple[str, str]:
    if set(value) != TOP_LEVEL_KEYS:
        raise ProvenanceValidationError("provenance manifest top-level schema is invalid")
    if value["schema_version"] != PROVENANCE_SCHEMA_VERSION:
        raise ProvenanceValidationError("unsupported provenance schema_version")
    tool = value["tool"]
    if (
        not isinstance(tool, dict)
        or set(tool) != {"name", "version"}
        or tool["name"] != "prepare_final_core_release"
        or not isinstance(tool["version"], str)
        or not tool["version"]
    ):
        raise ProvenanceValidationError("provenance tool identity is invalid")
    package = value["package"]
    version = value["release_version"]
    commit = value["commit_sha"]
    if not isinstance(package, str) or not package or not isinstance(version, str) or not version:
        raise ProvenanceValidationError("provenance package/version identity is invalid")
    if not isinstance(commit, str) or not FULL_SHA.fullmatch(commit):
        raise ProvenanceValidationError("provenance commit_sha is invalid")
    tag = value["tag"]
    tag_type = value["tag_type"]
    resolved_tag_commit = value["resolved_tag_commit"]
    if tag is None:
        if tag_type is not None or resolved_tag_commit is not None:
            raise ProvenanceValidationError("null tag requires null tag provenance fields")
    elif tag != f"core-v{version}" or tag_type != "annotated" or resolved_tag_commit != commit:
        raise ProvenanceValidationError("tag provenance is inconsistent with version/commit")
    source_export = value["source_export"]
    if (
        not isinstance(source_export, dict)
        or set(source_export) != {"mechanism", "commit_sha", "tree_sha", "archive_sha256"}
        or source_export["mechanism"] != "git archive"
        or source_export["commit_sha"] != commit
        or not isinstance(source_export["tree_sha"], str)
        or not FULL_SHA.fullmatch(source_export["tree_sha"])
        or not isinstance(source_export["archive_sha256"], str)
        or not SHA256.fullmatch(source_export["archive_sha256"])
    ):
        raise ProvenanceValidationError("immutable source-export identity is invalid")
    build = value["build"]
    if (
        not isinstance(build, dict)
        or set(build)
        != {
            "epoch",
            "timestamp_source",
            "repeated_builds_byte_identical",
            "canonical_sdist_wheel_byte_identical",
        }
        or not isinstance(build["epoch"], int)
        or build["epoch"] < 0
        or build["timestamp_source"] != "commit_committer_timestamp"
        or build["repeated_builds_byte_identical"] is not True
        or build["canonical_sdist_wheel_byte_identical"] is not True
    ):
        raise ProvenanceValidationError("deterministic build provenance is invalid")
    return package, version


def validate_upload_binding(manifest_path: Path, artifact_directory: Path) -> tuple[Path, Path]:
    """Return the only two artifacts eligible for upload after strict validation."""

    manifest = manifest_path.resolve()
    directory = artifact_directory.resolve()
    if manifest.parent != directory:
        raise ProvenanceValidationError("artifact directory must be the directory containing the provenance manifest")
    value = _load_manifest(manifest)
    package, version = _validate_manifest_identity(value)
    if value["verification_status"] != "passed":
        raise ProvenanceValidationError("provenance verification_status is not passed")
    if value["artifact_directory"] != ".":
        raise ProvenanceValidationError("artifact_directory must be the manifest-relative directory '.'")
    artifacts = value["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != {"wheel", "sdist"}:
        raise ProvenanceValidationError("provenance must contain exactly wheel and sdist records")
    wheel = _validate_record(artifacts["wheel"], directory, label="wheel")
    sdist = _validate_record(artifacts["sdist"], directory, label="sdist")
    expected_uploads = [wheel.name, sdist.name]
    if value["upload_artifacts"] != expected_uploads:
        raise ProvenanceValidationError("upload_artifacts does not match wheel/sdist provenance order")
    if {path.name for path in directory.glob("*.whl")} != {wheel.name}:
        raise ProvenanceValidationError("artifact directory contains an unexpected or substituted wheel")
    if {path.name for path in directory.glob("*.tar.gz")} != {sdist.name}:
        raise ProvenanceValidationError("artifact directory contains an unexpected or substituted sdist")
    validate_wheel(wheel, distribution=package, version=version)
    validate_sdist(sdist, distribution=package, version=version)
    return wheel, sdist


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provenance", required=True, type=Path)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    wheel, sdist = validate_upload_binding(arguments.provenance, arguments.artifact_dir)
    print("Validated provenance-bound upload inputs only:")
    print(wheel)
    print(sdist)
    print(f'Upload command: python -m twine upload "{wheel}" "{sdist}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
