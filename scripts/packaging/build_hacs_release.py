"""Build the deterministic Controlel HACS release ZIP."""

from __future__ import annotations

import argparse
import io
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path

if __package__:
    from .validate_hacs_release import (
        ARCHIVE_FILENAME,
        FIXED_ZIP_MODE,
        FIXED_ZIP_TIMESTAMP,
        ROOT,
        validate_archive,
        validate_source,
        write_checksum,
    )
else:
    from validate_hacs_release import (
        ARCHIVE_FILENAME,
        FIXED_ZIP_MODE,
        FIXED_ZIP_TIMESTAMP,
        ROOT,
        validate_archive,
        validate_source,
        write_checksum,
    )


def build_archive(
    output: Path,
    *,
    version: str,
    root: Path = ROOT,
) -> str:
    """Build, validate, and hash one deterministic release archive."""
    if output.name != ARCHIVE_FILENAME:
        raise ValueError(f"output must be named {ARCHIVE_FILENAME}")
    files = validate_source(root, version=version)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_archive_bytes(files))
    digest = validate_archive(output, version=version)
    write_checksum(
        output.with_name(f"{output.name}.sha256"),
        archive=output,
        digest=digest,
    )
    return digest


def _archive_bytes(files: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = FIXED_ZIP_MODE << 16
            archive.writestr(info, files[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return buffer.getvalue()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "hacs" / ARCHIVE_FILENAME,
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    digest = build_archive(
        arguments.output,
        version=arguments.version,
    )
    print(f"Built {arguments.output} with SHA-256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
