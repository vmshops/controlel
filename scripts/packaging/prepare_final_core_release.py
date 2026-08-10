"""Prepare final core artifacts from one verified immutable Git commit."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

if __package__:
    from .validate_artifacts import validate_sdist, validate_wheel
    from .validate_core_release_provenance import validate_upload_binding
else:
    from validate_artifacts import validate_sdist, validate_wheel
    from validate_core_release_provenance import validate_upload_binding

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROVENANCE_FILENAME = "core-release-provenance.json"
PROVENANCE_SCHEMA_VERSION = 1
TOOL_VERSION = "1.0.0"
FULL_SHA = re.compile(r"[0-9a-fA-F]{40}\Z")


class FinalCoreReleaseError(RuntimeError):
    """Raised when strict final-release preparation cannot be proven safe."""


@dataclass(frozen=True)
class VerifiedRepository:
    package: str
    version: str
    commit: str
    tree: str
    epoch: int
    tag: str | None
    tag_type: str | None
    resolved_tag_commit: str | None


def _git(repository: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        detail = ""
        if isinstance(error, subprocess.CalledProcessError):
            detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise FinalCoreReleaseError(
            f"Git verification failed for {' '.join(arguments)}" + (f": {detail}" if detail else "")
        ) from error
    return result.stdout


def _git_text(repository: Path, *arguments: str) -> str:
    return _git(repository, *arguments).decode("utf-8").strip()


def verify_repository(
    repository: Path,
    *,
    version: str,
    commit: str,
    tag: str | None,
) -> VerifiedRepository:
    """Verify clean exact-HEAD release policy before any artifact is built."""

    repository = repository.resolve()
    if not FULL_SHA.fullmatch(commit):
        raise FinalCoreReleaseError("commit must be an explicit full 40-character SHA")
    if _git_text(repository, "rev-parse", "--is-inside-work-tree") != "true":
        raise FinalCoreReleaseError("release preparation requires a Git working tree")
    resolved_commit = _git_text(repository, "rev-parse", "--verify", f"{commit}^{{commit}}")
    if resolved_commit.casefold() != commit.casefold():
        raise FinalCoreReleaseError("requested commit did not resolve to the exact supplied SHA")
    head = _git_text(repository, "rev-parse", "HEAD")
    if head != resolved_commit:
        raise FinalCoreReleaseError(f"current HEAD {head} does not equal requested release commit {resolved_commit}")

    status = _git_text(
        repository,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if status:
        raise FinalCoreReleaseError(f"final release preparation requires a clean checkout; Git reported:\n{status}")

    try:
        project = tomllib.loads(_git(repository, "show", f"{resolved_commit}:pyproject.toml").decode("utf-8"))[
            "project"
        ]
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError) as error:
        raise FinalCoreReleaseError("requested commit has invalid project metadata") from error
    package = project.get("name")
    project_version = project.get("version")
    if not isinstance(package, str) or not package:
        raise FinalCoreReleaseError("requested commit has no valid package name")
    if project_version != version:
        raise FinalCoreReleaseError(
            f"requested version {version!r} does not match commit package version {project_version!r}"
        )

    tag_type: str | None = None
    resolved_tag_commit: str | None = None
    if tag is not None:
        expected_tag = f"core-v{version}"
        if tag != expected_tag:
            raise FinalCoreReleaseError(f"release tag must be {expected_tag!r} for version {version}, got {tag!r}")
        _git(repository, "show-ref", "--verify", f"refs/tags/{tag}")
        object_type = _git_text(repository, "cat-file", "-t", f"refs/tags/{tag}")
        if object_type == "tag":
            tag_type = "annotated"
        elif object_type == "commit":
            raise FinalCoreReleaseError(f"tag {tag!r} is lightweight; final core release tags must be annotated")
        else:
            raise FinalCoreReleaseError(f"tag {tag!r} has unsupported Git object type {object_type!r}")
        resolved_tag_commit = _git_text(
            repository,
            "rev-parse",
            "--verify",
            f"refs/tags/{tag}^{{commit}}",
        )
        if resolved_tag_commit != resolved_commit:
            raise FinalCoreReleaseError(f"tag {tag!r} resolves to {resolved_tag_commit}, not {resolved_commit}")

    tree = _git_text(repository, "rev-parse", f"{resolved_commit}^{{tree}}")
    try:
        epoch = int(_git_text(repository, "show", "-s", "--format=%ct", resolved_commit))
    except ValueError as error:
        raise FinalCoreReleaseError("commit timestamp is not an integer") from error
    return VerifiedRepository(
        package=package,
        version=version,
        commit=resolved_commit,
        tree=tree,
        epoch=epoch,
        tag=tag,
        tag_type=tag_type,
        resolved_tag_commit=resolved_tag_commit,
    )


def _extract_tar_bytes(content: bytes, destination: Path, *, expected_prefix: str) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:") as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or path.parts[0] != expected_prefix
                or member.issym()
                or member.islnk()
                or not (member.isfile() or member.isdir())
            ):
                raise FinalCoreReleaseError(f"unsafe immutable export member: {member.name}")
        archive.extractall(destination, filter="data")
    source = destination / expected_prefix
    if not source.is_dir():
        raise FinalCoreReleaseError("immutable Git export did not create its source root")
    return source


def export_commit(repository: Path, commit: str, destination: Path) -> tuple[Path, str]:
    """Export only tracked bytes from the requested commit with git archive."""

    archive = _git(
        repository.resolve(),
        "-c",
        "core.autocrlf=false",
        "-c",
        "core.eol=lf",
        "archive",
        "--format=tar",
        "--prefix=source/",
        commit,
    )
    identity = hashlib.sha256(archive).hexdigest()
    return _extract_tar_bytes(archive, destination, expected_prefix="source"), identity


def _build_export(source: Path, *, epoch: int) -> tuple[Path, Path]:
    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = str(epoch)
    subprocess.run(
        [sys.executable, str(source / "scripts" / "packaging" / "build_core_release.py")],
        cwd=source,
        env=environment,
        check=True,
    )
    wheels = sorted((source / "dist").glob("*.whl"))
    sdists = sorted((source / "dist").glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise FinalCoreReleaseError("immutable export build must produce exactly one wheel and one sdist")
    return wheels[0], sdists[0]


def _extract_sdist(sdist: Path, destination: Path, *, expected_root: str) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(sdist, mode="r:gz") as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or path.parts[0] != expected_root
                or member.issym()
                or member.islnk()
                or not (member.isfile() or member.isdir())
            ):
                raise FinalCoreReleaseError(f"unsafe canonical sdist member: {member.name}")
        archive.extractall(destination, filter="data")
    root = destination / expected_root
    if not root.is_dir():
        raise FinalCoreReleaseError("canonical sdist did not contain its expected root")
    return root


def _rebuild_wheel_from_canonical_sdist(
    sdist: Path,
    destination: Path,
    *,
    package: str,
    version: str,
    epoch: int,
) -> Path:
    source = _extract_sdist(
        sdist,
        destination / "source",
        expected_root=f"{package}-{version}",
    )
    output = destination / "dist"
    output.mkdir()
    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = str(epoch)
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(output), str(source)],
        cwd=destination,
        env=environment,
        check=True,
    )
    wheels = sorted(output.glob("*.whl"))
    if len(wheels) != 1:
        raise FinalCoreReleaseError("canonical sdist rebuild must produce exactly one wheel")
    return wheels[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_record(path: Path) -> dict[str, object]:
    return {
        "filename": path.name,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _require_identical(first: Path, second: Path, *, label: str) -> None:
    if first.name != second.name or first.read_bytes() != second.read_bytes():
        raise FinalCoreReleaseError(f"repeated {label} builds are not byte-identical")


def _require_new_output_directory(output_directory: Path) -> Path:
    output = output_directory.resolve()
    if output.exists():
        raise FinalCoreReleaseError(
            f"output directory must not already exist: {output}; remove old generated output first"
        )
    if not output.parent.is_dir():
        raise FinalCoreReleaseError(f"output directory parent does not exist: {output.parent}")
    return output


def prepare_final_release(
    repository: Path,
    *,
    version: str,
    commit: str,
    tag: str | None,
    output_directory: Path,
) -> Path:
    """Build, prove, record, and bind final artifacts without publishing them."""

    verified = verify_repository(
        repository,
        version=version,
        commit=commit,
        tag=tag,
    )
    output = _require_new_output_directory(output_directory)
    with tempfile.TemporaryDirectory(prefix="controlel-final-core-") as temporary:
        temporary_root = Path(temporary)
        first_source, first_export_identity = export_commit(
            repository,
            verified.commit,
            temporary_root / "export-one",
        )
        second_source, second_export_identity = export_commit(
            repository,
            verified.commit,
            temporary_root / "export-two",
        )
        if first_export_identity != second_export_identity:
            raise FinalCoreReleaseError("repeated immutable source exports are not identical")

        first_wheel, first_sdist = _build_export(first_source, epoch=verified.epoch)
        second_wheel, second_sdist = _build_export(second_source, epoch=verified.epoch)
        validate_wheel(first_wheel, distribution=verified.package, version=verified.version)
        validate_sdist(first_sdist, distribution=verified.package, version=verified.version)
        validate_wheel(second_wheel, distribution=verified.package, version=verified.version)
        validate_sdist(second_sdist, distribution=verified.package, version=verified.version)
        _require_identical(first_wheel, second_wheel, label="wheel")
        _require_identical(first_sdist, second_sdist, label="sdist")

        rebuilt_wheel = _rebuild_wheel_from_canonical_sdist(
            first_sdist,
            temporary_root / "canonical-rebuild",
            package=verified.package,
            version=verified.version,
            epoch=verified.epoch,
        )
        validate_wheel(rebuilt_wheel, distribution=verified.package, version=verified.version)
        _require_identical(first_wheel, rebuilt_wheel, label="canonical-sdist wheel")

        wheel_record = _artifact_record(first_wheel)
        sdist_record = _artifact_record(first_sdist)
        provenance: dict[str, object] = {
            "schema_version": PROVENANCE_SCHEMA_VERSION,
            "tool": {
                "name": "prepare_final_core_release",
                "version": TOOL_VERSION,
            },
            "package": verified.package,
            "release_version": verified.version,
            "commit_sha": verified.commit,
            "tag": verified.tag,
            "tag_type": verified.tag_type,
            "resolved_tag_commit": verified.resolved_tag_commit,
            "source_export": {
                "mechanism": "git archive",
                "commit_sha": verified.commit,
                "tree_sha": verified.tree,
                "archive_sha256": first_export_identity,
            },
            "build": {
                "epoch": verified.epoch,
                "timestamp_source": "commit_committer_timestamp",
                "repeated_builds_byte_identical": True,
                "canonical_sdist_wheel_byte_identical": True,
            },
            "artifact_directory": ".",
            "artifacts": {
                "wheel": wheel_record,
                "sdist": sdist_record,
            },
            "upload_artifacts": [wheel_record["filename"], sdist_record["filename"]],
            "verification_status": "passed",
        }

        output.mkdir()
        (output / first_wheel.name).write_bytes(first_wheel.read_bytes())
        (output / first_sdist.name).write_bytes(first_sdist.read_bytes())
        manifest = output / PROVENANCE_FILENAME
        manifest.write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        validate_upload_binding(manifest, output)
        return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tag")
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    manifest = prepare_final_release(
        REPOSITORY_ROOT,
        version=arguments.version,
        commit=arguments.commit,
        tag=arguments.tag,
        output_directory=arguments.output_dir,
    )
    print(f"Prepared provenance-bound core release artifacts: {manifest.parent}")
    print(f"Provenance manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
