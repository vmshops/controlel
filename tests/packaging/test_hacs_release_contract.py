import hashlib
import json
import shutil
import stat
import zipfile
from pathlib import Path

import pytest

from scripts.packaging.build_hacs_release import build_archive
from scripts.packaging.validate_hacs_release import (
    ARCHIVE_FILENAME,
    EXPECTED_ARCHIVE_FILES,
    EXPECTED_HACS_MANIFEST,
    FIXED_ZIP_MODE,
    FIXED_ZIP_TIMESTAMP,
    HacsReleaseValidationError,
    validate_archive,
    validate_source,
)

ROOT = Path(__file__).parents[2]
INTEGRATION_VERSION = "0.8.0"


def test_hacs_source_contract_is_exact() -> None:
    files = validate_source(ROOT, version=INTEGRATION_VERSION)

    assert set(files) == EXPECTED_ARCHIVE_FILES
    assert json.loads((ROOT / "hacs.json").read_text(encoding="utf-8")) == EXPECTED_HACS_MANIFEST


def test_builder_is_deterministic_and_records_a_valid_checksum(tmp_path: Path) -> None:
    first = tmp_path / "first" / ARCHIVE_FILENAME
    second = tmp_path / "second" / ARCHIVE_FILENAME

    first_digest = build_archive(first, version=INTEGRATION_VERSION)
    second_digest = build_archive(second, version=INTEGRATION_VERSION)

    assert first.read_bytes() == second.read_bytes()
    assert first_digest == second_digest == hashlib.sha256(first.read_bytes()).hexdigest()
    assert first.with_name(f"{ARCHIVE_FILENAME}.sha256").read_text(encoding="ascii") == (
        f"{first_digest}  {ARCHIVE_FILENAME}\n"
    )
    assert validate_archive(first, version=INTEGRATION_VERSION) == first_digest

    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == sorted(EXPECTED_ARCHIVE_FILES)
        assert all(info.date_time == FIXED_ZIP_TIMESTAMP for info in archive.infolist())
        assert all(info.external_attr >> 16 == FIXED_ZIP_MODE for info in archive.infolist())
        assert all(not info.filename.startswith("custom_components/") for info in archive.infolist())


def test_validator_rejects_a_nested_component_root(tmp_path: Path) -> None:
    archive_path = tmp_path / ARCHIVE_FILENAME
    with zipfile.ZipFile(archive_path, "w") as archive:
        info = zipfile.ZipInfo(
            "custom_components/controlel/manifest.json",
            date_time=FIXED_ZIP_TIMESTAMP,
        )
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        archive.writestr(info, b"{}")

    with pytest.raises(HacsReleaseValidationError, match="file set mismatch"):
        validate_archive(archive_path, version=INTEGRATION_VERSION)


def test_validator_rejects_path_traversal_before_reading_content(tmp_path: Path) -> None:
    archive_path = tmp_path / ARCHIVE_FILENAME
    with zipfile.ZipFile(archive_path, "w") as archive:
        info = zipfile.ZipInfo("../secret", date_time=FIXED_ZIP_TIMESTAMP)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = FIXED_ZIP_MODE << 16
        archive.writestr(info, b"not a secret")

    with pytest.raises(HacsReleaseValidationError, match="unsafe or non-normalized"):
        validate_archive(archive_path, version=INTEGRATION_VERSION)


def test_validator_rejects_symlinks_and_duplicate_paths(tmp_path: Path) -> None:
    symlink_archive = tmp_path / "symlink" / ARCHIVE_FILENAME
    symlink_archive.parent.mkdir()
    with zipfile.ZipFile(symlink_archive, "w") as archive:
        info = zipfile.ZipInfo("manifest.json", date_time=FIXED_ZIP_TIMESTAMP)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, b"const.py")

    with pytest.raises(HacsReleaseValidationError, match="contains symlink"):
        validate_archive(symlink_archive, version=INTEGRATION_VERSION)

    duplicate_archive = tmp_path / "duplicate" / ARCHIVE_FILENAME
    duplicate_archive.parent.mkdir()
    with (
        zipfile.ZipFile(duplicate_archive, "w") as archive,
        pytest.warns(UserWarning, match="Duplicate name"),
    ):
        for _ in range(2):
            info = zipfile.ZipInfo("manifest.json", date_time=FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = FIXED_ZIP_MODE << 16
            archive.writestr(info, b"{}")

    with pytest.raises(HacsReleaseValidationError, match="duplicate paths"):
        validate_archive(duplicate_archive, version=INTEGRATION_VERSION)


def test_source_validator_rejects_secret_like_content_and_wrong_core_pin(tmp_path: Path) -> None:
    release_root = tmp_path / "release-root"
    shutil.copytree(ROOT / "custom_components", release_root / "custom_components")
    shutil.copy2(ROOT / "hacs.json", release_root / "hacs.json")
    component = release_root / "custom_components" / "controlel"
    component.joinpath("const.py").write_text(
        component.joinpath("const.py").read_text(encoding="utf-8") + "\n# github_pat_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n",
        encoding="utf-8",
    )

    with pytest.raises(HacsReleaseValidationError, match="secret-like content"):
        validate_source(release_root, version=INTEGRATION_VERSION)

    shutil.copy2(ROOT / "custom_components" / "controlel" / "const.py", component / "const.py")
    manifest_path = component / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["requirements"] = ["controlel==9.9.9"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(HacsReleaseValidationError, match="release metadata mismatch"):
        validate_source(release_root, version=INTEGRATION_VERSION)


def test_release_workflow_is_validation_only_and_uploads_inspection_artifacts() -> None:
    workflow = (ROOT / ".github" / "workflows" / "integration-release-validation.yml").read_text(encoding="utf-8")

    assert "python scripts/packaging/build_hacs_release.py --version 0.8.0" in workflow
    assert "python scripts/packaging/validate_hacs_release.py" in workflow
    assert "category: integration" in workflow
    assert "ignore: brands" in workflow
    assert "home-assistant/actions/hassfest@" in workflow
    assert "actions/upload-artifact@" in workflow
    assert "contents: read" in workflow
    forbidden = ("gh release", "create-release", "contents: write", "pypi", "twine upload")
    assert not any(value in workflow.casefold() for value in forbidden)
