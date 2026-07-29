"""Build deterministic core wheel and source-distribution artifacts."""

from __future__ import annotations

import argparse
import gzip
import os
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path, PurePosixPath

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class CoreReleaseBuildError(RuntimeError):
    """Raised when the deterministic core build contract is violated."""


def _project_identity() -> tuple[str, str]:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        project = tomllib.load(pyproject_file)["project"]
    return project["name"], project["version"]


def _source_date_epoch() -> int:
    configured = os.environ.get("SOURCE_DATE_EPOCH")
    if configured is not None:
        try:
            epoch = int(configured)
        except ValueError as error:
            raise CoreReleaseBuildError("SOURCE_DATE_EPOCH must be an integer") from error
    else:
        try:
            result = subprocess.run(
                ["git", "show", "-s", "--format=%ct", "HEAD"],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            epoch = int(result.stdout.strip())
        except (FileNotFoundError, subprocess.CalledProcessError, ValueError) as error:
            raise CoreReleaseBuildError(
                "SOURCE_DATE_EPOCH is required when the source is not a Git checkout"
            ) from error
    if epoch < 0:
        raise CoreReleaseBuildError("SOURCE_DATE_EPOCH must not be negative")
    return epoch


def _safe_member_name(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise CoreReleaseBuildError(f"unsafe sdist member path: {name}")


def canonicalize_sdist(sdist: Path, *, epoch: int) -> None:
    """Normalize an sdist's container metadata without changing its file content."""

    temporary_path: Path | None = None
    try:
        with tarfile.open(sdist, mode="r:gz") as source:
            members = sorted(source.getmembers(), key=lambda member: member.name)
            with tempfile.NamedTemporaryFile(
                dir=sdist.parent,
                prefix=f".{sdist.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                with gzip.GzipFile(
                    filename="",
                    mode="wb",
                    fileobj=temporary_file,
                    compresslevel=9,
                    mtime=epoch,
                ) as compressed:
                    with tarfile.open(
                        fileobj=compressed,
                        mode="w",
                        format=tarfile.PAX_FORMAT,
                    ) as target:
                        for member in members:
                            _safe_member_name(member.name)
                            normalized = tarfile.TarInfo(member.name)
                            normalized.mtime = epoch
                            normalized.uid = 0
                            normalized.gid = 0
                            normalized.uname = ""
                            normalized.gname = ""
                            if member.isdir():
                                normalized.type = tarfile.DIRTYPE
                                normalized.mode = 0o755
                                target.addfile(normalized)
                                continue
                            if not member.isfile():
                                raise CoreReleaseBuildError(f"sdist contains unsupported member type: {member.name}")
                            normalized.type = tarfile.REGTYPE
                            normalized.mode = 0o644
                            normalized.size = member.size
                            extracted = source.extractfile(member)
                            if extracted is None:
                                raise CoreReleaseBuildError(f"could not read sdist member: {member.name}")
                            with extracted:
                                target.addfile(normalized, extracted)
        if temporary_path is None:
            raise CoreReleaseBuildError("failed to create canonical sdist")
        temporary_path.replace(sdist)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def build_core_release() -> tuple[Path, Path]:
    """Run the PEP 517 build and canonicalize the generated sdist."""

    distribution, version = _project_identity()
    epoch = _source_date_epoch()
    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = str(epoch)
    subprocess.run(
        [sys.executable, "-m", "build"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=True,
    )

    dist_directory = REPOSITORY_ROOT / "dist"
    wheel = dist_directory / f"{distribution.replace('-', '_')}-{version}-py3-none-any.whl"
    sdist = dist_directory / f"{distribution}-{version}.tar.gz"
    if not wheel.is_file() or not sdist.is_file():
        raise CoreReleaseBuildError(f"build did not produce the expected artifacts: {wheel.name}, {sdist.name}")
    canonicalize_sdist(sdist, epoch=epoch)
    return wheel, sdist


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    wheel, sdist = build_core_release()
    print(f"Built deterministic wheel: {wheel}")
    print(f"Built deterministic sdist: {sdist}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
