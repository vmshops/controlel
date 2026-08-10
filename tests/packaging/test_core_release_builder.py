import gzip
import struct
import tarfile
from io import BytesIO
from pathlib import Path

import pytest

from scripts.packaging.build_core_release import (
    CoreReleaseBuildError,
    _source_date_epoch,
    canonicalize_sdist,
)

EPOCH = 1_700_000_000


def _write_varying_sdist(
    path: Path,
    *,
    mtime: float,
    reverse_members: bool,
) -> None:
    members = [
        ("controlel-0.4.0", None),
        ("controlel-0.4.0/PKG-INFO", b"Metadata-Version: 2.4\nName: controlel\nVersion: 0.4.0\n"),
        (
            "controlel-0.4.0/src/controlel/application/services/temperature_hysteresis_policy.py",
            b'"""Policy."""\n',
        ),
    ]
    if reverse_members:
        members.reverse()

    with path.open("wb") as raw:
        with gzip.GzipFile(
            filename=f"varying-{mtime}.tar",
            mode="wb",
            fileobj=raw,
            mtime=int(mtime),
        ) as compressed:
            with tarfile.open(
                fileobj=compressed,
                mode="w",
                format=tarfile.PAX_FORMAT,
            ) as archive:
                for name, content in members:
                    member = tarfile.TarInfo(name)
                    member.mtime = mtime
                    member.uid = int(mtime) % 1000
                    member.gid = int(mtime) % 500
                    member.uname = "builder"
                    member.gname = "build"
                    if content is None:
                        member.type = tarfile.DIRTYPE
                        member.mode = 0o775
                        archive.addfile(member)
                    else:
                        member.mode = 0o664
                        member.size = len(content)
                        archive.addfile(member, BytesIO(content))


def test_canonicalize_sdist_removes_all_container_metadata_variance(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    _write_varying_sdist(first, mtime=1_800_000_000.125, reverse_members=False)
    _write_varying_sdist(second, mtime=1_900_000_000.875, reverse_members=True)

    canonicalize_sdist(first, epoch=EPOCH)
    canonicalize_sdist(second, epoch=EPOCH)

    assert first.read_bytes() == second.read_bytes()
    header = first.read_bytes()[:10]
    assert header[3] & 0x08 == 0
    assert struct.unpack("<I", header[4:8])[0] == EPOCH

    with tarfile.open(first, mode="r:gz") as archive:
        members = archive.getmembers()
        assert [member.name for member in members] == sorted(member.name for member in members)
        for member in members:
            assert member.mtime == EPOCH
            assert "mtime" not in member.pax_headers
            assert member.uid == 0
            assert member.gid == 0
            assert member.uname == ""
            assert member.gname == ""
            assert member.mode == (0o755 if member.isdir() else 0o644)
        pkg_info = archive.extractfile("controlel-0.4.0/PKG-INFO")
        assert pkg_info is not None
        assert b"Version: 0.4.0" in pkg_info.read()


def test_source_date_epoch_accepts_only_non_negative_integer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", str(EPOCH))
    assert _source_date_epoch() == EPOCH

    monkeypatch.setenv("SOURCE_DATE_EPOCH", "not-an-integer")
    with pytest.raises(CoreReleaseBuildError, match="must be an integer"):
        _source_date_epoch()

    monkeypatch.setenv("SOURCE_DATE_EPOCH", "-1")
    with pytest.raises(CoreReleaseBuildError, match="must not be negative"):
        _source_date_epoch()
