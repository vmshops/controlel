import importlib.metadata
import json
import tomllib
from pathlib import Path

import pytest
from trove_classifiers import classifiers

import controlel
from scripts.packaging.validate_artifacts import (
    ArtifactValidationError,
    _assert_no_forbidden_content,
)

ROOT = Path(__file__).parents[2]


def load_pyproject() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as pyproject_file:
        return tomllib.load(pyproject_file)


def test_build_backend_and_src_package_discovery_are_explicit() -> None:
    pyproject = load_pyproject()

    assert pyproject["build-system"] == {
        "requires": ["setuptools>=77.0.3"],
        "build-backend": "setuptools.build_meta",
    }
    assert pyproject["tool"]["setuptools"]["packages"]["find"] == {
        "where": ["src"],
        "include": ["controlel*"],
    }
    assert pyproject["tool"]["setuptools"]["include-package-data"] is False


def test_project_metadata_and_runtime_dependencies_match_release_contract() -> None:
    project = load_pyproject()["project"]

    assert project["name"] == "controlel"
    assert project["version"] == "0.1.0"
    assert project["readme"] == "README.md"
    assert project["requires-python"] == ">=3.13"
    assert project["license"] == "MIT"
    assert project["authors"] == [{"name": "vmshops"}]
    assert project["dependencies"] == ["pydantic>=2.0"]
    assert project["classifiers"] == [
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ]
    assert project["urls"] == {
        "Source": "https://github.com/vmshops/controlel",
        "Issues": "https://github.com/vmshops/controlel/issues",
        "Documentation": "https://github.com/vmshops/controlel/tree/main/docs",
    }
    forbidden = {
        "homeassistant",
        "pytest",
        "ruff",
        "pre-commit",
        "pip-tools",
        "build",
        "twine",
        "pytest-homeassistant-custom-component",
    }
    assert not any(name in dependency.casefold() for name in forbidden for dependency in project["dependencies"])


def test_all_project_classifiers_are_official_trove_classifiers() -> None:
    declared_classifiers = load_pyproject()["project"]["classifiers"]

    assert len(declared_classifiers) == len(set(declared_classifiers))
    assert set(declared_classifiers) <= classifiers


def test_project_version_is_the_only_release_version_source() -> None:
    project_version = load_pyproject()["project"]["version"]
    package_source = (ROOT / "src" / "controlel" / "__init__.py").read_text(encoding="utf-8")
    version_files = [
        path for path in (ROOT / "src" / "controlel").rglob("*.py") if "__version__" in path.read_text(encoding="utf-8")
    ]

    assert project_version == "0.1.0"
    assert controlel.__version__ == project_version
    assert importlib.metadata.version("controlel") == project_version
    assert version_files == [ROOT / "src" / "controlel" / "__init__.py"]
    assert 'version("controlel")' in package_source
    assert "0.0.0+uninstalled" in package_source
    assert project_version not in package_source


def test_manifest_pins_published_core_and_keeps_version_independent() -> None:
    manifest = json.loads((ROOT / "custom_components" / "controlel" / "manifest.json").read_text(encoding="utf-8"))
    core_version = load_pyproject()["project"]["version"]

    assert core_version == "0.1.0"
    assert manifest["requirements"] == [f"controlel=={core_version}"]
    assert manifest["version"] == "0.3.0"
    assert manifest["version"] != core_version
    assert manifest["issue_tracker"] == "https://github.com/vmshops/controlel/issues"


def test_packaging_tools_are_pinned_and_isolated() -> None:
    requirements = (ROOT / "requirements" / "package-test.txt").read_text(encoding="utf-8").splitlines()

    assert requirements == [
        "build==1.5.0",
        "trove-classifiers==2026.6.1.19",
        "twine==6.2.0",
    ]
    assert not (ROOT / "src" / "controlel" / "py.typed").exists()


def test_artifact_policy_rejects_repository_and_secret_content() -> None:
    with pytest.raises(ArtifactValidationError, match="forbidden path"):
        _assert_no_forbidden_content(["controlel/__init__.py", "tests/test_core.py"], artifact="test.whl")
    with pytest.raises(ArtifactValidationError, match="forbidden file"):
        _assert_no_forbidden_content(["controlel/__init__.py", ".pypirc"], artifact="test.tar.gz")


def test_packaging_ci_builds_and_validates_without_publishing() -> None:
    workflow = (ROOT / ".github" / "workflows" / "packaging.yml").read_text(encoding="utf-8")

    required_commands = {
        "python -m build",
        "python -m twine check dist/*",
        "python scripts/packaging/validate_artifacts.py dist",
        "python scripts/packaging/verify_clean_install.py dist",
    }
    assert all(command in workflow for command in required_commands)
    assert "actions/checkout@v5" in workflow
    assert "actions/setup-python@v6" in workflow
    assert "publish" not in workflow.casefold()
    assert "upload" not in workflow.casefold()
    assert "token" not in workflow.casefold()
