from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.packaging import prepare_final_core_release as prepare
from scripts.packaging import validate_core_release_provenance as provenance

WHEEL_NAME = "controlel-0.3.0-py3-none-any.whl"
SDIST_NAME = "controlel-0.3.0.tar.gz"
WHEEL_BYTES = b"deterministic-wheel-from-immutable-export\n"
SDIST_BYTES = b"deterministic-sdist-from-immutable-export\n"


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_bytes(repository: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
    ).stdout


@pytest.fixture
def release_repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    (repository / "src" / "controlel").mkdir(parents=True)
    (repository / ".gitignore").write_text("dist/\nbuild/\n*.egg-info/\n", encoding="utf-8")
    (repository / "pyproject.toml").write_text(
        """[build-system]
requires = ["setuptools>=77.0.3"]
build-backend = "setuptools.build_meta"

[project]
name = "controlel"
version = "0.3.0"
""",
        encoding="utf-8",
    )
    (repository / "README.md").write_text("clean committed readme\n", encoding="utf-8")
    (repository / "src" / "controlel" / "__init__.py").write_text(
        'SOURCE_MARKER = "clean committed source"\n',
        encoding="utf-8",
    )
    _git(repository, "init")
    _git(repository, "config", "user.name", "Controlel Tests")
    _git(repository, "config", "user.email", "tests@example.invalid")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "release fixture")
    return repository, _git(repository, "rev-parse", "HEAD")


def _install_fake_build(
    monkeypatch: pytest.MonkeyPatch,
    *,
    observed_readmes: list[bytes] | None = None,
    rebuilt_wheel_bytes: bytes = WHEEL_BYTES,
) -> None:
    def fake_build(source: Path, *, epoch: int) -> tuple[Path, Path]:
        assert epoch > 0
        if observed_readmes is not None:
            observed_readmes.append((source / "README.md").read_bytes())
        output = source / "dist"
        output.mkdir()
        wheel = output / WHEEL_NAME
        sdist = output / SDIST_NAME
        wheel.write_bytes(WHEEL_BYTES)
        sdist.write_bytes(SDIST_BYTES)
        return wheel, sdist

    def fake_rebuild(
        sdist: Path,
        destination: Path,
        *,
        package: str,
        version: str,
        epoch: int,
    ) -> Path:
        assert sdist.read_bytes() == SDIST_BYTES
        assert (package, version) == ("controlel", "0.3.0")
        assert epoch > 0
        destination.mkdir(parents=True)
        wheel = destination / WHEEL_NAME
        wheel.write_bytes(rebuilt_wheel_bytes)
        return wheel

    monkeypatch.setattr(prepare, "_build_export", fake_build)
    monkeypatch.setattr(prepare, "_rebuild_wheel_from_canonical_sdist", fake_rebuild)
    monkeypatch.setattr(prepare, "validate_wheel", lambda *args, **kwargs: None)
    monkeypatch.setattr(prepare, "validate_sdist", lambda *args, **kwargs: None)
    monkeypatch.setattr(prepare, "validate_upload_binding", lambda *args, **kwargs: None)


def _prepare(
    repository: Path,
    commit: str,
    output: Path,
    *,
    tag: str | None = None,
) -> Path:
    return prepare.prepare_final_release(
        repository,
        version="0.3.0",
        commit=commit,
        tag=tag,
        output_directory=output,
    )


def _allow_fake_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provenance, "validate_wheel", lambda *args, **kwargs: None)
    monkeypatch.setattr(provenance, "validate_sdist", lambda *args, **kwargs: None)


def test_clean_exact_commit_succeeds_with_annotated_tag_and_stable_provenance(
    release_repository: tuple[Path, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, commit = release_repository
    _git(repository, "tag", "-a", "core-v0.3.0", "-m", "Core 0.3.0", commit)
    _install_fake_build(monkeypatch)

    manifest_path = _prepare(repository, commit, tmp_path / "final", tag="core-v0.3.0")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 1
    assert manifest["package"] == "controlel"
    assert manifest["release_version"] == "0.3.0"
    assert manifest["commit_sha"] == commit
    assert manifest["tag"] == "core-v0.3.0"
    assert manifest["tag_type"] == "annotated"
    assert manifest["resolved_tag_commit"] == commit
    assert manifest["source_export"]["mechanism"] == "git archive"
    assert manifest["source_export"]["commit_sha"] == commit
    assert manifest["verification_status"] == "passed"


def test_dirty_tracked_source_or_packaging_file_is_rejected(
    release_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repository, commit = release_repository
    (repository / "pyproject.toml").write_text("dirty packaging input\n", encoding="utf-8")

    with pytest.raises(prepare.FinalCoreReleaseError, match="requires a clean checkout"):
        _prepare(repository, commit, tmp_path / "final")


def test_relevant_untracked_source_is_rejected(
    release_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repository, commit = release_repository
    (repository / "src" / "controlel" / "untracked.py").write_text("VALUE = 1\n", encoding="utf-8")

    with pytest.raises(prepare.FinalCoreReleaseError, match="untracked.py"):
        _prepare(repository, commit, tmp_path / "final")


def test_ignored_dist_output_cannot_contaminate_immutable_export(
    release_repository: tuple[Path, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, commit = release_repository
    ignored = repository / "dist" / "old-candidate.whl"
    ignored.parent.mkdir()
    ignored.write_bytes(b"must never be an input")
    observed: list[bytes] = []
    committed_readme = _git_bytes(repository, "show", f"{commit}:README.md")
    _install_fake_build(monkeypatch, observed_readmes=observed)

    _prepare(repository, commit, tmp_path / "final")

    assert observed == [committed_readme, committed_readme]


def test_wrong_requested_head_relationship_is_rejected(
    release_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repository, first_commit = release_repository
    (repository / "notes.txt").write_text("second commit\n", encoding="utf-8")
    _git(repository, "add", "notes.txt")
    _git(repository, "commit", "-m", "second")

    with pytest.raises(prepare.FinalCoreReleaseError, match="does not equal requested"):
        _prepare(repository, first_commit, tmp_path / "final")


def test_nonexistent_commit_is_rejected(
    release_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repository, _ = release_repository

    with pytest.raises(prepare.FinalCoreReleaseError, match="Git verification failed"):
        _prepare(repository, "0" * 40, tmp_path / "final")


def test_wrong_tag_target_is_rejected(
    release_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repository, first_commit = release_repository
    _git(repository, "tag", "-a", "core-v0.3.0", "-m", "Core 0.3.0", first_commit)
    (repository / "notes.txt").write_text("second commit\n", encoding="utf-8")
    _git(repository, "add", "notes.txt")
    _git(repository, "commit", "-m", "second")
    second_commit = _git(repository, "rev-parse", "HEAD")

    with pytest.raises(prepare.FinalCoreReleaseError, match="resolves to"):
        _prepare(repository, second_commit, tmp_path / "final", tag="core-v0.3.0")


def test_lightweight_release_tag_is_explicitly_rejected(
    release_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repository, commit = release_repository
    _git(repository, "tag", "core-v0.3.0", commit)

    with pytest.raises(prepare.FinalCoreReleaseError, match="lightweight.*must be annotated"):
        _prepare(repository, commit, tmp_path / "final", tag="core-v0.3.0")


def test_version_and_release_tag_mismatches_are_rejected(
    release_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repository, commit = release_repository
    with pytest.raises(prepare.FinalCoreReleaseError, match="package version"):
        prepare.prepare_final_release(
            repository,
            version="0.4.0",
            commit=commit,
            tag=None,
            output_directory=tmp_path / "version-mismatch",
        )
    with pytest.raises(prepare.FinalCoreReleaseError, match="release tag must be"):
        _prepare(repository, commit, tmp_path / "tag-mismatch", tag="core-v0.4.0")


def test_provenance_matches_bytes_and_binds_only_exact_upload_inputs(
    release_repository: tuple[Path, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, commit = release_repository
    _install_fake_build(monkeypatch)
    manifest_path = _prepare(repository, commit, tmp_path / "final")
    _allow_fake_artifacts(monkeypatch)

    wheel, sdist = provenance.validate_upload_binding(manifest_path, manifest_path.parent)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert wheel.read_bytes() == WHEEL_BYTES
    assert sdist.read_bytes() == SDIST_BYTES
    assert manifest["artifacts"]["wheel"] == prepare._artifact_record(wheel)
    assert manifest["artifacts"]["sdist"] == prepare._artifact_record(sdist)
    assert manifest["upload_artifacts"] == [WHEEL_NAME, SDIST_NAME]


def test_changed_artifact_after_manifest_creation_is_rejected(
    release_repository: tuple[Path, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, commit = release_repository
    _install_fake_build(monkeypatch)
    manifest = _prepare(repository, commit, tmp_path / "final")
    _allow_fake_artifacts(monkeypatch)
    (manifest.parent / WHEEL_NAME).write_bytes(b"substituted bytes")

    with pytest.raises(provenance.ProvenanceValidationError, match="size differs|SHA-256 differs"):
        provenance.validate_upload_binding(manifest, manifest.parent)


def test_truncated_or_internally_inconsistent_provenance_is_rejected(
    release_repository: tuple[Path, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, commit = release_repository
    _install_fake_build(monkeypatch)
    manifest_path = _prepare(repository, commit, tmp_path / "final")
    _allow_fake_artifacts(monkeypatch)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_export"]["commit_sha"] = "f" * 40
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(provenance.ProvenanceValidationError, match="source-export identity"):
        provenance.validate_upload_binding(manifest_path, manifest_path.parent)


def test_substituted_directory_or_extra_artifact_is_rejected(
    release_repository: tuple[Path, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, commit = release_repository
    _install_fake_build(monkeypatch)
    manifest = _prepare(repository, commit, tmp_path / "final")
    _allow_fake_artifacts(monkeypatch)
    substituted = tmp_path / "substituted"
    shutil.copytree(manifest.parent, substituted)

    with pytest.raises(provenance.ProvenanceValidationError, match="directory containing"):
        provenance.validate_upload_binding(manifest, substituted)

    (manifest.parent / "other-0.3.0-py3-none-any.whl").write_bytes(WHEEL_BYTES)
    with pytest.raises(provenance.ProvenanceValidationError, match="unexpected or substituted wheel"):
        provenance.validate_upload_binding(manifest, manifest.parent)


def test_canonical_sdist_rebuild_must_produce_the_identical_wheel(
    release_repository: tuple[Path, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, commit = release_repository
    _install_fake_build(monkeypatch, rebuilt_wheel_bytes=b"different rebuilt wheel")

    with pytest.raises(prepare.FinalCoreReleaseError, match="canonical-sdist wheel"):
        _prepare(repository, commit, tmp_path / "final")


def test_git_archive_contains_only_requested_commit_bytes_even_if_caller_is_dirty(
    release_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repository, commit = release_repository
    committed_readme = _git_bytes(repository, "show", f"{commit}:README.md")
    committed_source = _git_bytes(repository, "show", f"{commit}:src/controlel/__init__.py")
    (repository / "README.md").write_text("dirty caller readme\n", encoding="utf-8")
    (repository / "src" / "controlel" / "__init__.py").write_bytes(b'SOURCE_MARKER = "dirty caller source"\r\n')

    source, _ = prepare.export_commit(repository, commit, tmp_path / "export")

    assert (source / "README.md").read_bytes() == committed_readme
    assert (source / "src" / "controlel" / "__init__.py").read_bytes() == committed_source


def test_0_3_0_incident_regression_refuses_dirty_readme_and_line_endings(
    release_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repository, commit = release_repository
    (repository / "README.md").write_text("candidate text not in release commit\n", encoding="utf-8")
    source_path = repository / "src" / "controlel" / "__init__.py"
    committed_source = _git_bytes(repository, "show", f"{commit}:src/controlel/__init__.py")
    changed_line_endings = (
        committed_source.replace(b"\r\n", b"\n")
        if b"\r\n" in committed_source
        else committed_source.replace(b"\n", b"\r\n")
    )
    source_path.write_bytes(changed_line_endings)
    output = tmp_path / "must-not-exist"

    with pytest.raises(prepare.FinalCoreReleaseError, match="requires a clean checkout"):
        _prepare(repository, commit, output)

    assert not output.exists()


def test_output_directory_must_be_new_to_prevent_older_candidate_substitution(
    release_repository: tuple[Path, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, commit = release_repository
    _install_fake_build(monkeypatch)
    output = tmp_path / "existing"
    output.mkdir()

    with pytest.raises(prepare.FinalCoreReleaseError, match="must not already exist"):
        _prepare(repository, commit, output)
